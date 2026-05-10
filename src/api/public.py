"""
Public (unauthenticated) endpoints used by the marketing landing page.

Surface:
  GET /public/platform_stats
  GET /public/leaderboards/{role}/{category}

Roles: "clients" | "coaches"
Client categories: "man-of-burn" | "cardi-athletes" | "consistency-kings"
Coach categories:  "mvp" | "most-liked" | "wisest"

Eligibility (all leaderboards): account.is_active AND NOT account.is_suspended.
Coach boards additionally require coach.verified.
"""
from datetime import datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, desc, exists, func, or_
from sqlmodel import select

from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    ClientCoachRelationship,
    ClientCoachRequest,
)
from src.database.meal.models import Food, Meal, MealFood, MealIngredient
from src.database.payment.models import (
    MAX_MONTHLY_PRICE_CENTS,
    PricingInterval,
    PricingPlan,
)
from src.database.reports.models import CoachReviews
from src.database.session import get_session
from src.database.telemetry.models import (
    ClientTelemetry,
    CompletedMealActivity,
    CompletedWorkout,
    CompletedWorkoutActivity,
    StepCount,
)
from src.database.workouts_and_activities.models import Workout

router = APIRouter(prefix="/public", tags=["public"])


# ────────────────────────────  schemas  ────────────────────────────
class PlatformStatsResponse(BaseModel):
    preset_workouts: int
    active_users: int
    verified_coaches: int
    average_coach_rating: float


class LeaderboardEntry(BaseModel):
    account_id: int
    name: str
    badge: str
    score: float
    display_score: str
    detail: str = ""
    pfp_url: str | None = None
    age: int | None = None
    gender: str | None = None


class LeaderboardResponse(BaseModel):
    role: str
    category: str
    entries: list[LeaderboardEntry]


# ────────────────────────────  ranking constants  ────────────────────────────
# Maximum review rating users can submit (CoachReviews.rating).
MAX_RATING: float = 5.0

# Most-liked weight: how strongly review volume modulates the rating.
# (rating/5) * num_reviews * MOST_LIKED_VOLUME_WEIGHT + rating
# C < 1 keeps a single 5★ review from outweighing many 4★ reviews.
MOST_LIKED_VOLUME_WEIGHT: float = 0.5

# MVP ceiling: worst-case (rating × monthly_cents) bound used as the reference
# point. Score = MAX_PRODUCT − (their_rating × their_monthly_cents). Higher
# score = bigger gap from the ceiling = better value-for-money.
MAX_RATING_PRICE_PRODUCT: float = MAX_RATING * float(MAX_MONTHLY_PRICE_CENTS)


# ────────────────────────────  helpers  ────────────────────────────
def _fmt_int(value) -> str:
    return f"{int(value or 0):,}"


def _fmt_float(value) -> str:
    return f"{float(value or 0):.1f}"


def _eligible_account_filter():
    """Account is active and not suspended."""
    return [
        Account.is_active == True,  # noqa: E712
        Account.is_suspended == False,  # noqa: E712
    ]


def _accepted_relationship_join(stmt):
    """
    Join the relationship → request chain restricted to accepted relationships.
    Mirrors how `/roles/coach/clients` defines an active client.
    """
    return (
        stmt.join(ClientCoachRequest, ClientCoachRequest.coach_id == Coach.id)
        .join(
            ClientCoachRelationship,
            ClientCoachRelationship.request_id == ClientCoachRequest.id,
        )
        .where(ClientCoachRequest.is_accepted == True)  # noqa: E712
    )


# ────────────────────────────  /platform_stats  ────────────────────────────
@router.get("/platform_stats", response_model=PlatformStatsResponse)
def get_platform_stats(db=Depends(get_session)):
    preset_workouts = db.exec(select(func.count()).select_from(Workout)).one()

    active_users = db.exec(
        select(func.count())
        .select_from(Account)
        .where(*_eligible_account_filter())
    ).one()

    verified_coaches = db.exec(
        select(func.count())
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, *_eligible_account_filter())  # noqa: E712
    ).one()

    average_rating = db.exec(
        select(func.avg(CoachReviews.rating))
        .select_from(CoachReviews)
        .join(Coach, CoachReviews.coach_id == Coach.id)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, *_eligible_account_filter())  # noqa: E712
    ).one()

    return PlatformStatsResponse(
        preset_workouts=int(preset_workouts or 0),
        active_users=int(active_users or 0),
        verified_coaches=int(verified_coaches or 0),
        average_coach_rating=round(float(average_rating or 0), 1),
    )


# ────────────────────────────  client leaderboards  ────────────────────────────
_CLIENT_PROFILE_COLS = (
    Account.id.label("account_id"),
    Account.name.label("name"),
    Account.pfp_url.label("pfp_url"),
    Account.age.label("age"),
    Account.gender.label("gender"),
)
_CLIENT_PROFILE_GROUP = (
    Account.id, Account.name, Account.pfp_url, Account.age, Account.gender,
)


