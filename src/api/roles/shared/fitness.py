from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from typing import Optional

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_active_account, PaginationParams
from src.database.workouts_and_activities.models import WorkoutPlan, WorkoutPlanActivity, WorkoutActivity
from src.api.roles.shared.domain import CreateWorkoutPlanInput, CreateWorkoutPlanResponse
from src.database.workouts_and_activities.models import Workout, WorkoutType, WorkoutEquiptment, Equiptment

router = APIRouter(prefix="/roles/shared/fitness", tags=["shared", "fitness"])


def _enrich_plan(db: Session, plan: WorkoutPlan) -> dict:
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
            "workout_type": workout.workout_type if workout else None,
            "intensity_measure": activity.intensity_measure if activity else None,
            "intensity_value": activity.intensity_value if activity else None,
            "planned_reps": pa.planned_reps,
            "planned_sets": pa.planned_sets,
            "planned_duration": pa.planned_duration,
            "estimated_calories": float(pa.estimated_calories) if pa.estimated_calories is not None else None,
        })
    return {
        "id": plan.id,
        "strata_name": plan.strata_name,
        "is_public": plan.is_public,
        "is_hidden": plan.is_hidden,
        "created_by_account_id": plan.created_by_account_id,
        "activities": enriched_activities,
    }


def _plan_has_telemetry(db: Session, plan_id: int) -> bool:
    """Return True if any completed_workout entry references an activity in this plan."""
    from src.database.telemetry.models import CompletedWorkout
    activity_ids = [
        pa.id for pa in db.exec(
            select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
        ).all()
        if pa.id is not None
    ]
    if not activity_ids:
        return False
    hit = db.exec(
        select(CompletedWorkout).where(CompletedWorkout.workout_plan_activity_id.in_(activity_ids))  # type: ignore
    ).first()
    return hit is not None


def _fork_plan(db: Session, plan: WorkoutPlan, acc: Account, exclude_activity_id: Optional[int] = None) -> WorkoutPlan:
    """Clone plan + its activities into a new version. Hide the old plan.

    exclude_activity_id: if set, that workout_plan_activity row is not copied
                         (used by remove-activity to drop it in the new version).
    """
    new_plan = WorkoutPlan(
        strata_name=plan.strata_name,
        is_public=plan.is_public,
        is_hidden=False,
        created_by_account_id=plan.created_by_account_id,
    )
    db.add(new_plan)
    db.flush()

    old_activities = db.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan.id)
    ).all()
    for old_pa in old_activities:
        if exclude_activity_id is not None and old_pa.id == exclude_activity_id:
            continue
        db.add(WorkoutPlanActivity(
            workout_plan_id=new_plan.id,
            workout_activity_id=old_pa.workout_activity_id,
            estimated_calories=old_pa.estimated_calories,
            modified_by_account_id=acc.id,
            planned_duration=old_pa.planned_duration,
            planned_reps=old_pa.planned_reps,
            planned_sets=old_pa.planned_sets,
        ))

    plan.is_hidden = True
    db.add(plan)
    return new_plan


