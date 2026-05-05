"""CLI seeder for meal data, portion sizes, and ingredients."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine


def choose_env() -> str:
    print("Choose target environment:")
    print("1) Testing (uses TESTING_DATABASE_URL and TESTING_SUPABASE_*)")
    print("2) Production (uses DATABASE_URL)")
    choice = input("Enter 1 or 2: ").strip()
    while choice not in ("1", "2"):
        choice = input("Please enter 1 or 2: ").strip()
    return choice


def resolve_account_id(conn: Any, account_data: dict | None, default_account_id: int) -> int:
    if not account_data:
        return default_account_id

    if account_data.get("created_by_account_id") is not None:
        return int(account_data["created_by_account_id"])

    email = account_data.get("created_by_account_email")
    if email:
        row = conn.execute(text("SELECT id FROM account WHERE email = :email"), {"email": email}).first()
        if not row:
            raise RuntimeError(f"Account with email {email!r} not found")
        return row[0]

    return default_account_id


def get_or_create_unit(conn: Any, unit_name: str, is_imperial: bool) -> tuple[int, bool]:
    unit_name = unit_name.strip()
    row = conn.execute(
        text(
            "SELECT id FROM unit WHERE unit_name = :unit_name AND is_imperial = :is_imperial"
        ),
        {"unit_name": unit_name, "is_imperial": is_imperial},
    ).first()
    if row:
        return row[0], False

    res = conn.execute(
        text(
            "INSERT INTO unit (unit_name, is_imperial) VALUES (:unit_name, :is_imperial) RETURNING id"
        ),
        {"unit_name": unit_name, "is_imperial": is_imperial},
    )
    return res.scalar(), True


def get_or_create_portion_size(conn: Any, unit_id: int, count: int) -> tuple[int, bool]:
    row = conn.execute(
        text(
            "SELECT id FROM portion_size WHERE unit_id = :unit_id AND count = :count"
        ),
        {"unit_id": unit_id, "count": count},
    ).first()
    if row:
        return row[0], False

    res = conn.execute(
        text(
            "INSERT INTO portion_size (unit_id, count) VALUES (:unit_id, :count) RETURNING id"
        ),
        {"unit_id": unit_id, "count": count},
    )
    return res.scalar(), True


def get_or_create_meal(conn: Any, meal_name: str, created_by_account_id: int) -> tuple[int, bool]:
    row = conn.execute(
        text("SELECT id FROM meal WHERE meal_name = :meal_name"),
        {"meal_name": meal_name},
    ).first()
    if row:
        return row[0], False

    res = conn.execute(
        text(
            "INSERT INTO meal (created_by_account_id, meal_name) VALUES (:created_by_account_id, :meal_name) RETURNING id"
        ),
        {"created_by_account_id": created_by_account_id, "meal_name": meal_name},
    )
    return res.scalar(), True


def meal_ingredient_exists(conn: Any, meal_id: int, ingredient_name: str, portion_size_id: int, calories: int) -> bool:
    row = conn.execute(
        text(
            "SELECT id FROM meal_ingredient WHERE meal_id = :meal_id AND ingredient_name = :ingredient_name "
            "AND portion_size_id = :portion_size_id AND calories = :calories"
        ),
        {
            "meal_id": meal_id,
            "ingredient_name": ingredient_name,
            "portion_size_id": portion_size_id,
            "calories": calories,
        },
    ).first()
    return bool(row)


def main() -> None:
    choice = choose_env()
    if choice == "1":
        os.environ["IS_TESTING"] = "true"
    else:
        os.environ.pop("IS_TESTING", None)

    from src import config

    engine = create_engine(config.DATABASE_URL, echo=False)
    data_path = Path(__file__).parent / "meals.json"
    if not data_path.exists():
        print(f"meals.json not found at {data_path}")
        return

    with open(data_path, "r", encoding="utf-8") as fh:
        meals = json.load(fh)

    inserted_meals = 0
    inserted_units = 0
    inserted_portions = 0
    inserted_ingredients = 0

    with engine.connect() as conn:
        default_account_row = conn.execute(text("SELECT id FROM account ORDER BY id LIMIT 1")).first()
        if not default_account_row:
            raise RuntimeError("No account records found. Create an account before seeding meals.")
        default_account_id = default_account_row[0]

    with engine.begin() as conn:
        for meal in meals:
            creator_id = resolve_account_id(conn, meal, default_account_id)
            meal_id, meal_created = get_or_create_meal(conn, meal["meal_name"], creator_id)
            if meal_created:
                inserted_meals += 1

            for ingredient in meal.get("ingredients", []):
                ingredient_name = ingredient["ingredient_name"].strip()
                portion = ingredient["portion_size"]
                unit_id, unit_created = get_or_create_unit(conn, portion["unit_name"], bool(portion["is_imperial"]))
                if unit_created:
                    inserted_units += 1

                portion_size_id, portion_created = get_or_create_portion_size(conn, unit_id, int(portion["count"]))
                if portion_created:
                    inserted_portions += 1

                if ingredient_name and portion_size_id and int(ingredient["calories"]) >= 0:
                    if not meal_ingredient_exists(conn, meal_id, ingredient_name, portion_size_id, int(ingredient["calories"])):
                        conn.execute(
                            text(
                                "INSERT INTO meal_ingredient (meal_id, ingredient_name, portion_size_id, calories) "
                                "VALUES (:meal_id, :ingredient_name, :portion_size_id, :calories)"
                            ),
                            {
                                "meal_id": meal_id,
                                "ingredient_name": ingredient_name,
                                "portion_size_id": portion_size_id,
                                "calories": int(ingredient["calories"]),
                            },
                        )
                        inserted_ingredients += 1

    print(
        f"Seed complete: {inserted_meals} meals, {inserted_ingredients} ingredients, "
        f"{inserted_units} units, {inserted_portions} portion sizes"
    )


if __name__ == "__main__":
    main()