def _client_entry_from_row(r, *, badge: str, score: float, fmt: Callable[[float], str], detail: str) -> LeaderboardEntry:
    return LeaderboardEntry(
        account_id=int(r.account_id),
        name=r.name,
        badge=badge,
        score=score,
        display_score=fmt(score),
        detail=detail,
        pfp_url=getattr(r, "pfp_url", None),
        age=getattr(r, "age", None),
        gender=getattr(r, "gender", None),
    )


def _meal_calories_for_telemetry(db, telemetry_ids: list[int]) -> float:
    """Sum the caloric intake across all CompletedMealActivity rows tied to the
    given telemetry IDs. Combines the modern `meal_food` (per-100g) path with
    legacy `meal_ingredient` rows; the meals API does the same fan-out."""
    if not telemetry_ids:
        return 0.0

    # Fetch the meal_ids referenced by completed activities. Each completed
    # meal activity references either a prescribed meal or an on-demand meal;
    # we aggregate caloric intake at the meal level.
    completed = db.exec(
        select(
            CompletedMealActivity.client_prescribed_meal_id,
            CompletedMealActivity.on_demand_meal_id,
        ).where(CompletedMealActivity.client_telemetry_id.in_(telemetry_ids))
    ).all()

    # Resolve prescribed → meal_id via ClientPrescribedMeal lookups.
    from src.database.meal.models import ClientPrescribedMeal

    meal_ids: list[int] = []
    prescribed_ids = [c.client_prescribed_meal_id for c in completed if c.client_prescribed_meal_id]
    if prescribed_ids:
        for pm in db.exec(
            select(ClientPrescribedMeal.meal_id).where(
                ClientPrescribedMeal.id.in_(prescribed_ids)
            )
        ).all():
            meal_ids.append(int(pm))
    for c in completed:
        if c.on_demand_meal_id is not None:
            meal_ids.append(int(c.on_demand_meal_id))

    if not meal_ids:
        return 0.0

    # Modern: meal_food × food.calories_per_100g × grams / 100
    modern = db.exec(
        select(
            func.coalesce(
                func.sum(Food.calories_per_100g * MealFood.grams / 100.0), 0.0
            )
        )
        .select_from(MealFood)
        .join(Food, Food.id == MealFood.food_id)
        .where(MealFood.meal_id.in_(meal_ids))
    ).one()

    # Legacy: meal_ingredient.calories
    legacy = db.exec(
        select(func.coalesce(func.sum(MealIngredient.calories), 0))
        .where(MealIngredient.meal_id.in_(meal_ids))
    ).one()

    return float(modern or 0) + float(legacy or 0)


