from sqlalchemy import Column, Time
from sqlmodel import Field
from decimal import Decimal
from typing import Optional
from datetime import datetime, time
from enum import Enum
from pydantic import field_validator
from src.database.base import SQLModelLU


class Account(SQLModelLU, table=True):
  __tablename__ = "account" # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  name: Optional[str] = None
  email: str

  # auth, ONE of these needs to be here
  hashed_password: Optional[str] = Field(default=None)
  gcp_user_id: Optional[str] = None
  
  # demo
  gender: Optional[str] = None
  bio: Optional[str] = None
  age: Optional[int] = None

  pfp_url: Optional[str] = None # pull from public supa bucket (private signing is too much rn)

  # role relations
  client_id: Optional[int] = Field(default=None, foreign_key="client.id") # all roles are clients by default
  coach_id: Optional[int] = Field(default=None, foreign_key="coach.id")
  admin_id: Optional[int] = Field(default=None, foreign_key="admin.id")

  created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
  
from enum import Enum

class Weekday(str, Enum):
   MONDAY = "monday"
   TUESDAY = "tuesday"
   WEDNESDAY = "wednesday"
   THURSDAY = "thursday"
   FRIDAY = "friday"
   SATURDAY = "saturday"
   SUNDAY = "sunday"

class Availability(SQLModelLU, table=True):
    __tablename__ = "availability"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    weekday: Weekday
    start_time: time = Field(sa_type=Time(timezone=True), nullable=False)
    end_time: time = Field(sa_type=Time(timezone=True), nullable=False)
    max_time_commitment_seconds: Optional[Decimal] = Field(default=None, max_digits=8, decimal_places=2)
    client_availability_id: Optional[int] = Field(default=None, foreign_key="client_availability.id")
    coach_availability_id: Optional[int] = Field(default=None, foreign_key="coach_availability.id")
