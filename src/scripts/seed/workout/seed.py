"""CLI seeder that reads JSON workouts and prompts for testing or production.

This seeder inserts rows directly via SQL so it does not import the
`src.database` package (avoids importing all models). It creates
`workout`, `equiptment`, `workout_equiptment`, and `workout_activity`
rows from `workouts.json`.
"""
from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from sqlmodel import create_engine
from sqlalchemy import text


def choose_env() -> str:
    print("Choose target environment:")
    print("1) Testing (uses TESTING_DATABASE_URL and TESTING_SUPABASE_*)")
    print("2) Production (uses DATABASE_URL)")
    choice = input("Enter 1 or 2: ").strip()
    while choice not in ("1", "2"):
        choice = input("Please enter 1 or 2: ").strip()
    return choice


def main():
    choice = choose_env()
    if choice == "1":
        os.environ["IS_TESTING"] = "true"
    else:
        os.environ.pop("IS_TESTING", None)

    # import config after IS_TESTING is set so src.__init__ picks TESTING_* values
    from src import config

    engine = create_engine(config.DATABASE_URL, echo=False)

    data_path = Path(__file__).parent / "workouts.json"
    if not data_path.exists():
        print(f"workouts.json not found at {data_path}")
        return

    with open(data_path, "r", encoding="utf-8") as fh:
        workouts = json.load(fh)

    inserted_workouts = 0
    inserted_activities = 0
    skipped_workouts = 0
    inserted_equiptment = 0
    inserted_mappings = 0

    # Detect how the DB represents workout_type (enum labels vs plain text)
    with engine.connect() as _conn:
        udt_row = _conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name='workout' AND column_name='workout_type'"
            )
        ).first()
        udt_name = udt_row[0] if udt_row else None

        db_wt_map = None
        if udt_name and udt_name != 'text':
            labels = _conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = :udt"
                ),
                {"udt": udt_name},
            ).fetchall()
            labels = [r[0] for r in labels]
            if 'REPETITION_BASED' in labels and 'DURATION_BASED' in labels:
                db_wt_map = {
                    "REPETITION_BASED": "REPETITION_BASED",
                    "DURATION_BASED": "DURATION_BASED",
                    "rep": "REPETITION_BASED",
                    "duration": "DURATION_BASED",
                }

        if db_wt_map is None:
            db_wt_map = {
                "REPETITION_BASED": "rep",
                "DURATION_BASED": "duration",
                "rep": "rep",
                "duration": "duration",
            }

    with engine.begin() as conn:
        for w in workouts:
            wt_str = w.get("workout_type", "REPETITION_BASED")
            db_wt = db_wt_map.get(wt_str, "rep")

            name = w.get("name")
            # check existing workout
            existing = conn.execute(text("SELECT id FROM workout WHERE name = :name"), {"name": name}).scalar()
            if existing:
                workout_id = existing
                skipped_workouts += 1
            else:
                res = conn.execute(
                    text(
                        "INSERT INTO workout (last_updated, name, description, instructions, workout_type) "
                        "VALUES (:last_updated, :name, :description, :instructions, :workout_type) RETURNING id"
                    ),
                    {
                        "last_updated": datetime.now(timezone.utc),
                        "name": name,
                        "description": w.get("description"),
                        "instructions": w.get("instructions"),
                        "workout_type": db_wt,
                    },
                )
                workout_id = res.scalar()
                inserted_workouts += 1

            # equipment
            for eq_name in w.get("equipment", []):
                eq_name = str(eq_name).strip()
                if not eq_name:
                    continue
                eq_existing = conn.execute(text("SELECT id FROM equiptment WHERE name = :name"), {"name": eq_name}).scalar()
                if eq_existing:
                    eq_id = eq_existing
                else:
                    res = conn.execute(
                        text(
                            "INSERT INTO equiptment (last_updated, name, description) VALUES (:last_updated, :name, :description) RETURNING id"
                        ),
                        {"last_updated": datetime.now(timezone.utc), "name": eq_name, "description": None},
                    )
                    eq_id = res.scalar()
                    inserted_equiptment += 1

                # link table (avoid duplicates)
                link_exists = conn.execute(
                    text(
                        "SELECT id FROM workout_equiptment WHERE workout_id = :wid AND equiptment_id = :eid"
                    ),
                    {"wid": workout_id, "eid": eq_id},
                ).scalar()

                if not link_exists:
                    conn.execute(
                        text(
                            "INSERT INTO workout_equiptment (last_updated, equiptment_id, workout_id, is_required, is_recommended) "
                            "VALUES (:last_updated, :eid, :wid, :req, :rec)"
                        ),
                        {"last_updated": datetime.now(timezone.utc), "eid": eq_id, "wid": workout_id, "req": True, "rec": True},
                    )
                    inserted_mappings += 1

            # activities
            for act in w.get("activities", []):
                est_val = act.get("estimated_calories_per_unit_frequency")
                if est_val is None:
                    continue
                intensity_measure = act.get("intensity_measure")
                intensity_value = act.get("intensity_value")
                est_decimal = Decimal(str(est_val))

                # avoid inserting duplicate activities for the same workout
                existing_activity = conn.execute(
                    text(
                        "SELECT id FROM workout_activity WHERE workout_id = :wid "
                        "AND ( (intensity_measure = :im) OR (intensity_measure IS NULL AND :im IS NULL) ) "
                        "AND ( (intensity_value = :iv) OR (intensity_value IS NULL AND :iv IS NULL) ) "
                        "AND estimated_calories_per_unit_frequency = :est"
                    ),
                    {"wid": workout_id, "im": intensity_measure, "iv": intensity_value, "est": est_decimal},
                ).scalar()

                if existing_activity:
                    continue

                conn.execute(
                    text(
                        "INSERT INTO workout_activity (last_updated, workout_id, intensity_measure, intensity_value, estimated_calories_per_unit_frequency) "
                        "VALUES (:last_updated, :wid, :im, :iv, :est)"
                    ),
                    {
                        "last_updated": datetime.now(timezone.utc),
                        "wid": workout_id,
                        "im": intensity_measure,
                        "iv": intensity_value,
                        "est": est_decimal,
                    },
                )
                inserted_activities += 1

    print(
        f"Seed complete: {inserted_workouts} new workouts, {inserted_activities} new activities, "
        f"{skipped_workouts} skipped workouts, {inserted_equiptment} new equiptment, {inserted_mappings} new mappings"
    )


if __name__ == "__main__":
    main()
