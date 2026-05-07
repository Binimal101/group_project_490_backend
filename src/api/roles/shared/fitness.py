from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from typing import Optional

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_active_account, PaginationParams
from src.database.workouts_and_activities.models import WorkoutPlan, WorkoutPlanActivity, WorkoutActivity
from src.api.roles.shared.domain import CreateWorkoutPlanInput, CreateWorkoutPlanResponse
from src.database.workouts_and_activities.models import Workout, WorkoutType, WorkoutEquiptment, Equiptment

router = APIRouter(prefix="/roles/shared/fitness", tags=["shared", "fitness"])

@router.post("/plan", response_model=CreateWorkoutPlanResponse)
def create_workout_plan(
    payload: CreateWorkoutPlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    # Create the workout plan
    plan = WorkoutPlan(strata_name=payload.strata_name)
    db.add(plan)
    db.flush()

    for act_input in payload.activities:
        activity = db.get(WorkoutActivity, act_input.workout_activity_id)
        if not activity:
            raise HTTPException(status_code=404, detail=f"WorkoutActivity {act_input.workout_activity_id} not found")

        # Estimate calories based on frequency metric
        frequency = act_input.planned_duration or (act_input.planned_reps * act_input.planned_sets) or 0 # type: ignore
        estimated_calories = activity.estimated_calories_per_unit_frequency * frequency

        plan_activity = WorkoutPlanActivity(
            workout_plan_id=plan.id, # type: ignore
            workout_activity_id=act_input.workout_activity_id,
            estimated_calories=estimated_calories,
            modified_by_account_id=acc.id, # type: ignore
            planned_duration=act_input.planned_duration,
            planned_reps=act_input.planned_reps,
            planned_sets=act_input.planned_sets
        )
        db.add(plan_activity)

    db.commit()
    return CreateWorkoutPlanResponse(workout_plan_id=plan.id) # type: ignore

@router.get("/query/activity")
def query_workout_activity(
    workout_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(WorkoutActivity).where(WorkoutActivity.workout_id == workout_id)
    activities = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return activities

@router.get("/query/workout")
def query_workout(
    text: Optional[str] = None,
    workout_type: Optional[WorkoutType] = None,
    equiptment_id: Optional[int] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(Workout)
    if equiptment_id is not None:
        query = query.join(WorkoutEquiptment).where(WorkoutEquiptment.equiptment_id == equiptment_id)
        
    if text:
        query = query.where(
            (Workout.name.contains(text)) |
            (Workout.description.contains(text))
        )
    if workout_type:
        query = query.where(Workout.workout_type == workout_type)

    workouts = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return workouts

@router.get("/query/supported_equiptment")
def query_supported_equiptment(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(Equiptment)
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get("/query/workout_plan")
def query_workout_plans(
    text: Optional[str] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List workout plans, optionally filtered by strata_name. Each plan is enriched
    with its activities, including the parent workout name and intensity details.
    """
    query = select(WorkoutPlan)
    if text:
        query = query.where(WorkoutPlan.strata_name.contains(text))  # type: ignore
    plans = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    results = []
    for plan in plans:
        plan_activities = db.exec(
            select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan.id)
        ).all()
        enriched_activities = []
        for pa in plan_activities:
            activity = db.get(WorkoutActivity, pa.workout_activity_id)
            workout = db.get(Workout, activity.workout_id) if activity else None
            enriched_activities.append({
                "id": pa.id,
                "workout_activity_id": pa.workout_activity_id,
                "workout_id": activity.workout_id if activity else None,
                "workout_name": workout.name if workout else None,
                "intensity_measure": activity.intensity_measure if activity else None,
                "intensity_value": activity.intensity_value if activity else None,
                "planned_reps": pa.planned_reps,
                "planned_sets": pa.planned_sets,
                "planned_duration": pa.planned_duration,
                "estimated_calories": float(pa.estimated_calories) if pa.estimated_calories is not None else None,
            })
        results.append({
            "id": plan.id,
            "strata_name": plan.strata_name,
            "activities": enriched_activities,
        })
    return results
