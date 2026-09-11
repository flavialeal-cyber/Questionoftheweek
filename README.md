# 🗳️ Question of the Week

A fun, interactive weekly poll for your team — built with Flask and Microsoft 365 authentication.

Every week, one opinion question goes live (Monday–Friday). Colleagues vote using their Microsoft account, see live results, react with emojis, and leave comments defending their picks.

![Poll Results](https://img.shields.io/badge/Status-Active-brightgreen) ![Python](https://img.shields.io/badge/Python-3.9+-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🗳️ **Weekly Polls** | One opinion question per week, live Monday to Friday |
| 🔒 **One Vote Per Person** | Microsoft Entra ID (Azure AD) authentication prevents duplicates |
| 📊 **Live Results** | Vote counts, percentages, and animated progress bars |
| 🔥 **Emoji Reactions** | React to polls with 👏 😂 🤯 🔥 💡 — toggle on/off |
| 💬 **Comments** | Defend your pick after voting (500 char max) |
| ⏳ **Countdown Timer** | Live countdown showing when the poll closes (Friday 5pm) |
| 📈 **Voting Streaks** | Track consecutive weeks of participation with 🔥 streak badges |
| 🏆 **Participation Board** | See who's most active, with streak tracking |
| 📚 **Poll History** | Browse past polls and their results |
| 🔒 **Poll Closing** | Polls auto-lock after Friday 5pm — no more votes, comments, or reactions |
|  **CSV Scheduling** | Load 40+ weeks of questions from a simple CSV file |
| ⚙️ **Admin Panel** | Add, schedule, deactivate, or delete questions from `/admin` in the browser |
| 🔗 **One Permanent Link** | Single URL — no new forms to create each week |
| 🧑‍💻 **Dev Mode** | Works without Azure AD for local testing |

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Seed questions from CSV

```bash
# Auto-schedule from next Monday
python seed_db.py

# Or specify a start date
python seed_db.py --start-date 2026-09-07

# Use a custom CSV
python seed_db.py --csv /path/to/questions.csv
```

### 3. Run the app

```bash
python app.py
# → http://localhost:8000
```

In dev mode (no Azure AD configured), you'll be auto-logged in as "Dev User".

---

## 🔐 Microsoft 365 Authentication

Set these environment variables to enable Azure AD / Entra ID login:

```bash
AZURE_CLIENT_ID=your-app-registration-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_TENANT_ID=your-tenant-id
```

### Azure App Registration Setup

1. Go to [Azure Portal](https://portal.azure.com) → **App registrations** → **New registration**
2. Name: `Question of the Week`
3. Redirect URI: `https://your-app-url/auth/callback` (Web)
4. Create a **Client secret** under Certificates & secrets
5. Under **API permissions**, ensure `User.Read` is granted
6. Set the three environment variables above

---

## 📋 CSV Format

Create questions in `sample_questions.csv`:

```csv
Title,OptionA,OptionB,OptionC,OptionD,Category
Tea or coffee?,Tea,Coffee,,,Food & Drink
Best meeting length?,15 minutes,30 minutes,45 minutes,1 hour,Work Life
```

- **Title**: The poll question (required)
- **OptionA/B**: Always required (at least 2 options)
- **OptionC/D**: Optional (leave blank for 2-option polls)
- **Category**: Optional tag displayed on the poll
- **WeekStart**: Optional `YYYY-MM-DD` to pin to a specific week

---

## 🏗️ Architecture

```
question-of-the-week/
├── app.py                    # Flask app (models, routes, auth)
├── seed_db.py                # CSV → SQLite seeder
├── sample_questions.csv      # 40 ready-to-use poll questions
├── requirements.txt          # Python dependencies
├── .gitignore
├── README.md
├── static/
│   └── style.css             # Custom styles
└── templates/
    ├── base.html             # Layout with navbar
    ├── index.html            # Poll + results + reactions + comments
    ├── admin.html            # Question management panel
    ├── participation.html    # Participation board with streaks
    └── history.html          # Past polls accordion
```

### Database Tables

| Table | Purpose |
|-------|---------|
| `questions` | Poll questions with options, category, and week schedule |
| `responses` | One vote per user per question (unique constraint) |
| `comments` | User comments on polls (must vote first) |
| `reactions` | Emoji reactions (toggle on/off, unique per user+emoji) |

---

## 🌐 Deployment Options

### Azure App Service (Recommended)

```bash
# Build & deploy
az webapp up --name qotw-app --resource-group your-rg --runtime PYTHON:3.11
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
```

### Windows (IIS / waitress)

```bash
pip install waitress
waitress-serve --port=8000 app:app
```

---

## 📢 Teams Integration

Share the permanent link in a Teams channel, or pin it as a tab:

1. In your Teams channel, click **+** (Add a tab)
2. Select **Website**
3. Paste your app URL: `https://your-app-url`
4. Name it "Question of the Week"

The same link works every week — no new forms needed!

---

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_CLIENT_ID` | *(empty)* | Azure AD app client ID (enables auth) |
| `AZURE_CLIENT_SECRET` | *(empty)* | Azure AD app client secret |
| `AZURE_TENANT_ID` | `common` | Azure AD tenant ID |
| `SECRET_KEY` | *(auto-generated)* | Flask session secret key |
| `DATABASE_URL` | `sqlite:///qotw.db` | Database connection string |
| `PORT` | `8000` | Port to serve on |
| `FLASK_DEBUG` | `1` | Set to `0` for production |

---

## 📝 Adding More Questions

### Option 1: Admin Panel (Recommended) ⚙️

Navigate to `/admin` in the app to:

- **Add questions** — fill in the question, 2-4 options, category, and pick a week
- **View all scheduled questions** — see the full schedule in a sortable table
- **Delete questions** — remove questions that haven't received any votes yet
- **Deactivate/reactivate** — toggle questions on/off without deleting them

The admin page auto-suggests the next available Monday and validates all input.

### Option 2: CSV Bulk Load

For loading many questions at once, use the CSV seeder:

```bash
python seed_db.py --csv new_questions.csv --start-date 2027-06-14
```

It won't duplicate existing weeks.

---

*Built with Flask, Bootstrap 5, and Microsoft 365 · No premium connectors required*
