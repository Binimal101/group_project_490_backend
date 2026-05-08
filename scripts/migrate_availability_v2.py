from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

import psycopg2
from psycopg2.extras import execute_values

WEEKDAY_OFFSETS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class LegacyAvailabilityRow:
    id: int
    weekday: str | None
    start_time: time | None
    end_time: time | None
    max_time_commitment_seconds: Any
    client_availability_id: int | None
    coach_availability_id: int | None
    client_id: int | None
    coach_id: int | None
    account_id: int | None


def _normalize_weekday(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


def _next_monday(today: date | None = None) -> date:
    today = today or datetime.now(timezone.utc).date()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    return today + timedelta(days=days_until_monday)


def _combine(anchor_date: date, slot_time: time | None) -> datetime:
    if slot_time is None:
        raise ValueError("slot_time is required")
    tzinfo = slot_time.tzinfo or timezone.utc
    return datetime.combine(anchor_date, slot_time.replace(tzinfo=tzinfo))


def _legacy_to_canonical(row: LegacyAvailabilityRow, anchor_monday: date) -> tuple[datetime, datetime]:
    weekday = _normalize_weekday(row.weekday)
    if weekday not in WEEKDAY_OFFSETS:
        raise ValueError(f"Unsupported weekday value: {row.weekday!r}")

    anchor_date = anchor_monday + timedelta(days=WEEKDAY_OFFSETS[weekday])
    start_dt = _combine(anchor_date, row.start_time)
    end_dt = _combine(anchor_date, row.end_time)
    if end_dt <= start_dt:
        raise ValueError(f"Invalid time range for availability {row.id}: {start_dt.isoformat()} -> {end_dt.isoformat()}")
    return start_dt, end_dt


def _ensure_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


def _create_tables(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS busy_slot (
            id SERIAL PRIMARY KEY,
            account_id INTEGER REFERENCES account(id) ON DELETE CASCADE,
            start_dt TIMESTAMPTZ,
            end_dt TIMESTAMPTZ,
            source TEXT NOT NULL DEFAULT 'manual',
            source_id INTEGER,
            note TEXT,
            last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_busy_slot_account_id ON busy_slot(account_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_busy_slot_start_dt ON busy_slot(start_dt)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_busy_slot_source ON busy_slot(source, source_id)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS availability_v2 (
            id SERIAL PRIMARY KEY,
            account_id INTEGER REFERENCES account(id) ON DELETE CASCADE,
            start_dt TIMESTAMPTZ,
            end_dt TIMESTAMPTZ,
            repeats_weekly BOOLEAN NOT NULL DEFAULT FALSE,
            recurrence_end_dt TIMESTAMPTZ,
            weekday TEXT,
            start_time TIME WITH TIME ZONE,
            end_time TIME WITH TIME ZONE,
            max_time_commitment_seconds NUMERIC(8, 2),
            client_availability_id INTEGER REFERENCES client_availability(id),
            coach_availability_id INTEGER REFERENCES coach_availability(id),
            last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_availability_v2_account_id ON availability_v2(account_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_availability_v2_start_dt ON availability_v2(start_dt)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_availability_v2_client_container ON availability_v2(client_availability_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_availability_v2_coach_container ON availability_v2(coach_availability_id)")


def _fetch_rows(cursor) -> list[LegacyAvailabilityRow]:
    cursor.execute(
        """
        SELECT
            a.id,
            a.weekday,
            a.start_time,
            a.end_time,
            a.max_time_commitment_seconds,
            a.client_availability_id,
            a.coach_availability_id,
            c.id AS client_id,
            ch.id AS coach_id,
            acc_client.id AS client_account_id,
            acc_coach.id AS coach_account_id
        FROM availability a
        LEFT JOIN client_availability ca ON ca.id = a.client_availability_id
        LEFT JOIN client c ON c.client_availability_id = ca.id
        LEFT JOIN account acc_client ON acc_client.client_id = c.id
        LEFT JOIN coach_availability coa ON coa.id = a.coach_availability_id
        LEFT JOIN coach ch ON ch.coach_availability = coa.id
        LEFT JOIN account acc_coach ON acc_coach.coach_id = ch.id
        ORDER BY a.id
        """
    )
    rows: list[LegacyAvailabilityRow] = []
    for record in cursor.fetchall():
        rows.append(
            LegacyAvailabilityRow(
                id=record[0],
                weekday=record[1],
                start_time=record[2],
                end_time=record[3],
                max_time_commitment_seconds=record[4],
                client_availability_id=record[5],
                coach_availability_id=record[6],
                client_id=record[7],
                coach_id=record[8],
                account_id=record[9] or record[10],
            )
        )
    return rows


def _classify_row(row: LegacyAvailabilityRow) -> str:
    if row.account_id is None:
        return "orphan"
    if row.client_availability_id is not None:
        return "client"
    if row.coach_availability_id is not None:
        return "coach"
    return "orphan"


def _build_insert_rows(rows: Iterable[LegacyAvailabilityRow], anchor_monday: date) -> tuple[list[tuple[Any, ...]], Counter[str]]:
    insert_rows: list[tuple[Any, ...]] = []
    counts: Counter[str] = Counter()

    for row in rows:
        bucket = _classify_row(row)
        counts[bucket] += 1
        if bucket == "orphan":
            continue

        if row.start_time is None or row.end_time is None or row.weekday is None:
            counts["malformed"] += 1
            continue

        try:
            start_dt, end_dt = _legacy_to_canonical(row, anchor_monday)
        except ValueError:
            counts["malformed"] += 1
            continue

        insert_rows.append(
            (
                row.account_id,
                start_dt,
                end_dt,
                True,
                None,
                row.weekday,
                row.start_time,
                row.end_time,
                row.max_time_commitment_seconds,
                row.client_availability_id,
                row.coach_availability_id,
            )
        )

    return insert_rows, counts


def _replace_table(cursor) -> None:
    cursor.execute("ALTER TABLE availability RENAME TO availability_legacy_v1")
    cursor.execute("ALTER TABLE availability_v2 RENAME TO availability")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_availability_account_start_dt ON availability(account_id, start_dt)")


def run(dry_run: bool) -> int:
    database_url = _ensure_database_url()
    anchor_monday = _next_monday()

    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            legacy_rows = _fetch_rows(cursor)
            insert_rows, counts = _build_insert_rows(legacy_rows, anchor_monday)

            print(f"Legacy rows: {len(legacy_rows)}")
            print(f"Migrated rows: {len(insert_rows)}")
            print(f"Skipped client-linked rows: {counts['client']}")
            print(f"Skipped coach-linked rows: {counts['coach']}")
            print(f"Skipped orphan rows: {counts['orphan']}")
            print(f"Malformed rows: {counts['malformed']}")
            print(f"Reference Monday: {anchor_monday.isoformat()}")

            if dry_run:
                connection.rollback()
                return 0

            _create_tables(cursor)
            execute_values(
                cursor,
                """
                INSERT INTO availability_v2 (
                    account_id,
                    start_dt,
                    end_dt,
                    repeats_weekly,
                    recurrence_end_dt,
                    weekday,
                    start_time,
                    end_time,
                    max_time_commitment_seconds,
                    client_availability_id,
                    coach_availability_id
                ) VALUES %s
                """,
                insert_rows,
                page_size=500,
            )
            _replace_table(cursor)

        connection.commit()

    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy availability rows to the date-based model.")
    parser.add_argument("--apply", action="store_true", help="Execute the migration instead of running a dry run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return run(dry_run=not args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
