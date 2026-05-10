from sqlmodel import SQLModel, Field
from typing import Optional
from src.database.base import SQLModelLU
from datetime import datetime
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.admin.models import Admin

from enum import Enum

class Roles(str, Enum):
  CLIENT = "client"
  COACH = "coach"
  ADMIN = "admin"

class RolePromotionResolution(SQLModelLU, table=True):
  __tablename__ = "role_promotion_resolution" # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  role : Roles
  # Both FKs are SET NULL — the resolution row is an audit record. Deleting
  # the admin who approved a coach (or the account that got promoted) doesn't
  # erase the trail, just nulls out the references.
  admin_id : Optional[int] = Field(default=None, foreign_key="admin.id", ondelete="SET NULL")
  account_id : Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="SET NULL")
  is_approved : bool

class CoachRequest(SQLModelLU, table=True):
  __tablename__ = "coach_request"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  created_on : datetime = datetime.utcnow()
  role_promotion_resolution_id : Optional[int] = Field(default=None, foreign_key="role_promotion_resolution.id")