def _client_man_of_burn(db) -> LeaderboardResponse:
    """Score = (calories burned via completed workouts) − (calories consumed via
    completed meals), summed over the last 30 days."""
    cutoff = datetime.utcnow() - timedelta(days=30)

    # Pull burn aggregated per account in one pass.
    burn_rows = db.exec(
        select(
            *_CLIENT_PROFILE_COLS,
            func.coalesce(func.sum(CompletedWorkoutActivity.estimated_calories), 0).label("burn"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .join(CompletedWorkout, CompletedWorkout.client_telemetry_id == ClientTelemetry.id)
        .join(
            CompletedWorkoutActivity,
            CompletedWorkout.completed_workout_details_id == CompletedWorkoutActivity.id,
        )
        .where(
            *_eligible_account_filter(),
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
            CompletedWorkoutActivity.estimated_calories.is_not(None),
        )
        .group_by(*_CLIENT_PROFILE_GROUP)
    ).all()

    # For each candidate (top burners are eligible), subtract their intake.
    # We bound the candidate set to the top ~15 raw burners to keep the second
    # pass cheap — anyone outside that window can't crack the top 5 net.
    candidates = sorted(burn_rows, key=lambda r: float(r.burn or 0), reverse=True)[:15]
    account_rows = db.exec(
        select(Account.id, Account.client_id).where(
            Account.id.in_([int(r.account_id) for r in candidates])
        )
    ).all()
    account_to_client_id = {
        int(account_id): int(client_id)
        for account_id, client_id in account_rows
        if client_id is not None
    }

    entries: list[LeaderboardEntry] = []
    for r in candidates:
        # Telemetry IDs for this client in the window — needed for intake.
        client_id = account_to_client_id.get(int(r.account_id))
        tel_ids = []
        if client_id is not None:
            tel_ids = [
                int(tid)
                for tid in db.exec(
                    select(ClientTelemetry.id).where(
                        ClientTelemetry.client_id == client_id,
                        ClientTelemetry.date >= cutoff,
                    )
                ).all()
            ]
        intake = _meal_calories_for_telemetry(db, tel_ids)
        net = float(r.burn or 0) - intake
        entries.append(
            _client_entry_from_row(
                r, badge="Net 30d burn", score=net, fmt=_fmt_int,
                detail=f"net kcal ({int(r.burn or 0):,} burn − {int(intake):,} intake)",
            )
        )

    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="clients", category="man-of-burn", entries=entries[:5])


def _client_cardi_athletes(db) -> LeaderboardResponse:
    """Σ steps over last 30 days (unchanged math, eligibility tightened)."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    rows = db.exec(
        select(
            *_CLIENT_PROFILE_COLS,
            func.coalesce(func.sum(StepCount.step_count), 0).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .join(StepCount, StepCount.client_telemetry_id == ClientTelemetry.id)
        .where(
            *_eligible_account_filter(),
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
        )
        .group_by(*_CLIENT_PROFILE_GROUP)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    entries = [
        _client_entry_from_row(
            r, badge="Monthly steps", score=float(r.score or 0),
            fmt=_fmt_int, detail="steps",
        )
        for r in rows
    ]
    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="clients", category="cardi-athletes", entries=entries[:5])


def _client_consistency_kings(db) -> LeaderboardResponse:
    """Distinct telemetry days (last 7) where the client logged at least one
    completed workout, completed meal, or step count. Health-metrics-only days
    are excluded — weighing yourself isn't meaningful activity."""
    cutoff = datetime.utcnow() - timedelta(days=7)

    has_meaningful_activity = or_(
        exists().where(CompletedWorkout.client_telemetry_id == ClientTelemetry.id),
        exists().where(CompletedMealActivity.client_telemetry_id == ClientTelemetry.id),
        exists().where(StepCount.client_telemetry_id == ClientTelemetry.id),
    )

    rows = db.exec(
        select(
            *_CLIENT_PROFILE_COLS,
            func.count(func.distinct(func.date(ClientTelemetry.date))).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .where(
            *_eligible_account_filter(),
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
            has_meaningful_activity,
        )
        .group_by(*_CLIENT_PROFILE_GROUP)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    entries = [
        _client_entry_from_row(
            r, badge="Active days", score=float(r.score or 0),
            fmt=_fmt_int, detail="active days",
        )
        for r in rows
    ]
    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="clients", category="consistency-kings", entries=entries[:5])


# ────────────────────────────  coach leaderboards  ────────────────────────────
def _coach_mvp(db) -> LeaderboardResponse:
    """
    MVP ranks coaches by how far below the platform's worst-case rating×price
    product they sit. Lower price OR lower rating widens the gap, so cheap
    high-rated coaches dominate, expensive low-rated coaches lag.

    score = MAX_RATING_PRICE_PRODUCT - (avg_rating × monthly_cents)

    The ceiling MAX_RATING_PRICE_PRODUCT is derived from
    `payment.models.MAX_MONTHLY_PRICE_CENTS`; if that constant changes the
    formula scales accordingly.
    """
    monthly_cents = case(
        (PricingPlan.payment_interval == PricingInterval.YEARLY, PricingPlan.price_cents / 12.0),
        else_=PricingPlan.price_cents,
    )
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.pfp_url.label("pfp_url"),
            Account.age.label("age"),
            Account.gender.label("gender"),
            Coach.specialties.label("specialties"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("avg_rating"),
            func.avg(monthly_cents).label("monthly_cents"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(PricingPlan, PricingPlan.coach_id == Coach.id)
        .outerjoin(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, *_eligible_account_filter())  # noqa: E712
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender, Coach.specialties)
        .having(func.count(CoachReviews.id) > 0)
    ).all()

    entries: list[LeaderboardEntry] = []
    for r in rows:
        rating = float(r.avg_rating or 0)
        cents = float(r.monthly_cents or 0)
        product = rating * cents
        score = MAX_RATING_PRICE_PRODUCT - product
        monthly_dollars = cents / 100.0
        entries.append(
            LeaderboardEntry(
                account_id=int(r.account_id),
                name=r.name,
                badge=r.specialties or "Verified coach",
                score=score,
                display_score=f"{int(score):,}",
                detail=f"{rating:.1f}★ at ${monthly_dollars:.0f}/mo",
                pfp_url=r.pfp_url,
                age=r.age,
                gender=r.gender,
            )
        )

    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="coaches", category="mvp", entries=entries[:5])


def _coach_most_liked(db) -> LeaderboardResponse:
    """
    Volume-weighted rating. A single 5★ review shouldn't beat 50× 4.6★ reviews
    (law of large numbers). Formula:

        score = (rating / MAX_RATING) * num_reviews * C + rating

    where C = MOST_LIKED_VOLUME_WEIGHT (< 1) keeps the volume term from
    swamping the rating term entirely. Tweak C to shift the balance.
    """
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.pfp_url.label("pfp_url"),
            Account.age.label("age"),
            Account.gender.label("gender"),
            Coach.specialties.label("specialties"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("avg_rating"),
            func.count(CoachReviews.id).label("review_count"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, *_eligible_account_filter())  # noqa: E712
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender, Coach.specialties)
    ).all()

    entries: list[LeaderboardEntry] = []
    for r in rows:
        rating = float(r.avg_rating or 0)
        n = int(r.review_count or 0)
        score = (rating / MAX_RATING) * n * MOST_LIKED_VOLUME_WEIGHT + rating
        entries.append(
            LeaderboardEntry(
                account_id=int(r.account_id),
                name=r.name,
                badge=r.specialties or "Verified coach",
                score=score,
                display_score=_fmt_float(score),
                detail=f"{rating:.1f}★ × {n} reviews",
                pfp_url=r.pfp_url,
                age=r.age,
                gender=r.gender,
            )
        )

    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="coaches", category="most-liked", entries=entries[:5])