@router.post("/plan", response_model=CreateWorkoutPlanResponse)
def create_workout_plan(
    payload: CreateWorkoutPlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    is_coach = acc.coach_id is not None
    is_public = payload.is_public and is_coach

    plan = WorkoutPlan(
        strata_name=payload.strata_name,
        is_public=is_public,
        is_hidden=False,
        created_by_account_id=acc.id,
    )
    db.add(plan)
    db.flush()

    for act_input in payload.activities:
        activity = db.get(WorkoutActivity, act_input.workout_activity_id)
        if not activity:
            raise HTTPException(status_code=404, detail=f"WorkoutActivity {act_input.workout_activity_id} not found")

        frequency = act_input.planned_duration or (act_input.planned_reps * act_input.planned_sets) or 0  # type: ignore
        estimated_calories = activity.estimated_calories_per_unit_frequency * frequency

        db.add(WorkoutPlanActivity(
            workout_plan_id=plan.id,  # type: ignore
            workout_activity_id=act_input.workout_activity_id,
            estimated_calories=estimated_calories,
            modified_by_account_id=acc.id,  # type: ignore
            planned_duration=act_input.planned_duration,
            planned_reps=act_input.planned_reps,
            planned_sets=act_input.planned_sets,
        ))

    db.commit()
    return CreateWorkoutPlanResponse(workout_plan_id=plan.id)  # type: ignore


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
    public_only: bool = False,
    mine_only: bool = False,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List visible (non-hidden) workout plans. public_only=true for Browse Plans;
    mine_only=true for My Plans (plans owned by the current account).
    Hidden (superseded) plan versions are never returned.
    """
    query = select(WorkoutPlan).where(WorkoutPlan.is_hidden == False)  # type: ignore
    if text:
        query = query.where(WorkoutPlan.strata_name.contains(text))  # type: ignore
    if public_only:
        query = query.where(WorkoutPlan.is_public == True)  # type: ignore
    if mine_only:
        query = query.where(WorkoutPlan.created_by_account_id == acc.id)  # type: ignore

    plans = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return [_enrich_plan(db, plan) for plan in plans]


# ── Plan modification endpoints (owner only, VCS-backed) ─────────────────────


class RenamePlanInput(BaseModel):
    strata_name: str


class AddPlanActivityInput(BaseModel):
    workout_activity_id: int
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None


def _get_owned_plan(plan_id: int, db: Session, acc: Account) -> WorkoutPlan:
    plan = db.get(WorkoutPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    if plan.created_by_account_id != acc.id:
        raise HTTPException(status_code=403, detail="You do not own this plan")
    if plan.is_hidden:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    return plan


@router.patch("/plan/{plan_id}")
def rename_workout_plan(
    plan_id: int,
    payload: RenamePlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    old_plan = _get_owned_plan(plan_id, db, acc)
    new_plan = _fork_plan(db, old_plan, acc)
    new_plan.strata_name = payload.strata_name.strip()
    db.add(new_plan)
    db.commit()
    db.refresh(new_plan)
    return _enrich_plan(db, new_plan)


@router.delete("/plan/{plan_id}")
def delete_workout_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    plan = _get_owned_plan(plan_id, db, acc)

    if _plan_has_telemetry(db, plan_id):
        raise HTTPException(
            status_code=409,
            detail="This plan has logged workout data and cannot be deleted. It has been archived instead.",
        )

    activities = db.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
    ).all()
    for a in activities:
        db.delete(a)
    db.flush()  # ensure activity rows are gone before the plan row is deleted
    db.delete(plan)
    db.commit()
    return {"deleted": plan_id}


@router.post("/plan/{plan_id}/activity")
def add_plan_activity(
    plan_id: int,
    payload: AddPlanActivityInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    old_plan = _get_owned_plan(plan_id, db, acc)
    activity = db.get(WorkoutActivity, payload.workout_activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail=f"WorkoutActivity {payload.workout_activity_id} not found")

    new_plan = _fork_plan(db, old_plan, acc)

    frequency = payload.planned_duration or (
        (payload.planned_reps or 0) * (payload.planned_sets or 0)
    )
    estimated_calories = activity.estimated_calories_per_unit_frequency * frequency

    db.add(WorkoutPlanActivity(
        workout_plan_id=new_plan.id,
        workout_activity_id=payload.workout_activity_id,
        estimated_calories=estimated_calories,
        modified_by_account_id=acc.id,
        planned_duration=payload.planned_duration,
        planned_reps=payload.planned_reps,
        planned_sets=payload.planned_sets,
    ))
    db.commit()
    db.refresh(new_plan)
    return _enrich_plan(db, new_plan)


@router.delete("/plan/{plan_id}/activity/{activity_id}")
def remove_plan_activity(
    plan_id: int,
    activity_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    old_plan = _get_owned_plan(plan_id, db, acc)
    pa = db.get(WorkoutPlanActivity, activity_id)
    if pa is None or pa.workout_plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Activity not found in this plan")

    new_plan = _fork_plan(db, old_plan, acc, exclude_activity_id=activity_id)
    db.commit()
    db.refresh(new_plan)
    return _enrich_plan(db, new_plan)
