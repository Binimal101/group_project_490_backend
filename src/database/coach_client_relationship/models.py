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
  created_at : datetime
  is_active : bool

class Chat(SQLModelLU, table=True):
  __tablename__ = "chat"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)

class ChatMessage(SQLModelLU, table=True):
  __tablename__ = "chat_message"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  chat_id : int = Field(foreign_key="chat.id", ondelete="CASCADE")
  from_account_id : int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
  is_read : bool = Field(default=False)
  message_text : str


class AccountChat(SQLModelLU, table=True):
  """Join row attaching an account to a chat. Exactly two rows per chat (enforced in app code)."""
  __tablename__ = "account_chat"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  account_id : int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
  chat_id : int = Field(foreign_key="chat.id", index=True, ondelete="CASCADE")
