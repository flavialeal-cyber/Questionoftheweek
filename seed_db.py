"""
Seed the SQLite database with poll questions from sample_questions.csv.

Each question is assigned to a week (Monday start date).
One question per week — polls run Monday to Friday.

Usage:
    cd question_of_the_day/webapp
    python seed_db.py                                 # Auto-schedule from next Monday
    python seed_db.py --start-date 2026-09-14         # Start from specific Monday
    python seed_db.py --csv ../sample_questions.csv    # Custom CSV path
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta

# Add parent to path so we can import from the webapp
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, Question


def next_monday(start_date, offset=0):
    """Return the Monday on or after start_date + offset weeks."""
    # Ensure we start on a Monday
    current = start_date
    while current.weekday() != 0:  # 0 = Monday
        current += timedelta(days=1)
    # Add offset weeks
    current += timedelta(weeks=offset)
    return current


def seed(csv_path, start_date):
    """Load questions from CSV into the database."""
    if not os.path.exists(csv_path):
        print(f"❌ CSV not found: {csv_path}")
        sys.exit(1)

    with app.app_context():
        db.create_all()

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            offset = 0
            added = 0
            skipped = 0

            for row in reader:
                scheduled = row.get("WeekStart", "").strip()
                if scheduled:
                    try:
                        week_date = datetime.strptime(scheduled, "%Y-%m-%d").date()
                    except ValueError:
                        week_date = next_monday(start_date, offset).date()
                        offset += 1
                else:
                    week_date = next_monday(start_date, offset).date()
                    offset += 1

                # Skip if this week already has a question
                existing = Question.query.filter_by(week_start=week_date).first()
                if existing:
                    print(f"  ⏭️  Skipped (week {week_date} taken): {row['Title'][:50]}")
                    skipped += 1
                    continue

                q = Question(
                    title=row["Title"].strip(),
                    option_a=row["OptionA"].strip(),
                    option_b=row["OptionB"].strip(),
                    option_c=row.get("OptionC", "").strip() or None,
                    option_d=row.get("OptionD", "").strip() or None,
                    category=row.get("Category", "").strip() or None,
                    week_start=week_date,
                    is_active=True,
                )
                db.session.add(q)
                added += 1
                week_end = week_date + timedelta(days=4)
                print(f"  ✅ [{added}] {row['Title'][:55]}... → {week_date} to {week_end}")

            db.session.commit()
            print(f"\n✅ Done: {added} polls added, {skipped} skipped.")
            print(f"   That covers {added} weeks of polls!")
            print(f"   Database: {app.config['SQLALCHEMY_DATABASE_URI']}")


def main():
    parser = argparse.ArgumentParser(description="Seed the Question of the Week database from CSV")
    parser.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "sample_questions.csv"),
        help="Path to CSV file (default: ../sample_questions.csv)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Start date (Monday) for scheduling (YYYY-MM-DD, default: next Monday)",
    )
    args = parser.parse_args()

    if args.start_date:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
    else:
        today = datetime.now()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        start = today + timedelta(days=days_until_monday)

    print("🗳️  Question of the Week — Database Seeder")
    print("=" * 44)
    print(f"   CSV: {args.csv}")
    print(f"   Start week: {start.strftime('%Y-%m-%d')} (Monday)\n")

    seed(args.csv, start)


if __name__ == "__main__":
    main()
