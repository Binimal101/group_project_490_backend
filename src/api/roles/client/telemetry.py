from src.api.roles.client.fitness import (
    APIRouter,
    PaginationParams,
    Session,
    TELEMETRY_STEPS,
    _get_or_create_daily_telemetry_for_type,
    datetime,
    select,
)
from sqlalchemy import func as sqlfunc
from src.database.telemetry.models import ClientTelemetry, CompletedMealActivity, HealthMetrics, StepCount, CompletedSurvey, DailyMoodSurvey, CompletedWorkout, CompletedWorkoutActivity
from src.api.roles.client.domain import StepCountUpdateInput, StepCountUpdateOutput, WeightUpdateInput
from src.database.session import get_session
from src.database.account.models import Account
from fastapi import Depends, HTTPException
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

@router.get("/query/random_appreciation")
def query_random_appreciation(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Return a single random todays_appreciation entry from this client's mood history."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = (
        select(CompletedSurvey)
        .join(DailyMoodSurvey, DailyMoodSurvey.completed_survey_id == CompletedSurvey.id)
        .join(ClientTelemetry, DailyMoodSurvey.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
        .where(CompletedSurvey.todays_appreciation.isnot(None))
        .where(CompletedSurvey.todays_appreciation != "")
        .order_by(sqlfunc.random())
        .limit(1)
    )
    entry = db.exec(query).first()
    return {"todays_appreciation": entry.todays_appreciation if entry else None}


@router.get("/query/workouts_enriched")
def query_workouts_enriched(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Return completed workouts joined with their actual metrics and activity names."""
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    from src.database.workouts_and_activities.models import WorkoutPlanActivity, WorkoutActivity, Workout

    query = (
        select(CompletedWorkout)
        .join(ClientTelemetry, CompletedWorkout.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
        .order_by(CompletedWorkout.id.desc())
    )
    workouts = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    result = []
    for cw in workouts:
        details = db.get(CompletedWorkoutActivity, cw.completed_workout_details_id) if cw.completed_workout_details_id else None
        activity_name = None
        if cw.workout_plan_activity_id:
            wpa = db.get(WorkoutPlanActivity, cw.workout_plan_activity_id)
            if wpa:
                wa = db.get(WorkoutActivity, wpa.workout_activity_id)
                if wa:
                    wo = db.get(Workout, wa.workout_id)
                    if wo:
                        activity_name = wo.name
        elif cw.workout_activity_id:
            wa = db.get(WorkoutActivity, cw.workout_activity_id)
            if wa:
                wo = db.get(Workout, wa.workout_id)
                if wo:
                    activity_name = wo.name
        result.append({
            "id": cw.id,
            "workout_plan_activity_id": cw.workout_plan_activity_id,
            "workout_activity_id": cw.workout_activity_id,
            "activity_name": activity_name,
            "completed_reps": details.completed_reps if details else None,
            "completed_sets": details.completed_sets if details else None,
            "completed_duration": details.completed_duration if details else None,
            "estimated_calories": details.estimated_calories if details else None,
            "last_updated": cw.last_updated.isoformat() if cw.last_updated else None,
        })
    return result


@router.get("/query/meals", response_model=list[CompletedMealActivity])
def query_meals(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedMealActivity).join(ClientTelemetry, CompletedMealActivity.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedMealActivity.id.desc())

    meals = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return meals


@router.get("/calories_today")
def get_calories_today(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Aggregate today's calorie totals for the authenticated client.

    Returns: {
        "calories_consumed": int,   # sum of meal-ingredient calories for today's logged meals
        "calories_burned":   int,   # sum of completed_workout_activity.estimated_calories for today's workouts
        "net_calories":      int,   # consumed - burned (the delta toward the daily goal; can be negative)
        "calories_goal":     int,   # account.daily_calorie_budget (defaults to 2000)
        "meal_count":        int,
        "workout_count":     int,
    }

    Today is the local date in UTC. All sums coerce nulls to 0.
    """
    from sqlalchemy import func as sqlafunc
    from src.database.meal.models import ClientPrescribedMeal, MealIngredient

    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    today_utc = datetime.utcnow().date()

    # ── BURNED ───────────────────────────────────────────────────────────────
    # Calories live on CompletedWorkoutActivity.estimated_calories.
    # Get them via CompletedWorkout.completed_workout_details_id, scoped by
    # parent ClientTelemetry being today and belonging to this client.
    burned_rows = db.exec(
        select(CompletedWorkoutActivity.estimated_calories)
        .join(
            CompletedWorkout,
            CompletedWorkout.completed_workout_details_id == CompletedWorkoutActivity.id,
        )
        .join(
            ClientTelemetry,
            ClientTelemetry.id == CompletedWorkout.client_telemetry_id,
        )
        .where(
            ClientTelemetry.client_id == acc.client_id,
            sqlafunc.date(ClientTelemetry.date) == today_utc,
        )
    ).all()
    calories_burned = sum(int(c or 0) for c in burned_rows)
    workout_count = len(burned_rows)

    # ── CONSUMED ─────────────────────────────────────────────────────────────
    # CompletedMealActivity references either a ClientPrescribedMeal (which
    # points at a Meal) or an on-demand Meal directly. Meal calories =
    # SUM(MealIngredient.calories WHERE meal_id = X).
    meal_links = db.exec(
        select(
            CompletedMealActivity.client_prescribed_meal_id,
            CompletedMealActivity.on_demand_meal_id,
        )
        .join(
            ClientTelemetry,
            ClientTelemetry.id == CompletedMealActivity.client_telemetry_id,
        )
        .where(
            ClientTelemetry.client_id == acc.client_id,
            sqlafunc.date(ClientTelemetry.date) == today_utc,
        )
    ).all()

    meal_ids: list[int] = []
    for cpm_id, odm_id in meal_links:
        if cpm_id is not None:
            cpm = db.get(ClientPrescribedMeal, cpm_id)
            if cpm and cpm.meal_id is not None:
                meal_ids.append(cpm.meal_id)
        elif odm_id is not None:
            meal_ids.append(odm_id)

    calories_consumed = 0
    if meal_ids:
        ingredient_total = db.exec(
            select(sqlafunc.coalesce(sqlafunc.sum(MealIngredient.calories), 0))
            .where(MealIngredient.meal_id.in_(meal_ids))  # type: ignore
        ).one()
        # one() can return scalar or 1-tuple depending on driver; coerce both
        if isinstance(ingredient_total, tuple):
            ingredient_total = ingredient_total[0] if ingredient_total else 0
        calories_consumed = int(ingredient_total or 0)

    goal = int(acc.daily_calorie_budget or 2000)

    return {
        "calories_consumed": calories_consumed,
        "calories_burned": calories_burned,
        "net_calories": calories_consumed - calories_burned,
        "calories_goal": goal,
        "meal_count": len(meal_links),
        "workout_count": workout_count,
    }
