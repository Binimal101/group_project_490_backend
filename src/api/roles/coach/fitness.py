from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_coach_account
from src.database.workouts_and_activities.models import (
    Workout, WorkoutEquiptment, WorkoutActivity, WorkoutType, Equiptment
)
from src.api.roles.coach.domain import (
    CreateWorkoutInput, CreateWorkoutResponse,
    CreateActivityInput, CreateActivityResponse
)

router = APIRouter(prefix="/roles/coach/fitness", tags=["coach", "fitness"])

@router.post("/create/workout", response_model=CreateWorkoutResponse)
def create_workout(
    payload: CreateWorkoutInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_coach_account)
):
    try:
        workout_type = WorkoutType(payload.workout_type)
    except ValueError:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid workout type. Must be one of {[t.value for t in WorkoutType]}"
        )

    workout = Workout(
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
        workout_type=workout_type
    )
    db.add(workout)
    db.flush()

    for eq_input in payload.equipment:
        if eq_input.equiptment_id is not None:
            eq = db.get(Equiptment, eq_input.equiptment_id)
            if not eq:
                raise HTTPException(status_code=404, detail=f"Equipment with id {eq_input.equiptment_id} not found")
        elif eq_input.name:
            eq = db.exec(select(Equiptment).where(Equiptment.name == eq_input.name)).first()
            if not eq:
                eq = Equiptment(name=eq_input.name, description=eq_input.description)
                db.add(eq)
                db.flush()
        else:
            raise HTTPException(status_code=400, detail="Must provide equiptment_id or name to link equipment")

        workout_eq = WorkoutEquiptment(
            equiptment_id=eq.id,
            workout_id=workout.id,
            is_required=eq_input.is_required,
            is_recommended=eq_input.is_recommended
        )
        db.add(workout_eq)
    
    db.commit()
    return CreateWorkoutResponse(workout_id=workout.id)

@router.post("/create/activity", response_model=CreateActivityResponse)
def create_activity(
    payload: CreateActivityInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_coach_account)
):
    if not db.get(Workout, payload.workout_id):
        raise HTTPException(status_code=404, detail=f"Workout with id {payload.workout_id} not found")

    activity = WorkoutActivity(
        workout_id=payload.workout_id,
        intensity_measure=payload.intensity_measure,
        intensity_value=payload.intensity_value,
        estimated_calories_per_unit_frequency=payload.estimated_calories_per_unit_frequency # type: ignore
    )
    db.add(activity)
    db.commit()

    return CreateActivityResponse(workout_activity_id=activity.id) # type: ignore
