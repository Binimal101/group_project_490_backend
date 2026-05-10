from fastapi import HTTPException
from sqlalchemy import Column, DateTime
from sqlmodel import Field
from decimal import Decimal
from typing import Optional
from datetime import date, datetime
from pydantic import model_validator, EmailStr

from src.database.base import SQLModelLU

class Account(SQLModelLU, table=True):
  __tablename__ = "account" # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  name: str
  email: EmailStr = Field(index=True)
  is_active: bool = Field(default=True)
  is_suspended: bool = Field(default=False)
  # status: str = Field(default="active")

  # auth, ONE of these needs to be here
  hashed_password: Optional[str] = Field(default=None)
  gcp_user_id: Optional[str] = None
  
  # demo
  gender: Optional[str] = None
  bio: Optional[str] = None
  age: Optional[int] = None

  pfp_url: Optional[str] = None # pull from public supa bucket (private signing is too much rn)

  # personal fitness goals
  daily_steps_goal: Optional[int] = Field(default=10000)
  daily_calorie_budget: Optional[int] = Field(default=2000)

  # role relations — indexed because every JWT-authed request runs
  # `WHERE Account.client_id == ?` or `Account.coach_id == ?` to map back from
  # the role row to the parent account, and admin/coach dashboards filter by
  # these in IN-clauses to enrich names alongside lists of clients/coaches.
  client_id: Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL", index=True) # all roles are clients by default
  coach_id: Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL", index=True)
  admin_id: Optional[int] = Field(default=None, foreign_key="admin.id", index=True)

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

class Availability(SQLModelLU, table=True):
    __tablename__ = "availability"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="CASCADE")
    start_dt: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=False))
    end_dt: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=False))
    repeats_weekly: bool = Field(default=False)
    recurrence_end_dt: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    max_time_commitment_seconds: Optional[Decimal] = Field(default=None, max_digits=8, decimal_places=2)

    @model_validator(mode="after")
    def validate_time(self):
        if self.start_dt is None or self.end_dt is None:
            return self
        if self.start_dt >= self.end_dt:
            raise HTTPException(status_code=400, detail="start_dt must be before end_dt")
        if self.recurrence_end_dt is not None and self.recurrence_end_dt < self.end_dt:
            raise HTTPException(status_code=400, detail="recurrence_end_dt must be on or after end_dt")
        return self


class BusySlot(SQLModelLU, table=True):
    __tablename__ = "busy_slot"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="CASCADE")
    start_dt: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    end_dt: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    source: str = Field(default="manual")
    source_id: Optional[int] = Field(default=None, index=True)
    note: Optional[str] = None

    @model_validator(mode="after")
    def validate_time(self):
        if self.start_dt is None or self.end_dt is None:
            return self
        if self.start_dt >= self.end_dt:
            raise HTTPException(status_code=400, detail="start_dt must be before end_dt")
        return self

class AccountBlock(SQLModelLU, table=True):
    """A blocks B. Symmetric DM gate: a block in either direction blocks sends both ways."""
    __tablename__ = "account_block"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    blocker_id: int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
    blockee_id: int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")


class Notification(SQLModelLU, table=True):
    __tablename__ = "notification"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    # The notification list endpoint filters by account_id on every poll —
    # this is the single hottest read in the app.
    account_id: int = Field(foreign_key="account.id", ondelete="CASCADE", index=True)

    fav_category: Optional[str] = None

    message: str
    details: Optional[str] = None # if they do expandable dialogs we have it built in
    is_read: bool = False
    created_at: date = Field(default_factory=date.today)
