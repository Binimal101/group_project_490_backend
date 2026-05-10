from datetime import timezone
from src.api.roles.client.fitness import (
    APIRouter,
    PaginationParams,
    Session,
    TELEMETRY_STEPS,
    _get_or_create_daily_telemetry_for_type,
    datetime,
    select,
)
from src.database.telemetry.models import ClientTelemetry, CompletedMealActivity, HealthMetrics, StepCount, CompletedSurvey, DailyMoodSurvey, CompletedWorkout
from src.database.meal.models import Meal, MealFood, MealIngredient, Food, ClientPrescribedMeal
from src.api.roles.client.domain import StepCountUpdateInput, StepCountUpdateOutput, WeightUpdateInput
from src.database.session import get_session
from src.database.account.models import Account
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from src.api.dependencies import get_client_account

today = datetime.utcnow().date()

router = APIRouter(prefix="/roles/client/telemetry", tags=["client", "telemetry"])

@router.put("/update_steps")
def update_steps(step_count: StepCountUpdateInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry = _get_or_create_daily_telemetry_for_type(db, acc.client_id, TELEMETRY_STEPS)
    
    step_count_entry = db.exec(select(StepCount).where(StepCount.client_telemetry_id == telemetry.id)).first()
    if not step_count_entry:
        step_count_entry = StepCount(step_count=step_count.step_count, client_telemetry_id=telemetry.id)
        db.add(step_count_entry)
    else:
        step_count_entry.step_count = step_count.step_count
    
    db.commit()
    db.refresh(step_count_entry)

    return StepCountUpdateOutput(step_count=step_count_entry.step_count)


@router.get("/query/steps", response_model=list[StepCount])
def query_step_counts(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(StepCount).join(ClientTelemetry, StepCount.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(StepCount.id.desc())
    steps = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return steps

@router.get("/query/weights", response_model=list[HealthMetrics])
def query_weights(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(HealthMetrics).join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(HealthMetrics.id.desc())

    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

@router.put("/update_weight/{health_metrics_id}", response_model=HealthMetrics)
def update_weight(health_metrics_id: int, payload: WeightUpdateInput, db: Session = Depends(get_session), acc: Account = Depends(get_client_account)):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    health_metrics = db.get(HealthMetrics, health_metrics_id)
    if health_metrics is None:
        raise HTTPException(status_code=404, detail="Weight entry not found")

    telemetry = db.get(ClientTelemetry, health_metrics.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this weight entry")

    health_metrics.weight = payload.weight

    db.add(health_metrics)
    db.commit()
    db.refresh(health_metrics)

    return health_metrics

@router.delete("/delete_weight/{health_metrics_id}")
def delete_weight(
    health_metrics_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    health_metrics = db.get(HealthMetrics, health_metrics_id)
    if health_metrics is None:
        raise HTTPException(status_code=404, detail="Weight entry not found")

    telemetry = db.get(ClientTelemetry, health_metrics.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this weight entry")

    db.delete(health_metrics)
    db.commit()

    return {"message": "Weight entry deleted successfully"}


@router.get("/query/moods", response_model=list[CompletedSurvey])
def query_moods(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedSurvey).join(DailyMoodSurvey, DailyMoodSurvey.completed_survey_id == CompletedSurvey.id).join(ClientTelemetry, DailyMoodSurvey.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedSurvey.id.desc())

    moods = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return moods


@router.get("/query/workouts", response_model=list[CompletedWorkout])
def query_workouts(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedWorkout).join(ClientTelemetry, CompletedWorkout.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedWorkout.id.desc())

    workouts = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return workouts

class CompletedMealRow(BaseModel):
    """Enriched logged-meal row used by the dashboard list. Joins
    CompletedMealActivity → resolved Meal → its food breakdown so the
    frontend doesn't have to do N follow-up requests to render N meal cards.
    `calories` is computed live from MealFood/Food when available, else
    falls back to legacy MealIngredient.calories totals."""
    id: int
    client_prescribed_meal_id: Optional[int] = None
    on_demand_meal_id: Optional[int] = None
    meal_id: Optional[int] = None
    meal_name: Optional[str] = None
    meal_kind: Optional[str] = None
    calories: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    logged_at: Optional[datetime] = None


def _resolve_meal_for_activity(
    db: Session, activity: CompletedMealActivity
) -> Optional[Meal]:
    """A CompletedMealActivity references either a prescribed meal or an
    on-demand meal. Resolve to the underlying Meal row (or None if both
    pointers are null/dangling)."""
    if activity.on_demand_meal_id is not None:
        return db.get(Meal, activity.on_demand_meal_id)
    if activity.client_prescribed_meal_id is not None:
        prescribed = db.get(ClientPrescribedMeal, activity.client_prescribed_meal_id)
        if prescribed:
            return db.get(Meal, prescribed.meal_id)
    return None


def _meal_macros(db: Session, meal_id: int) -> dict:
    """Sum a meal's macros from MealFood (preferred) or MealIngredient
    (legacy seed-data fallback). Returns kcal/protein/carbs/fat."""
    food_rows = db.exec(
        select(MealFood, Food)
        .where(MealFood.meal_id == meal_id)
        .where(MealFood.food_id == Food.id)
    ).all()
    if food_rows:
        return {
            "calories": round(sum(f.calories_per_100g * mf.grams / 100.0 for mf, f in food_rows), 1),
            "protein_g": round(sum(f.protein_g_per_100g * mf.grams / 100.0 for mf, f in food_rows), 1),
            "carbs_g": round(sum(f.carbs_g_per_100g * mf.grams / 100.0 for mf, f in food_rows), 1),
            "fat_g": round(sum(f.fat_g_per_100g * mf.grams / 100.0 for mf, f in food_rows), 1),
        }
    legacy = db.exec(
        select(MealIngredient).where(MealIngredient.meal_id == meal_id)
    ).all()
    return {
        "calories": float(sum(i.calories or 0 for i in legacy)),
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
    }


@router.get("/query/meals", response_model=List[CompletedMealRow])
def query_meals(
    on_date: Optional[str] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    """Logged meals for the current client, newest-first, with the resolved
    meal name and computed macros baked in. Pass `on_date` (YYYY-MM-DD) to
    filter to a single day — used by the overlay's "Logged Today" section
    so it actually matches today, not the most-recent N entries across
    history."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    parsed_date = None
    if on_date:
        try:
            parsed_date = datetime.strptime(on_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "on_date must be YYYY-MM-DD")

    query = (
        select(CompletedMealActivity, ClientTelemetry)
        .join(ClientTelemetry, CompletedMealActivity.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
    )
    if parsed_date is not None:
        # ClientTelemetry.date is tz-aware UTC datetime; compare against the
        # whole-day window so timezone offsets don't drop entries logged
        # right around midnight.
        day_start = datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = datetime.combine(parsed_date, datetime.max.time(), tzinfo=timezone.utc)
        query = query.where(
            ClientTelemetry.date >= day_start,
            ClientTelemetry.date <= day_end,
        )
    query = query.order_by(CompletedMealActivity.id.desc())
    rows = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    out: List[CompletedMealRow] = []
    for activity, telemetry in rows:
        meal = _resolve_meal_for_activity(db, activity)
        if meal:
            macros = _meal_macros(db, meal.id)
        else:
            macros = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        out.append(CompletedMealRow(
            id=activity.id,
            client_prescribed_meal_id=activity.client_prescribed_meal_id,
            on_demand_meal_id=activity.on_demand_meal_id,
            meal_id=meal.id if meal else None,
            meal_name=meal.meal_name if meal else None,
            meal_kind=activity.meal_kind,
            logged_at=telemetry.date,
            **macros,
        ))
    return out


class UpdateMealLogPayload(BaseModel):
    """Editable fields on a logged meal. All optional — caller sends just the
    field they want to change. To "swap which meal was logged," replace either
    `client_prescribed_meal_id` or `on_demand_meal_id`. To re-tag the meal
    kind (breakfast/lunch/dinner/snack), set `meal_kind`."""
    meal_kind: Optional[str] = None
    client_prescribed_meal_id: Optional[int] = None
    on_demand_meal_id: Optional[int] = None


@router.patch("/meals/{activity_id}", response_model=CompletedMealRow)
def update_logged_meal(
    activity_id: int,
    payload: UpdateMealLogPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Edit a logged meal — typically just to retag the meal kind, but also
    supports swapping which Meal the log points at. Ownership is verified via
    the join through client_telemetry.client_id so a client can't edit another
    user's logs."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    activity = db.get(CompletedMealActivity, activity_id)
    if activity is None:
        raise HTTPException(404, "Logged meal not found.")
    telemetry = db.get(ClientTelemetry, activity.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(403, "Not authorized to edit this log.")

    # Apply only fields that were sent (None = leave unchanged for meal_kind;
    # for the meal-id swap, sending None explicitly clears the other slot
    # so the resulting row never points at both).
    if payload.meal_kind is not None:
        activity.meal_kind = payload.meal_kind
    if payload.client_prescribed_meal_id is not None or payload.on_demand_meal_id is not None:
        activity.client_prescribed_meal_id = payload.client_prescribed_meal_id
        activity.on_demand_meal_id = payload.on_demand_meal_id
    db.add(activity)
    db.commit()
    db.refresh(activity)

    meal = _resolve_meal_for_activity(db, activity)
    macros = _meal_macros(db, meal.id) if meal else {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    return CompletedMealRow(
        id=activity.id,
        client_prescribed_meal_id=activity.client_prescribed_meal_id,
        on_demand_meal_id=activity.on_demand_meal_id,
        meal_id=meal.id if meal else None,
        meal_name=meal.meal_name if meal else None,
        meal_kind=activity.meal_kind,
        logged_at=telemetry.date,
        **macros,
    )


@router.delete("/meals/{activity_id}")
def delete_logged_meal(
    activity_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Delete a meal log. Ownership verified via client_telemetry.client_id.
    The DailyMealSurvey row for that day is left as-is (its
    completed_meal_activity_id may now point at a deleted row, which is fine —
    the calories aggregate ignores rows that don't resolve)."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    activity = db.get(CompletedMealActivity, activity_id)
    if activity is None:
        raise HTTPException(404, "Logged meal not found.")
    telemetry = db.get(ClientTelemetry, activity.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(403, "Not authorized to delete this log.")

    db.delete(activity)
    db.commit()
    return {"success": True, "message": "Meal log deleted."}


class CaloriesTodayResponse(BaseModel):
    calories_consumed: float
    protein_g: float
    carbs_g: float
    fat_g: float
    meal_count: int


@router.get("/calories_today", response_model=CaloriesTodayResponse)
def calories_today(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Sum today's logged-meal calories+macros for the calories card on the
    client dashboard. 'Today' is by client_telemetry.date in UTC; matches the
    same bucketing the survey routes use, so a meal logged at 23:30 UTC
    counts toward that day's total even if local time has rolled over."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    today_date = datetime.utcnow().date()
    rows = db.exec(
        select(CompletedMealActivity, ClientTelemetry)
        .join(ClientTelemetry, CompletedMealActivity.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
    ).all()

    total = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    count = 0
    for activity, telemetry in rows:
        # Compare bare dates so timezone-aware vs naive doesn't trip us.
        tel_date = telemetry.date.date() if hasattr(telemetry.date, "date") else telemetry.date
        if tel_date != today_date:
            continue
        meal = _resolve_meal_for_activity(db, activity)
        if not meal:
            continue
        m = _meal_macros(db, meal.id)
        total["calories"] += m["calories"]
        total["protein_g"] += m["protein_g"]
        total["carbs_g"] += m["carbs_g"]
        total["fat_g"] += m["fat_g"]
        count += 1

    return CaloriesTodayResponse(
        calories_consumed=round(total["calories"], 1),
        protein_g=round(total["protein_g"], 1),
        carbs_g=round(total["carbs_g"], 1),
        fat_g=round(total["fat_g"], 1),
        meal_count=count,
    )


class RandomAppreciationResponse(BaseModel):
    """One random gratitude entry pulled from the client's mood-survey
    history. `todays_appreciation` matches the field name the frontend reads
    from. Returns null fields when the client has nothing logged."""
    todays_appreciation: Optional[str] = None
    logged_on: Optional[datetime] = None


@router.get("/random_appreciation", response_model=RandomAppreciationResponse)
def random_appreciation(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Pick a random non-empty `todays_appreciation` the client has ever
    written in a daily mood survey. The dashboard's AppreciationCard hits
    this on mount to surface a past gratitude entry as a "something I'm
    grateful for" reminder."""
    if acc.client_id is None:
        raise HTTPException(404, "Client profile not found")

    # Walk the chain: CompletedSurvey ← DailyMoodSurvey ← ClientTelemetry
    # so we can scope to the current client. Filtering todays_appreciation
    # to non-empty in SQL avoids loading rows we'd just discard.
    rows = db.exec(
        select(CompletedSurvey)
        .join(DailyMoodSurvey, DailyMoodSurvey.completed_survey_id == CompletedSurvey.id)
        .join(ClientTelemetry, ClientTelemetry.id == DailyMoodSurvey.client_telemetry_id)
        .where(
            ClientTelemetry.client_id == acc.client_id,
            CompletedSurvey.todays_appreciation.isnot(None),
            CompletedSurvey.todays_appreciation != "",
        )
    ).all()

    if not rows:
        return RandomAppreciationResponse()

    import random
    pick = random.choice(rows)
    return RandomAppreciationResponse(
        todays_appreciation=pick.todays_appreciation,
        logged_on=pick.last_updated,
    )
