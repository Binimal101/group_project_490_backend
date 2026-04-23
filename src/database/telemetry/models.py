from datetime import datetime
from typing import Optional

from pydantic import field_validator
from sqlmodel import Field

from src.database.base import SQLModelLU


class ClientTelemetry(SQLModelLU, table=True):
    __tablename__ = "client_telemetry"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", ondelete="CASCADE")
    date: datetime


class StepCount(SQLModelLU, table=True):
    __tablename__ = "step_count"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")
    step_count: int


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
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class HealthMetrics(SQLModelLU, table=True):
    __tablename__ = "health_metrics"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    weight: int
    progress_pic_url: Optional[str] = None
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")

    @field_validator("weight")
    def weight_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Weight must be a positive integer")
        return v

class DailyWorkoutSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_workout_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_workout_id: Optional[int] = Field(default=None, foreign_key="completed_workout.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class DailyBodyMetricsSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_body_metrics_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_health_metrics_id: Optional[int] = Field(default=None, foreign_key="health_metrics.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class DailyStepsSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_steps_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    step_count_id: Optional[int] = Field(default=None, foreign_key="step_count.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class DailyMealSurvey(SQLModelLU, table=True):
    __tablename__ = "daily_meal_survey"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    is_seen: bool = False
    is_started: bool = False
    is_finished: bool = False
    completed_meal_activity_id: Optional[int] = Field(default=None, foreign_key="completed_meal_activity.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class CompletedMealActivity(SQLModelLU, table=True):
    __tablename__ = "completed_meal_activity"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    client_prescribed_meal_id: Optional[int] = Field(default=None, foreign_key="client_prescribed_meal.id", ondelete="CASCADE")
    on_demand_meal_id: Optional[int] = Field(default=None, foreign_key="meal.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")


class CompletedWorkout(SQLModelLU, table=True):
    __tablename__ = "completed_workout"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    workout_plan_activity_id: Optional[int] = Field(default=None, foreign_key="workout_plan_activity.id")
    workout_activity_id: Optional[int] = Field(default=None, foreign_key="workout_activity.id")
    completed_workout_details_id: Optional[int] = Field(default=None, foreign_key="completed_workout_activity.id")
    client_telemetry_id: int = Field(foreign_key="client_telemetry.id", ondelete="CASCADE")