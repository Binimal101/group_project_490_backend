from datetime import time
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import model_validator
from sqlmodel import Field

from src.database.base import SQLModelLU


class WorkoutType(str, Enum):
    REPETITION_BASED = "rep"
    DURATION_BASED = "duration"


class Equiptment(SQLModelLU, table=True):
    __tablename__ = "equiptment"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None


class WorkoutEquiptment(SQLModelLU, table=True):
    __tablename__ = "workout_equiptment"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    equiptment_id: int = Field(foreign_key="equiptment.id")
    workout_id: int = Field(foreign_key="workout.id")
    is_required: bool = Field(default=True)
    is_recommended: bool = Field(default=True)


class Workout(SQLModelLU, table=True):
    __tablename__ = "workout"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str
    instructions: str
    workout_type: WorkoutType


class WorkoutActivity(SQLModelLU, table=True):
    __tablename__ = "workout_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    workout_id: int = Field(foreign_key="workout.id")
    intensity_measure: Optional[str] = None
    intensity_value: Optional[int] = None
    estimated_calories_per_unit_frequency: Decimal = Field(max_digits=10, decimal_places=6)


class WorkoutPlan(SQLModelLU, table=True):
    __tablename__ = "workout_plan"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    strata_name: str # this is the name of the grouping for workout_plan_activities


class WorkoutPlanActivity(SQLModelLU, table=True):
    __tablename__ = "workout_plan_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    workout_plan_id: int = Field(foreign_key="workout_plan.id")
    workout_activity_id: int = Field(foreign_key="workout_activity.id")
    estimated_calories: Decimal = Field(max_digits=8, decimal_places=2)
    modified_by_account_id: int = Field(foreign_key="account.id", index=True)
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def validate_one_time_metric(cls, values):
        duration = values.get("planned_duration")
        reps = values.get("planned_reps")
        sets = values.get("planned_sets")

        
        if reps and sets and not duration:
            return values
        if duration and not (reps or sets):
            return values
        
        raise ValueError("WorkoutPlanActivity must have either planned_duration or both planned_reps and planned_sets, but not both.")