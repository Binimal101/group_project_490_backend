from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.admin.models import Admin

class Roles(SQLModel, table=True):
  __tablename__ = "roles"
  id : int = Field(primary_key=True)
  name : str
  last_updated : datetime

class RolePromotionResolution(SQLModel, table=True):
  __tablename__ = "role_promotion_resolution"
  id : int = Field(primary_key=True)
  admin_id : int = Field(foreign_key="admin.id")
  client_id : int = Field(foreign_key="client.id")
  role_id : int = Field(foreign_key="roles.id")
  is_approved : bool
  last_updated : datetime

class CoachRequest(SQLModel, table=True):
  __tablename__ = "coach_request"
  id : int = Field(primary_key=True)
  coach_id : int = Field(foreign_key="coach.id")
  created_on : datetime
  role_promotion_resolution_id : Optional[int] = Field(foreign_key="role_promotion_resolution.id")
  last_updated : datetime
