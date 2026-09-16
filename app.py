"""
Question of the Week — Web Application
=======================================

A Flask web app that serves a weekly opinion poll / question.
Users authenticate via Microsoft Entra ID (Azure AD) and can vote once per question.
No correct answers — it's about seeing what the team thinks!

Features:
  - Weekly polls (Mon–Fri) with 2-4 options
  - One vote per user per poll (duplicate prevention)
  - Live results with vote counts, percentages, and progress bars
  - Comments — defend your pick after voting
  - Emoji reactions on results (👏 😂 🤯 🔥 💡)
  - Voting streak tracking & fun stats
  - Countdown timer showing when the poll closes
  - Participation board
  - Poll history with past results

Usage:
  pip install -r requirements.txt
  python app.py                          # Development mode
  gunicorn -w 4 -b 0.0.0.0:8000 app:app # Production (Linux)
  waitress-serve --port=8000 app:app     # Production (Windows)

Environment variables:
  AZURE_CLIENT_ID       - Azure AD app registration client ID
  AZURE_CLIENT_SECRET   - Azure AD app registration client secret
  AZURE_TENANT_ID       - Azure AD tenant ID
  SECRET_KEY            - Flask session secret (auto-generated if not set)
  DATABASE_URL          - SQLite path (default: sqlite:///qotw.db)
  PORT                  - Port to run on (default: 8000)
"""

import os
import secrets
from datetime import datetime, date, timedelta
from functools import wraps
from collections import Counter

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
import msal

# ---------------------------------------------------------------------------
# App Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Database — always resolve relative to this file's directory
_basedir = os.path.abspath(os.path.dirname(__file__))
_default_db = "sqlite:///" + os.path.join(_basedir, "qotw.db")
db_path = os.environ.get("DATABASE_URL", _default_db)
app.config["SQLALCHEMY_DATABASE_URI"] = db_path
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Azure AD / Entra ID Configuration
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
REDIRECT_PATH = "/auth/callback"
SCOPE = ["User.Read"]

AUTH_ENABLED = bool(AZURE_CLIENT_ID)

