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
  admin_id : int = Field(foreign_key="admin.id")
  account_id : int = Field(foreign_key="account.id", index=True)
  is_approved : bool

class CoachRequest(SQLModelLU, table=True):
  __tablename__ = "coach_request"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  created_on : datetime = datetime.utcnow()
  role_promotion_resolution_id : Optional[int] = Field(default=None, foreign_key="role_promotion_resolution.id")
