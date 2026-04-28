from fastapi import HTTPException
from sqlalchemy import Column, Time
from sqlmodel import Field
from decimal import Decimal
from typing import Optional
from datetime import date, datetime, time
from enum import Enum
from pydantic import field_validator, model_validator, EmailStr

from src.database.base import SQLModelLU

class Account(SQLModelLU, table=True):
  __tablename__ = "account" # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  name: str
  email: EmailStr = Field(index=True)
  is_active: bool = Field(default=True)

  # auth, ONE of these needs to be here
  hashed_password: Optional[str] = Field(default=None)
  gcp_user_id: Optional[str] = None
  
  # demo
  gender: Optional[str] = None
  bio: Optional[str] = None
  age: Optional[int] = None

  pfp_url: Optional[str] = None # pull from public supa bucket (private signing is too much rn)

  # role relations
  client_id: Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL") # all roles are clients by default
  coach_id: Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  admin_id: Optional[int] = Field(default=None, foreign_key="admin.id")

  created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

  @model_validator(mode="after")
  def validate_auth(self):
      hashed_password = self.hashed_password
      gcp_user_id = self.gcp_user_id
      if not hashed_password and not gcp_user_id:
          raise HTTPException(status_code=400, detail="Either hashed_password or gcp_user_id must be provided")
      if hashed_password and gcp_user_id:
          raise HTTPException(status_code=400, detail="Only one of hashed_password or gcp_user_id can be provided")
      return self

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
    start_time: time = Field(sa_column=Column(Time(timezone=True), nullable=False))
    end_time: time = Field(sa_column=Column(Time(timezone=True), nullable=False))
    max_time_commitment_seconds: Optional[Decimal] = Field(default=None, max_digits=8, decimal_places=2)
    client_availability_id: Optional[int] = Field(default=None, foreign_key="client_availability.id")
    coach_availability_id: Optional[int] = Field(default=None, foreign_key="coach_availability.id")

    @model_validator(mode="after")
    def validate_time(self):
        start_time = self.start_time
        end_time = self.end_time
        if start_time >= end_time:
            raise HTTPException(status_code=400, detail="start_time must be before end_time")
        return self

class Notification(SQLModelLU, table=True):
    __tablename__ = "notification"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", ondelete="CASCADE")
    
    fav_category: Optional[str] = None
    
    message: str
    details: Optional[str] = None # if they do expandable dialogs we have it built in
    is_read: bool = False
    created_at: date = Field(default_factory=date.today)