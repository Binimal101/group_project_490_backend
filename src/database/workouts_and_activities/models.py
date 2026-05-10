from datetime import datetime, time
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import model_validator
from sqlmodel import Field

from src.database.base import SQLModelLU


class PlanLibrarySource(str, Enum):
    SELF_AUTHORED = "self_authored"
    PRESCRIBED = "prescribed"
    PUBLIC_SAVE = "public_save"


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
    is_hidden: bool = Field(default=False)


class WorkoutActivity(SQLModelLU, table=True):
    __tablename__ = "workout_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    workout_id: int = Field(foreign_key="workout.id")
    intensity_measure: Optional[str] = None
    intensity_value: Optional[int] = None
    estimated_calories_per_unit_frequency: Decimal = Field(max_digits=10, decimal_places=6)
    is_hidden: bool = Field(default=False)


class WorkoutPlan(SQLModelLU, table=True):
    __tablename__ = "workout_plan"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    strata_name: str  # this is the name of the grouping for workout_plan_activities
    is_public: bool = Field(default=False)
    is_hidden: bool = Field(default=False)
    created_by_account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    # PRD v2: copy-to-own model. is_forked plans were created via the
    # client-only /plan/{id}/copy endpoint. They cannot be made public and
    # cannot be prescribed (prescribe_plan rejects forks).
    is_forked: bool = Field(default=False)
    forked_from_plan_id: Optional[int] = Field(default=None, foreign_key="workout_plan.id")


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
    # PRD v2: in-place edits replace fork-on-edit. When the owner removes an
    # activity that has CompletedWorkout rows referencing it, we soft-delete
    # via this flag instead of hard-deleting (preserves caloric attribution).
    is_hidden: bool = Field(default=False)

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


class PlanLibraryEntry(SQLModelLU, table=True):
    """PRD v2: junction between Account and WorkoutPlan. The single source of
    truth for "who has this plan in their library and how they got it."

    Replaces the v1 heuristic of inferring ownership from
    `WorkoutPlan.created_by_account_id`. A plan can appear in multiple library
    entries (one per saver/recipient) without ever being mutated.
    """
    __tablename__ = "plan_library_entry"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
    workout_plan_id: int = Field(foreign_key="workout_plan.id", index=True)
    source: PlanLibrarySource
    # When source = "prescribed", this records which coach prescribed it.
    # Survives termination so provenance is preserved.
    source_coach_account_id: Optional[int] = Field(default=None, foreign_key="account.id")
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    # Set by terminate_relationship for prescribed entries. PRD v2 default is
    # to leave the plan link live (coach edits keep flowing) — revoked_at is
    # an audit / UI-badge marker, not a hard cut.
    revoked_at: Optional[datetime] = None