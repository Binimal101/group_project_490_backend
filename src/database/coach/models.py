from sqlmodel import SQLModel, Field
from datetime import datetime

class Coach(SQLModel, table=True):
  __tablename__ = "coach"
  id : int = Field(primary_key=True)
  verified : bool
  coach_availability : int = Field(foreign_key="coach_availability.id")
  last_updated : datetime

class CoachAvailability(SQLModel, table=True):
  id : int = Field(primary_key=True)
  is_weekly : bool
  last_updated : datetime
