"""CLI seeder for coach accounts, coach requests, certifications, experiences, and approvals."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine

from src.api.auth.services import hash_password
from src.database.account.models import Weekday


def choose_env() -> str:
    print("Choose target environment:")
    print("1) Testing (uses TESTING_DATABASE_URL and TESTING_SUPABASE_*)")
    print("2) Production (uses DATABASE_URL)")
    choice = input("Enter 1 or 2: ").strip()
    while choice not in ("1", "2"):
        choice = input("Please enter 1 or 2: ").strip()
    return choice


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M:%S").time()


def get_or_create_admin(conn: Any) -> int:
    row = conn.execute(text("SELECT id FROM admin ORDER BY id LIMIT 1")).first()
    if row:
        return row[0]

    now = datetime.now(timezone.utc)
    return conn.execute(text("INSERT INTO admin (last_updated) VALUES (:last_updated) RETURNING id"), {"last_updated": now}).scalar()


def get_or_create_account(conn: Any, account_data: dict) -> tuple[int, bool]:
    row = conn.execute(text("SELECT id, client_id, coach_id FROM account WHERE email = :email"), {"email": account_data["email"]}).first()
    if row:
        account_id, client_id, coach_id = row
        if coach_id is not None:
            raise RuntimeError(f"Account {account_data['email']} already has coach_id={coach_id}")
        return account_id, False

    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO account (name, email, hashed_password, is_active, gender, bio, age, pfp_url, created_at, last_updated) "
            "VALUES (:name, :email, :hashed_password, :is_active, :gender, :bio, :age, :pfp_url, :created_at, :last_updated) RETURNING id"
        ),
        {
            "name": account_data["name"],
            "email": account_data["email"],
            "hashed_password": hash_password(account_data["password"]),
            "is_active": True,
            "gender": account_data.get("gender"),
            "bio": account_data.get("bio"),
            "age": account_data.get("age"),
            "pfp_url": account_data.get("pfp_url"),
            "created_at": now,
            "last_updated": now,
        },
    )
    return res.scalar(), True


def get_or_create_client(conn: Any) -> int:
    now = datetime.now(timezone.utc)
    return conn.execute(text("INSERT INTO client (last_updated) VALUES (:last_updated) RETURNING id"), {"last_updated": now}).scalar()


def get_or_create_coach(conn: Any, coach_availability_id: int, specialties: list[str] | None) -> int:
    row = conn.execute(text("SELECT id FROM coach WHERE coach_availability = :coach_availability AND specialties = :specialties"), {"coach_availability": coach_availability_id, "specialties": ", ".join(specialties) if specialties else None}).first()
    if row:
        return row[0]

    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO coach (verified, specialties, coach_availability, last_updated) "
            "VALUES (:verified, :specialties, :coach_availability, :last_updated) RETURNING id"
        ),
        {
            "verified": False,
            "specialties": ", ".join(specialties) if specialties else None,
            "coach_availability": coach_availability_id,
            "last_updated": now,
        },
    )
    return res.scalar()


def get_or_create_certification(conn: Any, cert_data: dict) -> int:
    row = conn.execute(
        text(
            "SELECT id FROM certifications WHERE certification_name = :name "
            "AND certification_date = :date AND certification_organization = :org "
            "AND certification_score IS NOT DISTINCT FROM :score"
        ),
        {
            "name": cert_data["certification_name"],
            "date": parse_date(cert_data["certification_date"]),
            "org": cert_data["certification_organization"],
            "score": cert_data.get("certification_score"),
        },
    ).first()
    if row:
        return row[0]

    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO certifications (certification_name, certification_date, certification_score, certification_organization, last_updated) "
            "VALUES (:name, :date, :score, :org, :last_updated) RETURNING id"
        ),
        {
            "name": cert_data["certification_name"],
            "date": parse_date(cert_data["certification_date"]),
            "score": cert_data.get("certification_score"),
            "org": cert_data["certification_organization"],
            "last_updated": now,
        },
    )
    return res.scalar()


def get_or_create_experience(conn: Any, exp_data: dict) -> int:
    exp_start = parse_date(exp_data["experience_start"])
    exp_end = parse_date(exp_data["experience_end"]) if exp_data.get("experience_end") else None

    row = conn.execute(
        text(
            "SELECT id FROM experience WHERE experience_name = :name "
            "AND experience_title = :title AND experience_description = :description "
            "AND experience_start = :start AND experience_end IS NOT DISTINCT FROM :end"
        ),
        {
            "name": exp_data["experience_name"],
            "title": exp_data["experience_title"],
            "description": exp_data["experience_description"],
            "start": exp_start,
            "end": exp_end,
        },
    ).first()
    if row:
        return row[0]

    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO experience (experience_name, experience_title, experience_description, experience_start, experience_end, last_updated) "
            "VALUES (:name, :title, :description, :start, :end, :last_updated) RETURNING id"
        ),
        {
            "name": exp_data["experience_name"],
            "title": exp_data["experience_title"],
            "description": exp_data["experience_description"],
            "start": exp_start,
            "end": exp_end,
            "last_updated": now,
        },
    )
    return res.scalar()


def get_or_create_pricing_plan(conn: Any, coach_id: int, payment_interval: str, price_cents: int) -> int:
    row = conn.execute(
        text(
            "SELECT id FROM pricing_plan WHERE coach_id = :coach_id "
            "AND payment_interval = :interval AND price_cents = :price"
        ),
        {"coach_id": coach_id, "interval": payment_interval, "price": price_cents},
    ).first()
    if row:
        return row[0]

    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO pricing_plan (coach_id, payment_interval, price_cents, last_updated) "
            "VALUES (:coach_id, :interval, :price, :last_updated) RETURNING id"
        ),
        {"coach_id": coach_id, "interval": payment_interval, "price": price_cents, "last_updated": now},
    )
    return res.scalar()


def insert_coach_availability(conn: Any) -> int:
    now = datetime.now(timezone.utc)
    return conn.execute(text("INSERT INTO coach_availability (last_updated) VALUES (:last_updated) RETURNING id"), {"last_updated": now}).scalar()


def create_availabilities(conn: Any, coach_availability_id: int, availabilities: list[dict]) -> int:
    inserted = 0
    for avail in availabilities:
        now = datetime.now(timezone.utc)
        weekday_value = Weekday(avail["weekday"]).name
        conn.execute(
            text(
                "INSERT INTO availability (weekday, start_time, end_time, max_time_commitment_seconds, coach_availability_id, last_updated) "
                "VALUES (:weekday, :start_time, :end_time, :max_commitment, :coach_availability_id, :last_updated)"
            ),
            {
                "weekday": weekday_value,
                "start_time": parse_time(avail["start_time"]),
                "end_time": parse_time(avail["end_time"]),
                "max_commitment": avail.get("max_time_commitment_seconds"),
                "coach_availability_id": coach_availability_id,
                "last_updated": now,
            },
        )
        inserted += 1
    return inserted


def create_coach_request(conn: Any, coach_id: int) -> int:
    existing = conn.execute(text("SELECT id FROM coach_request WHERE coach_id = :coach_id AND role_promotion_resolution_id IS NULL"), {"coach_id": coach_id}).first()
    if existing:
        return existing[0]
    now = datetime.now(timezone.utc)
    return conn.execute(text("INSERT INTO coach_request (coach_id, created_on, last_updated) VALUES (:coach_id, :created_on, :last_updated) RETURNING id"), {"coach_id": coach_id, "created_on": now, "last_updated": now}).scalar()


def create_resolution(conn: Any, coach_request_id: int, admin_id: int, account_id: int, approve: bool) -> int:
    now = datetime.now(timezone.utc)
    res = conn.execute(
        text(
            "INSERT INTO role_promotion_resolution (role, admin_id, account_id, is_approved, last_updated) "
            "VALUES (:role, :admin_id, :account_id, :approved, :last_updated) RETURNING id"
        ),
        {"role": "coach", "admin_id": admin_id, "account_id": account_id, "approved": approve, "last_updated": now},
    )
    resolution_id = res.scalar()
    conn.execute(
        text("UPDATE coach_request SET role_promotion_resolution_id = :resolution_id WHERE id = :request_id"),
        {"resolution_id": resolution_id, "request_id": coach_request_id},
    )
    return resolution_id


def link_coach_certification(conn: Any, coach_id: int, certification_id: int) -> None:
    exists = conn.execute(
        text(
            "SELECT id FROM coach_certifications WHERE coach_id = :coach_id AND certification_id = :cert_id"
        ),
        {"coach_id": coach_id, "cert_id": certification_id},
    ).first()
    if not exists:
        now = datetime.now(timezone.utc)
        conn.execute(
            text(
                "INSERT INTO coach_certifications (coach_id, certification_id, last_updated) VALUES (:coach_id, :cert_id, :last_updated)"
            ),
            {"coach_id": coach_id, "cert_id": certification_id, "last_updated": now},
        )


def link_coach_experience(conn: Any, coach_id: int, experience_id: int) -> None:
    exists = conn.execute(
        text(
            "SELECT id FROM coach_experience WHERE coach_id = :coach_id AND experience_id = :exp_id"
        ),
        {"coach_id": coach_id, "exp_id": experience_id},
    ).first()
    if not exists:
        now = datetime.now(timezone.utc)
        conn.execute(
            text(
                "INSERT INTO coach_experience (coach_id, experience_id, last_updated) VALUES (:coach_id, :exp_id, :last_updated)"
            ),
            {"coach_id": coach_id, "exp_id": experience_id, "last_updated": now},
        )


def mark_coach_verified(conn: Any, coach_id: int) -> None:
    conn.execute(text("UPDATE coach SET verified = TRUE WHERE id = :coach_id"), {"coach_id": coach_id})


def main() -> None:
    choice = choose_env()
    if choice == "1":
        os.environ["IS_TESTING"] = "true"
    else:
        os.environ.pop("IS_TESTING", None)

    from src import config

    engine = create_engine(config.DATABASE_URL, echo=False)
    data_path = Path(__file__).parent / "coaches.json"
    if not data_path.exists():
        print(f"coaches.json not found at {data_path}")
        return

    with open(data_path, "r", encoding="utf-8") as fh:
        coaches = json.load(fh)

    inserted_accounts = 0
    inserted_clients = 0
    inserted_coaches = 0
    inserted_availabilities = 0
    inserted_experiences = 0
    inserted_certifications = 0
    inserted_pricing_plans = 0
    inserted_requests = 0
    inserted_resolutions = 0

    with engine.connect() as conn:
        admin_id = get_or_create_admin(conn)

    with engine.begin() as conn:
        for coach_entry in coaches:
            account_data = coach_entry["account"]
            coach_details = coach_entry["coach_details"]
            approve = coach_entry.get("approve", True)

            account_id, account_created = get_or_create_account(conn, account_data)
            if account_created:
                inserted_accounts += 1

            client_row = conn.execute(text("SELECT client_id FROM account WHERE id = :account_id"), {"account_id": account_id}).first()
            client_id = client_row[0] if client_row else None
            if client_id is None:
                client_id = get_or_create_client(conn)
                conn.execute(text("UPDATE account SET client_id = :client_id WHERE id = :account_id"), {"client_id": client_id, "account_id": account_id})
                inserted_clients += 1

            coach_row = conn.execute(text("SELECT coach_id FROM account WHERE id = :account_id"), {"account_id": account_id}).first()
            existing_coach_id = coach_row[0] if coach_row else None
            if existing_coach_id is not None:
                print(f"Skipping {account_data['email']}: already has coach_id={existing_coach_id}")
                continue

            coach_availability_id = insert_coach_availability(conn)
            coach_id = get_or_create_coach(conn, coach_availability_id, coach_details.get("specialties"))
            inserted_coaches += 1

            conn.execute(text("UPDATE account SET coach_id = :coach_id WHERE id = :account_id"), {"coach_id": coach_id, "account_id": account_id})
            conn.execute(text("UPDATE coach SET coach_availability = :availability_id WHERE id = :coach_id"), {"availability_id": coach_availability_id, "coach_id": coach_id})

            inserted_availabilities += create_availabilities(conn, coach_availability_id, coach_details.get("availabilities", []))

            for cert in coach_details.get("certifications", []):
                cert_id = get_or_create_certification(conn, cert)
                link_coach_certification(conn, coach_id, cert_id)
                inserted_certifications += 1

            for exp in coach_details.get("experiences", []):
                exp_id = get_or_create_experience(conn, exp)
                link_coach_experience(conn, coach_id, exp_id)
                inserted_experiences += 1

            pricing_id = get_or_create_pricing_plan(conn, coach_id, coach_details["payment_interval"], coach_details["price_cents"])
            inserted_pricing_plans += 1

            request_id = create_coach_request(conn, coach_id)
            inserted_requests += 1

            if approve:
                create_resolution(conn, request_id, admin_id, account_id, True)
                mark_coach_verified(conn, coach_id)
                inserted_resolutions += 1

    print(
        f"Seed complete: {inserted_accounts} accounts, {inserted_clients} clients, {inserted_coaches} coaches, "
        f"{inserted_availabilities} availabilities, {inserted_experiences} experiences, "
        f"{inserted_certifications} certifications, {inserted_pricing_plans} pricing plans, "
        f"{inserted_requests} coach requests, {inserted_resolutions} approvals"
    )


if __name__ == "__main__":
    main()
