"""Add `is_suspended` column to `account` table if it doesn't exist.

This is a minimal idempotent migration script that will ALTER the table
in-place for Postgres-compatible databases. It reads `DATABASE_URL` from
environment (or `TESTING_DATABASE_URL` for test runs) and executes the
ALTER TABLE statement safely using `IF NOT EXISTS`.
"""

import os
from dotenv import load_dotenv
from sqlmodel import create_engine


def main() -> None:
    load_dotenv()

    # Prefer explicit TESTING_DATABASE_URL when running tests locally via env
    from src import config

    database_url = os.getenv("DATABASE_URL") or config.DATABASE_URL
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    engine = create_engine(database_url, echo=True)

    alter_sql = (
        "ALTER TABLE account "
        "ADD COLUMN IF NOT EXISTS is_suspended boolean NOT NULL DEFAULT false;"
    )

    with engine.connect() as conn:
        # SQLAlchemy 2.x requires using exec_driver_sql or text() for plain SQL strings
        conn.exec_driver_sql(alter_sql)
        conn.commit()

    print("Migration complete: ensured `is_suspended` column exists on account.")


if __name__ == "__main__":
    main()
