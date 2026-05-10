"""
Migration: add daily_steps_goal and daily_calorie_budget columns to account table.

Run once against any existing database that predates these columns:
    python -m src.scripts.apply_daily_goals_migration
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def apply_migration(database_url: str) -> None:
    engine = create_engine(database_url, echo=True)
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE account ADD COLUMN IF NOT EXISTS daily_steps_goal INTEGER DEFAULT 10000;"
        ))
        conn.execute(text(
            "ALTER TABLE account ADD COLUMN IF NOT EXISTS daily_calorie_budget INTEGER DEFAULT 2000;"
        ))
    print("Migration applied: daily_steps_goal and daily_calorie_budget added to account.")


def main() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set.")
    apply_migration(database_url)


if __name__ == "__main__":
    main()
