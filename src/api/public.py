from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel
from sqlalchemy import case, desc, func
from sqlmodel import select
from fastapi import APIRouter, Depends

from src.database.account.models import Account
from src.database.coach_client_relationship.models import ClientCoachRelationship, ClientCoachRequest
from src.database.coach.models import Coach
from src.database.payment.models import PricingInterval, PricingPlan
from src.database.reports.models import CoachReviews
from src.database.session import get_session
from src.database.telemetry.models import ClientTelemetry, CompletedWorkout, CompletedWorkoutActivity, StepCount
from src.database.workouts_and_activities.models import Workout


router = APIRouter(prefix="/public", tags=["public"])


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
    detail: str


class LeaderboardResponse(BaseModel):
    role: str
    category: str
    entries: list[LeaderboardEntry]


@router.get("/platform_stats", response_model=PlatformStatsResponse)
def get_platform_stats(db=Depends(get_session)):
    preset_workouts = db.exec(
        select(func.count()).select_from(Workout)
    ).one()
    active_users = db.exec(
        select(func.count()).select_from(Account).where(Account.is_active == True)
    ).one()
    verified_coaches = db.exec(
        select(func.count())
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)
    ).one()
    average_rating = db.exec(
        select(func.avg(CoachReviews.rating))
        .select_from(CoachReviews)
        .join(Coach, CoachReviews.coach_id == Coach.id)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)
    ).one()

    return PlatformStatsResponse(
        preset_workouts=int(preset_workouts or 0),
        active_users=int(active_users or 0),
        verified_coaches=int(verified_coaches or 0),
        average_coach_rating=round(float(average_rating or 0), 1),
    )


def _format_int(value: float | int | None) -> str:
    return f"{int(value or 0):,}"


def _format_float(value: float | int | None) -> str:
    return f"{float(value or 0):.1f}"


def _client_entries(rows, *, badge: str, score_formatter: Callable[[float], str], detail_suffix: str) -> list[LeaderboardEntry]:
    entries = []
    for row in rows:
        score = float(row.score or 0)
        entries.append(
            LeaderboardEntry(
                account_id=int(row.account_id),
                name=row.name,
                badge=badge,
                score=score,
                display_score=score_formatter(score),
                detail=detail_suffix,
            )
        )
    return sorted(entries, key=lambda entry: entry.score, reverse=True)[:5]


def _coach_entries(rows, *, score_formatter: Callable[[float], str]) -> list[LeaderboardEntry]:
    entries = []
    for row in rows:
        score = float(row.score or 0)
        badge = row.specialties or "Verified coach"
        entries.append(
            LeaderboardEntry(
                account_id=int(row.account_id),
                name=row.name,
                badge=badge,
                score=score,
                display_score=score_formatter(score),
                detail=getattr(row, "detail", ""),
            )
        )
    return sorted(entries, key=lambda entry: entry.score, reverse=True)[:5]


def _client_man_of_burn(db) -> LeaderboardResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            func.coalesce(func.sum(CompletedWorkoutActivity.estimated_calories), 0).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .join(CompletedWorkout, CompletedWorkout.client_telemetry_id == ClientTelemetry.id)
        .join(CompletedWorkoutActivity, CompletedWorkout.completed_workout_details_id == CompletedWorkoutActivity.id)
        .where(
            Account.is_active == True,
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
            CompletedWorkoutActivity.estimated_calories.is_not(None),
        )
        .group_by(Account.id, Account.name)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="man-of-burn",
        entries=_client_entries(rows, badge="Monthly burn", score_formatter=_format_int, detail_suffix="calories"),
    )


def _client_cardi_athletes(db) -> LeaderboardResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            func.coalesce(func.sum(StepCount.step_count), 0).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .join(StepCount, StepCount.client_telemetry_id == ClientTelemetry.id)
        .where(
            Account.is_active == True,
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
        )
        .group_by(Account.id, Account.name)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="cardi-athletes",
        entries=_client_entries(rows, badge="Monthly steps", score_formatter=_format_int, detail_suffix="steps"),
    )


def _client_consistency_kings(db) -> LeaderboardResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            func.count(ClientTelemetry.id).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .where(
            Account.is_active == True,
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
        )
        .group_by(Account.id, Account.name)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="consistency-kings",
        entries=_client_entries(rows, badge="Weekly telemetry", score_formatter=_format_int, detail_suffix="submissions"),
    )


