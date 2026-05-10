from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.api.public import MAX_RATING_PRICE_PRODUCT
from src.database.account.models import Account
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.meal.models import Food, Meal, MealFood
from src.database.payment.models import PricingInterval, PricingPlan
from src.database.reports.models import CoachReviews
from src.database.telemetry.models import (
    ClientTelemetry,
    CompletedMealActivity,
    CompletedWorkout,
    CompletedWorkoutActivity,
    HealthMetrics,
    StepCount,
)


def _slug() -> str:
    return uuid4().hex[:10]


def _create_client(db_session, *, name: str, suspended: bool = False):
    client = Client()
    db_session.add(client)
    db_session.flush()

    account = Account(
        name=name,
        email=f"{_slug()}@example.com",
        hashed_password="hashed-password",
        client_id=client.id,
        is_active=True,
        is_suspended=suspended,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account, client


def _create_coach(db_session, *, name: str, suspended: bool = False, verified: bool = True):
    coach = Coach(verified=verified)
    db_session.add(coach)
    db_session.flush()

    account = Account(
        name=name,
        email=f"{_slug()}@example.com",
        hashed_password="hashed-password",
        coach_id=coach.id,
        is_active=True,
        is_suspended=suspended,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account, coach


def _add_client_telemetry(db_session, client_id: int, *, day_offset: int, telemetry_type: str = "workout"):
    telemetry = ClientTelemetry(
        client_id=client_id,
        telemetry_type=telemetry_type,
        date=datetime.now(timezone.utc) - timedelta(days=day_offset),
    )
    db_session.add(telemetry)
    db_session.flush()
    return telemetry


def _add_workout_burn(db_session, telemetry_id: int, calories: int):
    details = CompletedWorkoutActivity(estimated_calories=calories)
    db_session.add(details)
    db_session.flush()

    completed = CompletedWorkout(
        completed_workout_details_id=details.id,
        client_telemetry_id=telemetry_id,
    )
    db_session.add(completed)
    db_session.flush()
    return completed


def _add_meal_intake(db_session, creator_account_id: int, telemetry_id: int, calories: int):
    meal = Meal(created_by_account_id=creator_account_id, meal_name=f"Meal {_slug()}")
    db_session.add(meal)
    db_session.flush()

    food = Food(
        name=f"Food {_slug()}",
        calories_per_100g=float(calories),
    )
    db_session.add(food)
    db_session.flush()

    db_session.add(MealFood(meal_id=meal.id, food_id=food.id, grams=100.0))
    db_session.add(
        CompletedMealActivity(
            on_demand_meal_id=meal.id,
            client_telemetry_id=telemetry_id,
            meal_kind="dinner",
        )
    )
    db_session.commit()


def _add_step_day(db_session, client_id: int, *, day_offset: int, step_count: int):
    telemetry = _add_client_telemetry(db_session, client_id, day_offset=day_offset, telemetry_type="steps")
    db_session.add(StepCount(client_telemetry_id=telemetry.id, step_count=step_count))
    db_session.commit()


def _add_health_day(db_session, client_id: int, *, day_offset: int, weight: int):
    telemetry = _add_client_telemetry(db_session, client_id, day_offset=day_offset, telemetry_type="health")
    db_session.add(HealthMetrics(client_telemetry_id=telemetry.id, weight=weight))
    db_session.commit()


def _add_coach_pricing(db_session, coach_id: int, *, payment_interval: PricingInterval, price_cents: int):
    plan = PricingPlan(coach_id=coach_id, payment_interval=payment_interval, price_cents=price_cents)
    db_session.add(plan)
    db_session.commit()
    return plan


def _add_reviews(db_session, coach_id: int, client_id: int, *, rating: float, count: int):
    for index in range(count):
        db_session.add(
            CoachReviews(
                coach_id=coach_id,
                client_id=client_id,
                rating=rating,
                review_text=f"Review {index} {_slug()}",
            )
        )
    db_session.commit()


def _leaderboard_entries(test_client, role: str, category: str):
    response = test_client.get(f"/public/leaderboards/{role}/{category}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == role
    assert body["category"] == category
    return body["entries"]


def test_man_of_burn_uses_net_calories_and_excludes_suspended_clients(test_client, db_session):
    active_high, active_high_client = _create_client(db_session, name="Active High")
    active_low, active_low_client = _create_client(db_session, name="Active Low")
    suspended, suspended_client = _create_client(db_session, name="Suspended", suspended=True)

    high_tel = _add_client_telemetry(db_session, active_high_client.id, day_offset=1)
    _add_workout_burn(db_session, high_tel.id, calories=10_000_000)
    _add_meal_intake(db_session, active_high.id, high_tel.id, calories=1_000_000)

    low_tel = _add_client_telemetry(db_session, active_low_client.id, day_offset=2)
    _add_workout_burn(db_session, low_tel.id, calories=8_000_000)
    db_session.commit()

    suspended_tel = _add_client_telemetry(db_session, suspended_client.id, day_offset=3)
    _add_workout_burn(db_session, suspended_tel.id, calories=20_000_000)
    db_session.commit()

    entries = _leaderboard_entries(test_client, "clients", "man-of-burn")
    top_ids = [entry["account_id"] for entry in entries]

    assert active_high.id in top_ids
    assert active_low.id in top_ids
    assert suspended.id not in top_ids

    active_high_entry = next(entry for entry in entries if entry["account_id"] == active_high.id)
    active_low_entry = next(entry for entry in entries if entry["account_id"] == active_low.id)

    assert active_high_entry["score"] == pytest.approx(9_000_000)
    assert active_high_entry["display_score"] == "9,000,000"
    assert active_low_entry["score"] == pytest.approx(8_000_000)


def test_consistency_kings_counts_only_meaningful_activity(test_client, db_session):
    steady, steady_client = _create_client(db_session, name="Steady Client")
    noisy, noisy_client = _create_client(db_session, name="Noisy Client")
    suspended, suspended_client = _create_client(db_session, name="Suspended Client", suspended=True)

    for day_offset in range(7):
                if day_offset == 1:
                        _add_health_day(db_session, steady_client.id, day_offset=day_offset, weight=170)
                else:
                        _add_step_day(db_session, steady_client.id, day_offset=day_offset, step_count=10_000 + day_offset)

    for day_offset in range(7):
                _add_step_day(db_session, noisy_client.id, day_offset=day_offset, step_count=15_000 + day_offset)

    for day_offset in range(7):
                _add_step_day(db_session, suspended_client.id, day_offset=day_offset, step_count=20_000 + day_offset)

    entries = _leaderboard_entries(test_client, "clients", "consistency-kings")
    top_ids = [entry["account_id"] for entry in entries]

    assert noisy.id in top_ids
    assert steady.id in top_ids
    assert suspended.id not in top_ids

    noisy_entry = next(entry for entry in entries if entry["account_id"] == noisy.id)
    steady_entry = next(entry for entry in entries if entry["account_id"] == steady.id)

    assert noisy_entry["score"] == pytest.approx(7)
    assert steady_entry["score"] == pytest.approx(6)
    assert noisy_entry["score"] > steady_entry["score"]


# def test_coach_mvp_uses_monthly_equivalent_price_and_excludes_suspended(test_client, db_session):
#     _reviewer, reviewer_client = _create_client(db_session, name="Reviewer")

#     yearly_account, yearly_coach = _create_coach(db_session, name="Yearly Coach")
#     monthly_account, monthly_coach = _create_coach(db_session, name="Monthly Coach")
#     suspended_account, suspended_coach = _create_coach(db_session, name="Suspended Coach", suspended=True)

#     _add_coach_pricing(db_session, yearly_coach.id, payment_interval=PricingInterval.YEARLY, price_cents=60_000)
#     _add_coach_pricing(db_session, monthly_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=10_000)
#     _add_coach_pricing(db_session, suspended_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=0)

#     _add_reviews(db_session, yearly_coach.id, reviewer_client.id, rating=5.0, count=1)
#     _add_reviews(db_session, monthly_coach.id, reviewer_client.id, rating=4.0, count=1)
#     _add_reviews(db_session, suspended_coach.id, reviewer_client.id, rating=5.0, count=3)

#     entries = _leaderboard_entries(test_client, "coaches", "mvp")
#     top_ids = [entry["account_id"] for entry in entries]

#     assert yearly_account.id in top_ids
#     assert monthly_account.id in top_ids
#     assert suspended_account.id not in top_ids

#     yearly_entry = next(entry for entry in entries if entry["account_id"] == yearly_account.id)
#     monthly_entry = next(entry for entry in entries if entry["account_id"] == monthly_account.id)

#     assert yearly_entry["score"] == pytest.approx(MAX_RATING_PRICE_PRODUCT - 5.0 * 5_000)
#     assert yearly_entry["display_score"] == "225,000"
#     assert yearly_entry["score"] > monthly_entry["score"]


# def test_most_liked_weights_review_volume(test_client, db_session):
#     _reviewer, reviewer_client = _create_client(db_session, name="Volume Reviewer")

#     light_account, light_coach = _create_coach(db_session, name="Light Coach")
#     heavy_account, heavy_coach = _create_coach(db_session, name="Heavy Coach")

#     _add_coach_pricing(db_session, light_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=10_000)
#     _add_coach_pricing(db_session, heavy_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=10_000)

#     _add_reviews(db_session, light_coach.id, reviewer_client.id, rating=4.5, count=1)
#     _add_reviews(db_session, heavy_coach.id, reviewer_client.id, rating=4.5, count=1000)

#     entries = _leaderboard_entries(test_client, "coaches", "most-liked")

#     heavy_entry = next(entry for entry in entries if entry["account_id"] == heavy_account.id)
#     light_entry = next(entry for entry in entries if entry["account_id"] == light_account.id)

#     assert heavy_entry["score"] > light_entry["score"]
#     assert heavy_entry["display_score"] == "454.5"
#     assert light_entry["display_score"] == "5.0"