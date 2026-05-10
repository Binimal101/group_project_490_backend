"""
Public (unauthenticated) endpoints used by the marketing landing page.

Surface:
  GET /public/platform_stats
  GET /public/leaderboards/{role}/{category}

Roles: "clients" | "coaches"
Client categories: "man-of-burn" | "cardi-athletes" | "consistency-kings"
Coach categories:  "mvp" | "most-liked" | "wisest"
"""
from datetime import datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, desc, func
from sqlmodel import select

from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    ClientCoachRelationship,
    ClientCoachRequest,
)
from src.database.payment.models import PricingInterval, PricingPlan
from src.database.reports.models import CoachReviews
from src.database.session import get_session
from src.database.telemetry.models import (
    ClientTelemetry,
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


# ────────────────────────────  helpers  ────────────────────────────
def _fmt_int(value) -> str:
    return f"{int(value or 0):,}"


def _fmt_float(value) -> str:
    return f"{float(value or 0):.1f}"


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
        .where(Account.is_active == True)  # noqa: E712
    ).one()

    verified_coaches = db.exec(
        select(func.count())
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)  # noqa: E712
    ).one()

    average_rating = db.exec(
        select(func.avg(CoachReviews.rating))
        .select_from(CoachReviews)
        .join(Coach, CoachReviews.coach_id == Coach.id)
        .join(Account, Account.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)  # noqa: E712
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


def _client_entries(
    rows, *, badge: str, fmt: Callable[[float], str], detail_suffix: str
) -> list[LeaderboardEntry]:
    out = [
        LeaderboardEntry(
            account_id=int(r.account_id),
            name=r.name,
            badge=badge,
            score=float(r.score or 0),
            display_score=fmt(r.score),
            detail=detail_suffix,
            pfp_url=getattr(r, "pfp_url", None),
            age=getattr(r, "age", None),
            gender=getattr(r, "gender", None),
        )
        for r in rows
    ]
    return sorted(out, key=lambda e: e.score, reverse=True)[:5]


def _client_man_of_burn(db) -> LeaderboardResponse:
    cutoff = datetime.utcnow() - timedelta(days=30)
    rows = db.exec(
        select(
            *_CLIENT_PROFILE_COLS,
            func.coalesce(
                func.sum(CompletedWorkoutActivity.estimated_calories), 0
            ).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .join(CompletedWorkout, CompletedWorkout.client_telemetry_id == ClientTelemetry.id)
        .join(
            CompletedWorkoutActivity,
            CompletedWorkout.completed_workout_details_id == CompletedWorkoutActivity.id,
        )
        .where(
            Account.is_active == True,  # noqa: E712
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
            CompletedWorkoutActivity.estimated_calories.is_not(None),
        )
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="man-of-burn",
        entries=_client_entries(
            rows, badge="Monthly burn", fmt=_fmt_int, detail_suffix="calories"
        ),
    )


def _client_cardi_athletes(db) -> LeaderboardResponse:
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
            Account.is_active == True,  # noqa: E712
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
        )
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="cardi-athletes",
        entries=_client_entries(
            rows, badge="Monthly steps", fmt=_fmt_int, detail_suffix="steps"
        ),
    )


def _client_consistency_kings(db) -> LeaderboardResponse:
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = db.exec(
        select(
            *_CLIENT_PROFILE_COLS,
            func.count(ClientTelemetry.id).label("score"),
        )
        .select_from(Account)
        .join(ClientTelemetry, ClientTelemetry.client_id == Account.client_id)
        .where(
            Account.is_active == True,  # noqa: E712
            Account.client_id.is_not(None),
            ClientTelemetry.date >= cutoff,
        )
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender)
        .order_by(desc("score"))
        .limit(5)
    ).all()
    return LeaderboardResponse(
        role="clients",
        category="consistency-kings",
        entries=_client_entries(
            rows, badge="Weekly telemetry", fmt=_fmt_int, detail_suffix="submissions"
        ),
    )


# ────────────────────────────  coach leaderboards  ────────────────────────────
def _coach_mvp(db) -> LeaderboardResponse:
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
            (func.avg(monthly_cents) / 100.0).label("monthly_rate"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(PricingPlan, PricingPlan.coach_id == Coach.id)
        .outerjoin(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)  # noqa: E712
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender, Coach.specialties)
        .having(func.count(CoachReviews.id) > 0)
    ).all()

    entries = []
    for r in rows:
        rating = float(r.avg_rating or 0)
        monthly_dollars = float(r.monthly_rate or 0)
        score = rating / monthly_dollars if monthly_dollars > 0 else rating
        entries.append(
            LeaderboardEntry(
                account_id=int(r.account_id),
                name=r.name,
                badge=r.specialties or "Verified coach",
                score=score,
                display_score=_fmt_float(score),
                detail=f"{rating:.1f} avg rating at ${monthly_dollars:.0f}/mo",
                pfp_url=r.pfp_url,
                age=r.age,
                gender=r.gender,
            )
        )

    return LeaderboardResponse(
        role="coaches",
        category="mvp",
        entries=sorted(entries, key=lambda e: e.score, reverse=True)[:5],
    )


def _coach_most_liked(db) -> LeaderboardResponse:
    rows = db.exec(
        select(
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.pfp_url.label("pfp_url"),
            Account.age.label("age"),
            Account.gender.label("gender"),
            Coach.specialties.label("specialties"),
            func.coalesce(func.avg(CoachReviews.rating), 0).label("score"),
            func.count(CoachReviews.id).label("review_count"),
        )
        .select_from(Coach)
        .join(Account, Account.coach_id == Coach.id)
        .join(CoachReviews, CoachReviews.coach_id == Coach.id)
        .where(Coach.verified == True, Account.is_active == True)  # noqa: E712
        .group_by(Account.id, Account.name, Account.pfp_url, Account.age, Account.gender, Coach.specialties)
        .order_by(desc("score"))
        .limit(5)
    ).all()

    entries = [
        LeaderboardEntry(
            account_id=int(r.account_id),
            name=r.name,
            badge=r.specialties or "Verified coach",
            score=float(r.score or 0),
            display_score=_fmt_float(r.score),
            detail=f"{int(r.review_count or 0)} reviews",
            pfp_url=r.pfp_url,
            age=r.age,
            gender=r.gender,
        )
        for r in rows
    ]
    return LeaderboardResponse(
        role="coaches",
        category="most-liked",
        entries=sorted(entries, key=lambda e: e.score, reverse=True)[:5],
    )


def _coach_wisest(db) -> LeaderboardResponse:
    """
    Score = (days_on_platform * users_coached) / max(avg_retention_days, 1).
    Active relationship = ClientCoachRelationship whose request is accepted.
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
        .where(Coach.verified == True, Account.is_active == True)  # noqa: E712
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

    entries = []
    for account_id, c in coaches.items():
        users_coached = len(c["retention_days"])
        if users_coached == 0:
            continue
        avg_retention = sum(c["retention_days"]) / users_coached
        score = (c["days_on_platform"] * users_coached) / max(avg_retention, 1)
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

    return LeaderboardResponse(
        role="coaches",
        category="wisest",
        entries=sorted(entries, key=lambda e: e.score, reverse=True)[:5],
    )


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