def _coach_mvp(db) -> LeaderboardResponse:
    monthly_rate = case(
        (PricingPlan.payment_interval == PricingInterval.YEARLY, PricingPlan.price_cents / 12.0),
        else_=PricingPlan.price_cents,
    )
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Coach.specialties.label("specialties"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("avg_rating"),
            (func.avg(monthly_rate) / 100.0).label("monthly_rate"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(PricingPlan, PricingPlan.coach_id == Coach.id)
        .outerjoin(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)
        .group_by(Account.id, Account.name, Coach.specialties)
        .having(func.count(CoachReviews.id) > 0)
    ).all()
    entries = []
    for row in rows:
        avg_rating = float(row.avg_rating or 0)
        monthly_rate_dollars = float(row.monthly_rate or 0)
        score = avg_rating / monthly_rate_dollars if monthly_rate_dollars > 0 else avg_rating
        entries.append(
            LeaderboardEntry(
                account_id=int(row.account_id),
                name=row.name,
                badge=row.specialties or "Verified coach",
                score=score,
                display_score=_format_float(score),
                detail=f"{avg_rating:.1f} avg rating at ${monthly_rate_dollars:.0f}/mo",
            )
        )

    return LeaderboardResponse(
        role="coaches",
        category="mvp",
        entries=sorted(entries, key=lambda entry: entry.score, reverse=True)[:5],
    )


def _coach_most_liked(db) -> LeaderboardResponse:
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Coach.specialties.label("specialties"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("score"),
            func.count(CoachReviews.id).label("review_count"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("avg_rating"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)
        .group_by(Account.id, Account.name, Coach.specialties)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="coaches",
        category="most-liked",
        entries=sorted([
            LeaderboardEntry(
                account_id=int(row.account_id),
                name=row.name,
                badge=row.specialties or "Verified coach",
                score=float(row.score or 0),
                display_score=_format_float(row.score),
                detail=f"{int(row.review_count or 0)} reviews",
            )
            for row in rows
        ], key=lambda entry: entry.score, reverse=True)[:5],
    )


def _coach_wisest(db) -> LeaderboardResponse:
    now = datetime.utcnow()
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Coach.specialties.label("specialties"),
            Account.created_at.label("created_at"),
            ClientCoachRelationship.created_at.label("relationship_created_at"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(ClientCoachRequest, ClientCoachRequest.coach_id == Coach.id)
        .join(ClientCoachRelationship, ClientCoachRelationship.request_id == ClientCoachRequest.id)
        .where(
            Coach.verified == True,
            Account.is_active == True,
            ClientCoachRelationship.is_active == True,
            ClientCoachRelationship.coach_blocked == False,
            ClientCoachRelationship.client_blocked == False,
        )
    ).all()

    coaches = {}
    for row in rows:
        coach_key = int(row.account_id)
        if coach_key not in coaches:
            created_at = row.created_at
            if created_at is None:
                days_on_platform = 1
            else:
                if created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)
                days_on_platform = max((now - created_at).days, 1)

            coaches[coach_key] = {
                "account_id": coach_key,
                "name": row.name,
                "badge": row.specialties or "Verified coach",
                "days_on_platform": days_on_platform,
                "retention_days": [],
            }

        relationship_created_at = row.relationship_created_at
        if relationship_created_at is None:
            retention_days = 1
        else:
            if relationship_created_at.tzinfo is not None:
                relationship_created_at = relationship_created_at.replace(tzinfo=None)
            retention_days = max((now - relationship_created_at).days, 1)
        coaches[coach_key]["retention_days"].append(retention_days)

    entries = []
    for coach in coaches.values():
        users_coached = len(coach["retention_days"])
        if users_coached == 0:
            continue

        average_retention = sum(coach["retention_days"]) / users_coached
        score = (coach["days_on_platform"] * users_coached) / max(average_retention, 1)
        entries.append(
            LeaderboardEntry(
                account_id=coach["account_id"],
                name=coach["name"],
                badge=coach["badge"],
                score=float(score),
                display_score=_format_float(score),
                detail=f"{users_coached} users, {average_retention:.0f}d avg retention",
            )
        )

    return LeaderboardResponse(
        role="coaches",
        category="wisest",
        entries=sorted(entries, key=lambda entry: entry.score, reverse=True)[:5],
    )


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
    normalized_role = role.lower()
    normalized_category = category.lower()
    if normalized_role in {"client", "clients"} and normalized_category in CLIENT_LEADERBOARDS:
        return CLIENT_LEADERBOARDS[normalized_category](db)
    if normalized_role in {"coach", "coaches"} and normalized_category in COACH_LEADERBOARDS:
        return COACH_LEADERBOARDS[normalized_category](db)
    return LeaderboardResponse(role=normalized_role, category=normalized_category, entries=[])


@router.get("/leaderboards/clients/man-of-burn", response_model=LeaderboardResponse)
def get_man_of_burn_leaderboard(db=Depends(get_session)):
    return _client_man_of_burn(db)


@router.get("/leaderboards/clients/cardi-athletes", response_model=LeaderboardResponse)
def get_cardi_athletes_leaderboard(db=Depends(get_session)):
    return _client_cardi_athletes(db)


@router.get("/leaderboards/clients/consistency-kings", response_model=LeaderboardResponse)
def get_consistency_kings_leaderboard(db=Depends(get_session)):
    return _client_consistency_kings(db)


@router.get("/leaderboards/coaches/mvp", response_model=LeaderboardResponse)
def get_mvp_leaderboard(db=Depends(get_session)):
    return _coach_mvp(db)


@router.get("/leaderboards/coaches/most-liked", response_model=LeaderboardResponse)
def get_most_liked_leaderboard(db=Depends(get_session)):
    return _coach_most_liked(db)


@router.get("/leaderboards/coaches/wisest", response_model=LeaderboardResponse)
def get_wisest_leaderboard(db=Depends(get_session)):
    return _coach_wisest(db)
