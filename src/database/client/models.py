from sqlmodel import SQLModel, Field
from datetime import datetime, date

class Client(SQLModel, table=True):
  __tablename__ = "client"
  id: int = Field(primary_key=True)
  payment_information_id : int = Field(foreign_key="payment_information.id")
  client_availability_id : int = Field(foreign_key="client_availability.id")
  last_update : datetime

class ClientAvailability(SQLModel, table=True):
  __tablename__ = "client_availability"
  id : int = Field(primary_key=True)
  id_weekly : bool

class FitnessGoals(SQLModel, table=True):
  __tablename__ = "fitness_goals"
  id : int = Field(primary_key=True)
  client_id : int = Field(foreign_key="client.id")
  goal_enum : str
  last_updated : datetime

class ClientWorkoutPlan(SQLModel, table=True):
  __tablename__ = "client_workout_plan"
  id: int = Field(primary_key=True)
  client_id : int = Field(foreign_key="client.id")
  workout_plan_id : int = Field(foreign_key="workout_plan.id")
  start_time : datetime
  end_time : datetime
