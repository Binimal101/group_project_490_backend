from datetime import datetime, timezone
from typing import Optional

from pydantic import field_validator
from sqlmodel import Field
from sqlalchemy import Column, DateTime

from src.database.base import SQLModelLU


class ClientTelemetry(SQLModelLU, table=True):
    __tablename__ = "client_telemetry"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    # Both client dashboards and coach dashboards filter telemetry by client_id
    # constantly (calories today, weekly graphs, etc) — this column is the most
    # frequent WHERE-target after primary keys.
    client_id: int = Field(foreign_key="client.id", ondelete="CASCADE", index=True)
    telemetry_type: Optional[str] = Field(default=None, index=True)
    date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class StepCount(SQLModelLU, table=True):
    __tablename__ = "step_count"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )
    step_count: int

    @field_validator("step_count")
    def step_count_in_realistic_range(cls, v):
        # 70k caps a marathon-runner extreme; anything higher is almost
        # certainly a sensor glitch or fat-fingered manual entry. 0 keeps
        # the model symmetric with the rest-day case.
        if v < 0:
            raise ValueError("step_count must be non-negative")
        if v > 70000:
            raise ValueError("step_count exceeds realistic maximum (70000)")
        return v


class CompletedWorkoutActivity(SQLModelLU, table=True):
    __tablename__ = "completed_workout_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    completed_reps: Optional[int] = None
    completed_sets: Optional[int] = None
    completed_duration: Optional[int] = None
    estimated_calories: Optional[int] = None


class CompletedSurvey(SQLModelLU, table=True):
    __tablename__ = "completed_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    happiness_meter: Optional[int] = None
    alertness: Optional[int] = None
    healthiness: Optional[int] = None
    todays_goals: Optional[str] = None
    todays_appreciation: Optional[str] = None


class DailyMoodSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_mood_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_survey_id: Optional[int] = Field(default=None, foreign_key="completed_survey.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )


class HealthMetrics(SQLModelLU, table=True):
    __tablename__ = "health_metrics"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    weight: int
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )

    @field_validator("weight")
    def weight_in_realistic_range(cls, v):
        # 600 lbs caps the upper end of the human range with margin; 1 is
        # the lower bound (0/negative is a sensor glitch). Anything above
        # 600 is almost certainly a unit-of-measure mix-up.
        if v <= 0:
            raise ValueError("Weight must be a positive integer")
        if v > 600:
            raise ValueError("Weight exceeds realistic maximum (600 lbs)")
        return v

class DailyWorkoutSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_workout_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_workout_id: Optional[int] = Field(default=None, foreign_key="completed_workout.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )


class DailyBodyMetricsSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_body_metrics_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_health_metrics_id: Optional[int] = Field(default=None, foreign_key="health_metrics.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )


class DailyStepsSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_steps_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    step_count_id: Optional[int] = Field(default=None, foreign_key="step_count.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )


class DailyMealSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_meal_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_meal_activity_id: Optional[int] = Field(default=None, foreign_key="completed_meal_activity.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )


class CompletedMealActivity(SQLModelLU, table=True):
    __tablename__ = "completed_meal_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_prescribed_meal_id: Optional[int] = Field(default=None, foreign_key="client_prescribed_meal.id", ondelete="CASCADE")
    on_demand_meal_id: Optional[int] = Field(default=None, foreign_key="meal.id")
    # Multiple meals per day are allowed (breakfast + lunch + dinner all share
    # the same client_telemetry row), so client_telemetry_id is NOT unique.
    # Indexed because the meals-today endpoint joins through this on every
    # client dashboard load.
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        index=True,
    )
    # Tag each log with its kind ("breakfast"/"lunch"/"dinner"/"snack") so the
    # client dashboard can group meals and the coach can review the plan
    # adherence per slot.
    meal_kind: Optional[str] = Field(default=None)


class CompletedWorkout(SQLModelLU, table=True):
    __tablename__ = "completed_workout"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    # Indexed because telemetry-delete and the VCS plan-delete guard scan by
    # workout_plan_activity_id, and the plan PATCH path queries by it too.
    workout_plan_activity_id: Optional[int] = Field(default=None, foreign_key="workout_plan_activity.id", index=True)
    workout_activity_id: Optional[int] = Field(default=None, foreign_key="workout_activity.id", index=True)
    completed_workout_details_id: Optional[int] = Field(default=None, foreign_key="completed_workout_activity.id")
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        index=True,
    )


class DailyProgressPicture(SQLModelLU, table=True):
    """One progress picture per client per day.

    Each picture row has its own client_telemetry row. Re-uploading on the same
    day updates this row instead of sharing telemetry with another metric type.
    """
    __tablename__ = "daily_progress_picture"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_telemetry_id: int = Field(
        foreign_key="client_telemetry.id",
        ondelete="CASCADE",
        sa_column_kwargs={"unique": True},
    )
    url: str