def _coach_wisest(db) -> LeaderboardResponse:
    """
    Wisest = veterans who keep clients long-term and don't over-stretch.

        score = days_on_platform * avg_retention / max(users_coached, 1)

    Reads as: tenure × deep relationships, penalized for big rosters that
    spread attention thin. Inverts the prior formula (which divided by
    avg_retention) on purpose — we want to reward retention, not volume.
    """
    now = datetime.utcnow()

    stmt = (
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.pfp_url.label("pfp_url"),
            Account.age.label("age"),
            Account.gender.label("gender"),
            Coach.specialties.label("specialties"),
            Account.created_at.label("coach_created_at"),
            ClientCoachRelationship.created_at.label("relationship_created_at"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, *_eligible_account_filter())  # noqa: E712
    )
    rows = db.exec(_accepted_relationship_join(stmt)).all()

    coaches: dict[int, dict] = {}
    for r in rows:
        key = int(r.account_id)
        bucket = coaches.get(key)
        if bucket is None:
            coach_created = r.coach_created_at
            if coach_created is None:
                days_on_platform = 1
            else:
                if coach_created.tzinfo is not None:
                    coach_created = coach_created.replace(tzinfo=None)
                days_on_platform = max((now - coach_created).days, 1)

            bucket = coaches[key] = {
                "name": r.name,
                "badge": r.specialties or "Verified coach",
                "days_on_platform": days_on_platform,
                "retention_days": [],
                "pfp_url": r.pfp_url,
                "age": r.age,
                "gender": r.gender,
            }

        rel_created = r.relationship_created_at
        if rel_created is None:
            retention = 1
        else:
            if rel_created.tzinfo is not None:
                rel_created = rel_created.replace(tzinfo=None)
            retention = max((now - rel_created).days, 1)
        bucket["retention_days"].append(retention)

    entries: list[LeaderboardEntry] = []
    for account_id, c in coaches.items():
        users_coached = len(c["retention_days"])
        if users_coached == 0:
            continue
        avg_retention = sum(c["retention_days"]) / users_coached
        score = (c["days_on_platform"] * avg_retention) / max(users_coached, 1)
        entries.append(
            LeaderboardEntry(
                account_id=account_id,
                name=c["name"],
                badge=c["badge"],
                score=float(score),
                display_score=_fmt_float(score),
                detail=f"{users_coached} users, {avg_retention:.0f}d avg retention",
                pfp_url=c["pfp_url"],
                age=c["age"],
                gender=c["gender"],
            )
        )

    entries.sort(key=lambda e: e.score, reverse=True)
    return LeaderboardResponse(role="coaches", category="wisest", entries=entries[:5])


# ────────────────────────────  /leaderboards/{role}/{category}  ────────────────────────────
CLIENT_LEADERBOARDS = {
    "man-of-burn": _client_man_of_burn,
    "cardi-athletes": _client_cardi_athletes,
    "consistency-kings": _client_consistency_kings,
}

COACH_LEADERBOARDS = {
    "mvp": _coach_mvp,
    "most-liked": _coach_most_liked,
    "wisest": _coach_wisest,
}


@router.get("/leaderboards/{role}/{category}", response_model=LeaderboardResponse)
def get_leaderboard(role: str, category: str, db=Depends(get_session)):
    role_norm = role.lower()
    cat_norm = category.lower()
    if role_norm in {"client", "clients"} and cat_norm in CLIENT_LEADERBOARDS:
        return CLIENT_LEADERBOARDS[cat_norm](db)
    if role_norm in {"coach", "coaches"} and cat_norm in COACH_LEADERBOARDS:
        return COACH_LEADERBOARDS[cat_norm](db)
    return LeaderboardResponse(role=role_norm, category=cat_norm, entries=[])
