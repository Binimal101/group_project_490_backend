from enum import Enum
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
from src.database.base import SQLModelLU

from pydantic import field_validator, model_validator
from fastapi import HTTPException

class Client(SQLModelLU, table=True):
  __tablename__ = "client"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  payment_information_id : Optional[int] = Field(default=None, foreign_key="payment_information.id")
  client_availability_id : Optional[int] = Field(default=None, foreign_key="client_availability.id")
  # Daily targets the dashboard's progress rings + calories card read from.
  # Defaults match the previous hardcoded values on the frontend so existing
  # rows show the same numbers after migration. Coach can update them later
  # via the client information PATCH route.
  daily_step_goal : int = Field(default=10000)
  daily_calorie_goal : int = Field(default=2000)

  @field_validator("daily_step_goal")
  def step_goal_in_realistic_range(cls, v):
      if v < 0 or v > 70000:
          raise ValueError("daily_step_goal must be between 0 and 70000")
      return v

  @field_validator("daily_calorie_goal")
  def calorie_goal_in_realistic_range(cls, v):
      # 500 kcal lower bound is medically risky — anything under that is
      # almost certainly a typo. 6000 caps the upper end of high-volume
      # bulkers / endurance athletes; beyond that = data-entry error.
      if v < 500 or v > 6000:
          raise ValueError("daily_calorie_goal must be between 500 and 6000")
      return v

class ClientAvailability(SQLModelLU, table=True):
  __tablename__ = "client_availability"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)

class FitnessGoalEnum(str, Enum):
  WEIGHT_LOSS = "weight loss"
  MAINTENENCE = "maintenence"
  MUSCLE_GAIN = "muscle gain"

class FitnessGoals(SQLModelLU, table=True):
  __tablename__ = "fitness_goals"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")
  goal_enum : FitnessGoalEnum

  @field_validator("goal_enum")
  def validate_goal_enum(cls, value):
    return value.lower()

class ClientWorkoutPlan(SQLModelLU, table=True):
  __tablename__ = "client_workout_plan"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  # SET NULL — keeps the schedule rows after the client is gone so the
  # workout_plan creator can see who-had-this-on-the-calendar history.
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")
  workout_plan_id : int = Field(foreign_key="workout_plan.id")
  start_time : datetime
  end_time : datetime
  repeats_weekly: bool = Field(default=False)
  recurrence_end_dt: Optional[datetime] = None

  @model_validator(mode="after")
  def validate_time(self):
      start_time = self.start_time
      end_time = self.end_time
      if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")
      return self