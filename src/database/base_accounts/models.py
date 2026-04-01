from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.admin.models import Admin

class SupaUser(SQLModel, table=True):
  __tablename__ = "supa_user"
  id : int = Field(primary_key=True)
  email : Optional[str]
  last_updated : datetime

class Account(SQLModel, table=True):
  __tablename__ = "account"
  id : int = Field(primary_key=True)
  supa_user_id : int = Field(foreign_key="supa_user.id")
  coach_id : Optional[int] = Field(foreign_key="coach.id")
  client_id : Optional[int] = Field(foreign_key="client.id")
  admin_id : Optional[int] = Field(foreign_key="admin.id")
  last_updated : datetime
