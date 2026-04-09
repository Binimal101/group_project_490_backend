from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel
from src.database.base import SQLModelLU

class ClientCoachRequest(SQLModelLU, table=True):
  __tablename__ = "client_coach_request"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  is_accepted : Optional[bool]
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)  

class ClientCoachRelationship(SQLModelLU, table=True):
  __tablename__ = "client_coach_relationship"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  request_id : int = Field(foreign_key="client_coach_request.id", ondelete="CASCADE")
  create_at : datetime
  is_active : bool
  coach_blocked : bool
  client_blocked: bool

class Chat(SQLModelLU, table=True):
  __tablename__ = "chat"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  client_coach_relationship_id : int = Field(foreign_key="client_coach_relationship.id", ondelete="CASCADE")

class ChatMessage(SQLModelLU, table=True):
  __tablename__ = "chat_message"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  chat_id : int = Field(foreign_key="chat.id", ondelete="CASCADE")
  from_account_id : int = Field(foreign_key="account.id", index=True)
  is_read : bool = Field(default=False)
  message_text : str
