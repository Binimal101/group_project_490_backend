from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel

class WorkoutPlanActivityInput(BaseModel):
    workout_activity_id: int
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None

class CreateWorkoutPlanInput(BaseModel):
    strata_name: str
    activities: List[WorkoutPlanActivityInput]

class CreateWorkoutPlanResponse(BaseModel):
    workout_plan_id: int
