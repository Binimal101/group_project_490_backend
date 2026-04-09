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
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  goal_enum : FitnessGoalEnum

  @field_validator("goal_enum")
  def validate_goal_enum(cls, value):
    return value.lower()

class ClientWorkoutPlan(SQLModelLU, table=True):
  __tablename__ = "client_workout_plan"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  workout_plan_id : int = Field(foreign_key="workout_plan.id")
  start_time : datetime
  end_time : datetime

  @model_validator(mode="after")
  def validate_time(self):
      start_time = self.start_time
      end_time = self.end_time
      if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")
      return self