# Available emoji reactions
EMOJI_OPTIONS = ["👏", "😂", "🤯", "🔥", "💡"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_current_week_monday():
    """Return the Monday of the current week."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def get_week_end(monday):
    """Return the Friday of the week starting on the given Monday."""
    return monday + timedelta(days=4)


def is_poll_open(question):
    """Check if a poll is still open for voting (before Friday 5pm)."""
    if not question:
        return False
    now = datetime.now()
    friday_close = datetime.combine(
        question.week_start + timedelta(days=4),
        datetime.min.time()
    ) + timedelta(hours=17)
    return now <= friday_close


# ---------------------------------------------------------------------------
# Database Models
# ---------------------------------------------------------------------------


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=True)
    option_d = db.Column(db.String(200), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    week_start = db.Column(db.Date, nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    responses = db.relationship("Response", backref="question", lazy=True)
    comments = db.relationship("Comment", backref="question", lazy=True,
                                order_by="Comment.created_at.desc()")
    reactions = db.relationship("Reaction", backref="question", lazy=True)

    @property
    def week_end(self):
        return self.week_start + timedelta(days=4)

    @property
    def week_label(self):
        mon = self.week_start
        fri = self.week_end
        if mon.month == fri.month:
            return f"{mon.strftime('%d %b')} – {fri.strftime('%d %b %Y')}"
        return f"{mon.strftime('%d %b')} – {fri.strftime('%d %b %Y')}"

    @property
    def total_votes(self):
        return len(self.responses)

    @property
    def votes_a(self):
        return sum(1 for r in self.responses if r.selected_option == "A")

    @property
    def votes_b(self):
        return sum(1 for r in self.responses if r.selected_option == "B")

    @property
    def votes_c(self):
        return sum(1 for r in self.responses if r.selected_option == "C")

    @property
    def votes_d(self):
        return sum(1 for r in self.responses if r.selected_option == "D")

    def votes_for(self, letter):
        return sum(1 for r in self.responses if r.selected_option == letter)

    def pct(self, letter):
        total = self.total_votes
        if total == 0:
            return 0
        return round(self.votes_for(letter) * 100 / total)

    @property
    def winning_option(self):
        if self.total_votes == 0:
            return None
        options = {}
        for letter in ("A", "B", "C", "D"):
            text = getattr(self, f"option_{letter.lower()}")
            if text:
                options[letter] = self.votes_for(letter)
        if not options:
            return None
        max_votes = max(options.values())
        if max_votes == 0:
            return None
        winners = [k for k, v in options.items() if v == max_votes]
        return winners[0] if len(winners) == 1 else None

    @property
    def reaction_counts(self):
        """Return a dict of emoji -> count."""
        counts = Counter(r.emoji for r in self.reactions)
        return {emoji: counts.get(emoji, 0) for emoji in EMOJI_OPTIONS}

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
            "option_d": self.option_d,
            "category": self.category,
            "week_start": self.week_start.isoformat(),
            "week_label": self.week_label,
            "total_votes": self.total_votes,
            "votes": {
                "A": self.votes_a, "B": self.votes_b,
                "C": self.votes_c, "D": self.votes_d,
            },
            "percentages": {
                "A": self.pct("A"), "B": self.pct("B"),
                "C": self.pct("C"), "D": self.pct("D"),
            },
            "winning_option": self.winning_option,
            "reaction_counts": self.reaction_counts,
        }


class Response(db.Model):
    __tablename__ = "responses"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    user_email = db.Column(db.String(200), nullable=False)
    user_name = db.Column(db.String(200), nullable=True)
    selected_option = db.Column(db.String(1), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("question_id", "user_email", name="unique_vote"),
    )


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    user_email = db.Column(db.String(200), nullable=False)
    user_name = db.Column(db.String(200), nullable=True)
    text = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reaction(db.Model):
    __tablename__ = "reactions"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    user_email = db.Column(db.String(200), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("question_id", "user_email", "emoji", name="unique_reaction"),
    )


# ---------------------------------------------------------------------------
# Authentication Helpers
# ---------------------------------------------------------------------------


def _build_msal_app():
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
    )


def get_current_user():
    if not AUTH_ENABLED:
        return {"name": "Dev User", "email": "dev.user@localhost"}
    return session.get("user")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def get_user_stats(user_email):
    """Calculate fun stats for a user: streak, total votes, etc."""
    # Get all weeks this user has voted on, sorted
    voted_weeks = (
        db.session.query(Question.week_start)
        .join(Response, Response.question_id == Question.id)
        .filter(Response.user_email == user_email)
        .order_by(Question.week_start.desc())
        .all()
    )
    voted_weeks = [w[0] for w in voted_weeks]
    total_votes = len(voted_weeks)

    # Calculate current streak
    streak = 0
    current_monday = get_current_week_monday()
    check_monday = current_monday

    for _ in range(100):  # max 100 weeks back
        if check_monday in voted_weeks:
            streak += 1
            check_monday -= timedelta(weeks=1)
        else:
            break

    return {
        "total_votes": total_votes,
        "streak": streak,
        "streak_fire": "🔥" * min(streak, 5) if streak > 0 else "",
    }


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------


@app.route("/login")
def login():
    if not AUTH_ENABLED:
        session["user"] = {"name": "Dev User", "email": "dev.user@localhost"}
        return redirect(url_for("index"))

    msal_app = _build_msal_app()
    auth_url = msal_app.get_authorization_request_url(
        SCOPE,
        redirect_uri=request.url_root.rstrip("/") + REDIRECT_PATH,
    )
    return redirect(auth_url)


@app.route(REDIRECT_PATH)
def auth_callback():
    if not AUTH_ENABLED:
        return redirect(url_for("index"))

    code = request.args.get("code")
    if not code:
        flash("Authentication failed — no authorization code received.", "error")
        return redirect(url_for("index"))

    msal_app = _build_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=request.url_root.rstrip("/") + REDIRECT_PATH,
    )

    if "error" in result:
        flash(f"Authentication error: {result.get('error_description', 'Unknown')}", "error")
        return redirect(url_for("index"))

    claims = result.get("id_token_claims", {})
    session["user"] = {
        "name": claims.get("name", claims.get("preferred_username", "Unknown")),
        "email": claims.get("preferred_username", claims.get("email", "unknown@unknown")),
    }
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    if AUTH_ENABLED:
        return redirect(
            f"{AUTHORITY}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={request.url_root}"
        )
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Main Routes
# ---------------------------------------------------------------------------


@app.route("/")
@login_required
def index():
    """Show this week's question."""
    user = get_current_user()
    monday = get_current_week_monday()

    question = Question.query.filter_by(week_start=monday, is_active=True).first()

    if not question:
        return render_template(
            "index.html",
            question=None,
            user=user,
            message="No question scheduled for this week. Check back next Monday! 📅",
            stats=get_user_stats(user["email"]),
            emoji_options=EMOJI_OPTIONS,
        )

    existing_vote = Response.query.filter_by(
        question_id=question.id, user_email=user["email"]
    ).first()

    # Get user's reactions for this question
    user_reactions = [
        r.emoji for r in Reaction.query.filter_by(
            question_id=question.id, user_email=user["email"]
        ).all()
    ]

    # Calculate countdown to Friday 17:00
    now = datetime.now()
    friday_close = datetime.combine(question.week_end, datetime.min.time()) + timedelta(hours=17)
    time_remaining = friday_close - now
    if time_remaining.total_seconds() < 0:
        time_remaining = timedelta(0)

    poll_open = is_poll_open(question)

    return render_template(
        "index.html",
        question=question,
        user=user,
        existing_vote=existing_vote,
        message=None,
        stats=get_user_stats(user["email"]),
        emoji_options=EMOJI_OPTIONS,
        user_reactions=user_reactions,
        countdown_end=friday_close.isoformat(),
        time_remaining=time_remaining,
        poll_open=poll_open,
    )


@app.route("/vote", methods=["POST"])
@login_required
def vote():
    """Submit a vote."""
    user = get_current_user()
    question_id = request.form.get("question_id", type=int)
    selected_option = request.form.get("selected_option", "").upper()

    if not question_id or selected_option not in ("A", "B", "C", "D"):
        flash("Invalid vote submission.", "error")
        return redirect(url_for("index"))

    question = db.session.get(Question, question_id)
    if not question:
        flash("Question not found.", "error")
        return redirect(url_for("index"))

    # Check if poll is still open
    if not is_poll_open(question):
        flash("This poll has closed! ⏰ Check back next Monday for a new one.", "warning")
        return redirect(url_for("index"))

    existing = Response.query.filter_by(
        question_id=question_id, user_email=user["email"]
    ).first()

    if existing:
        flash("You've already voted on this question! 🔒", "warning")
        return redirect(url_for("index"))

    response = Response(
        question_id=question_id,
        user_email=user["email"],
        user_name=user["name"],
        selected_option=selected_option,
    )

    try:
        db.session.add(response)
        db.session.commit()
        flash("🗳️ Vote recorded! See the results below.", "success")
    except Exception:
        db.session.rollback()
        flash("You've already voted on this question! 🔒", "warning")

    return redirect(url_for("index"))


@app.route("/comment", methods=["POST"])
@login_required
def add_comment():
    """Add a comment to a poll (must have voted first)."""
    user = get_current_user()
    question_id = request.form.get("question_id", type=int)
    text = request.form.get("comment_text", "").strip()

    if not question_id or not text:
        flash("Comment cannot be empty.", "warning")
        return redirect(url_for("index"))

    if len(text) > 500:
        text = text[:500]

    # Check if poll is still open
    question = db.session.get(Question, question_id)
    if question and not is_poll_open(question):
        flash("This poll has closed — comments are locked! ⏰", "warning")
        return redirect(url_for("index"))

    # Must have voted first
    existing_vote = Response.query.filter_by(
        question_id=question_id, user_email=user["email"]
    ).first()
    if not existing_vote:
        flash("You need to vote before commenting! 🗳️", "warning")
        return redirect(url_for("index"))

    comment = Comment(
        question_id=question_id,
        user_email=user["email"],
        user_name=user["name"],
        text=text,
    )
    db.session.add(comment)
    db.session.commit()
    flash("💬 Comment added!", "success")
    return redirect(url_for("index"))


@app.route("/react", methods=["POST"])
@login_required
def toggle_reaction():
    """Toggle an emoji reaction on a poll."""
    user = get_current_user()
    question_id = request.form.get("question_id", type=int)
    emoji = request.form.get("emoji", "")

    if not question_id or emoji not in EMOJI_OPTIONS:
        flash("Invalid reaction.", "warning")
        return redirect(url_for("index"))

    # Toggle: remove if exists, add if not
    existing = Reaction.query.filter_by(
        question_id=question_id, user_email=user["email"], emoji=emoji
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
    else:
        reaction = Reaction(
            question_id=question_id,
            user_email=user["email"],
            emoji=emoji,
        )
        try:
            db.session.add(reaction)
            db.session.commit()
        except Exception:
            db.session.rollback()

    return redirect(url_for("index"))


@app.route("/participation")
@login_required
def participation():
    """Show participation stats."""
    user = get_current_user()

    results = (
        db.session.query(
            Response.user_name,
            Response.user_email,
            db.func.count(Response.id).label("total_votes"),
        )
        .group_by(Response.user_email, Response.user_name)
        .order_by(db.desc("total_votes"))
        .all()
    )

    participation_data = []
    for i, row in enumerate(results, 1):
        total = row.total_votes or 0
        user_stats = get_user_stats(row.user_email)
        participation_data.append(
            {
                "rank": i,
                "name": row.user_name or row.user_email,
                "email": row.user_email,
                "total_votes": total,
                "streak": user_stats["streak"],
                "streak_fire": user_stats["streak_fire"],
                "trophy": "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "")),
            }
        )

    return render_template("participation.html", user=user, participation=participation_data)


@app.route("/history")
@login_required
def history():
    """Show past questions and results."""
    user = get_current_user()
    monday = get_current_week_monday()

    questions = (
        Question.query.filter(Question.week_start <= monday, Question.is_active == True)
        .order_by(Question.week_start.desc())
        .limit(30)
        .all()
    )

    return render_template("history.html", user=user, questions=questions)


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------


@app.route("/admin")
@login_required
def admin():
    """Admin page to manage questions."""
    user = get_current_user()
    questions = Question.query.order_by(Question.week_start.desc()).all()

    # Find next available Monday (first Monday without a scheduled question)
    existing_mondays = {q.week_start for q in questions}
    next_monday = get_current_week_monday() + timedelta(weeks=1)
    for _ in range(200):
        if next_monday not in existing_mondays:
            break
        next_monday += timedelta(weeks=1)

    return render_template(
        "admin.html",
        user=user,
        questions=questions,
        next_monday=next_monday.isoformat(),
    )


@app.route("/admin/add", methods=["POST"])
@login_required
def admin_add_question():
    """Add a new question from the admin form."""
    title = request.form.get("title", "").strip()
    option_a = request.form.get("option_a", "").strip()
    option_b = request.form.get("option_b", "").strip()
    option_c = request.form.get("option_c", "").strip() or None
    option_d = request.form.get("option_d", "").strip() or None
    category = request.form.get("category", "").strip() or None
    week_start_str = request.form.get("week_start", "").strip()

    # Validation
    if not title or not option_a or not option_b:
        flash("Question, Option A, and Option B are required.", "error")
        return redirect(url_for("admin"))

    if not week_start_str:
        flash("Week start date is required.", "error")
        return redirect(url_for("admin"))

    try:
        week_start = date.fromisoformat(week_start_str)
    except ValueError:
        flash("Invalid date format. Use YYYY-MM-DD.", "error")
        return redirect(url_for("admin"))

    # Ensure it's a Monday
    if week_start.weekday() != 0:
        # Snap to the Monday of that week
        week_start = week_start - timedelta(days=week_start.weekday())
        flash(f"Date adjusted to Monday: {week_start.isoformat()}", "info")

    # Check for duplicate week
    existing = Question.query.filter_by(week_start=week_start).first()
    if existing:
        flash(f"A question is already scheduled for the week of {week_start.isoformat()}.", "error")
        return redirect(url_for("admin"))

    question = Question(
        title=title,
        option_a=option_a,
        option_b=option_b,
        option_c=option_c,
        option_d=option_d,
        category=category,
        week_start=week_start,
        is_active=True,
    )
    db.session.add(question)
    db.session.commit()
    flash(f"✅ Question added for week of {week_start.strftime('%d %b %Y')}!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/edit/<int:question_id>", methods=["GET", "POST"])
@login_required
def admin_edit_question(question_id):
    """Edit an existing question."""
    question = db.session.get(Question, question_id)
    if not question:
        flash("Question not found.", "error")
        return redirect(url_for("admin"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        option_a = request.form.get("option_a", "").strip()
        option_b = request.form.get("option_b", "").strip()
        option_c = request.form.get("option_c", "").strip() or None
        option_d = request.form.get("option_d", "").strip() or None
        category = request.form.get("category", "").strip() or None
        week_start_str = request.form.get("week_start", "").strip()

        if not title or not option_a or not option_b:
            flash("Question, Option A, and Option B are required.", "error")
            return redirect(url_for("admin"))

        if week_start_str:
            try:
                new_week_start = date.fromisoformat(week_start_str)
                # Ensure it's a Monday
                if new_week_start.weekday() != 0:
                    new_week_start = new_week_start - timedelta(days=new_week_start.weekday())
                # Check for duplicate week (excluding this question)
                existing = Question.query.filter(
                    Question.week_start == new_week_start,
                    Question.id != question_id
                ).first()
                if existing:
                    flash(f"Another question is already scheduled for the week of {new_week_start.isoformat()}.", "error")
                    return redirect(url_for("admin"))
                question.week_start = new_week_start
            except ValueError:
                flash("Invalid date format.", "error")
                return redirect(url_for("admin"))

        question.title = title
        question.option_a = option_a
        question.option_b = option_b
        question.option_c = option_c
        question.option_d = option_d
        question.category = category
        db.session.commit()
        flash(f"✏️ Question updated successfully!", "success")
        return redirect(url_for("admin"))

    # GET — return question data as JSON for the modal
    return jsonify({
        "id": question.id,
        "title": question.title,
        "option_a": question.option_a,
        "option_b": question.option_b,
        "option_c": question.option_c or "",
        "option_d": question.option_d or "",
        "category": question.category or "",
        "week_start": question.week_start.isoformat(),
    })


@app.route("/admin/delete/<int:question_id>", methods=["POST"])
@login_required
def admin_delete_question(question_id):
    """Delete a question (only if it has no votes)."""
    question = db.session.get(Question, question_id)
    if not question:
        flash("Question not found.", "error")
        return redirect(url_for("admin"))

    if question.total_votes > 0:
        flash(f"Cannot delete — this question has {question.total_votes} vote(s). Deactivate instead.", "warning")
        return redirect(url_for("admin"))

    db.session.delete(question)
    db.session.commit()
    flash("🗑️ Question deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/toggle/<int:question_id>", methods=["POST"])
@login_required
def admin_toggle_question(question_id):
    """Toggle a question's active status."""
    question = db.session.get(Question, question_id)
    if not question:
        flash("Question not found.", "error")
        return redirect(url_for("admin"))

    question.is_active = not question.is_active
    db.session.commit()
    status = "activated" if question.is_active else "deactivated"
    flash(f"Question {status}.", "success")
    return redirect(url_for("admin"))


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.route("/api/current")
def api_current():
    monday = get_current_week_monday()
    question = Question.query.filter_by(week_start=monday, is_active=True).first()
    if not question:
        return jsonify({"error": "No question this week"}), 404
    return jsonify(question.to_dict())


@app.route("/api/vote", methods=["POST"])
@login_required
def api_vote():
    user = get_current_user()
    data = request.get_json()
    question_id = data.get("question_id")
    selected_option = data.get("selected_option", "").upper()

    if not question_id or selected_option not in ("A", "B", "C", "D"):
        return jsonify({"error": "Invalid vote"}), 400

    question = db.session.get(Question, question_id)
    if not question:
        return jsonify({"error": "Question not found"}), 404

    existing = Response.query.filter_by(
        question_id=question_id, user_email=user["email"]
    ).first()
    if existing:
        return jsonify({"error": "Already voted", "already_voted": True}), 409

    response = Response(
        question_id=question_id,
        user_email=user["email"],
        user_name=user["name"],
        selected_option=selected_option,
    )
    try:
        db.session.add(response)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Already voted"}), 409

    return jsonify({"results": question.to_dict()})


# ---------------------------------------------------------------------------
# Initialise & Run
# ---------------------------------------------------------------------------


def init_db():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"\n🗳️  Question of the Week — Web App")
    print(f"   Running on http://localhost:{port}")
    if not AUTH_ENABLED:
        print(f"   ⚠️  Auth disabled (set AZURE_CLIENT_ID to enable)")
    print()
    app.run(host="0.0.0.0", port=port, debug=debug)
