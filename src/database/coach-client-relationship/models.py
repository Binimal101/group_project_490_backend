from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.base_accounts.models import Account

class ClientCoachRequest(SQLModel, table=True):
  __tablename__ = "client_coach_request"
  id : int = Field(primary_key=True)
  created_at : datetime
  is_accepted : Optional[bool]
  client_id : int = Field(foreign_key="client.id")
  coach_id : int = Field(foreign_key="coach.id")
  last_updated : datetime

class ClientCoachRelationship(SQLModel, table=True):
  __tablename__ = "client_coach_relationship"
  id : int = Field(primary_key=True)
  request_id : int = Field(foreign_key="client_coach_request.id")
  create_at : datetime
  is_active : bool
  coach_blocked : bool
  client_blocked: bool
  last_updated : datetime

class Chat(SQLModel, table=True):
  __tablename__ = "chat"
  id : int = Field(primary_key=True)
  client_coach_relationship_id : int = Field(foreign_key="client_coach_relationship.id")
  last_updated : datetime

class ChatMessage(SQLModel, table=True):
  __tablename__ = "chat_message"
  id : int = Field(primary_key=True)
  chat_id : int = Field(foreign_key="chat.id")
  from_account_id : int = Field(foreign_key="account.id")
  is_read : bool
  last_updated : datetime
