from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel
from src.database.base import SQLModelLU

class ClientCoachRequest(SQLModelLU, table=True):
  __tablename__ = "client_coach_request"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  is_accepted : Optional[bool]
  # Both FKs indexed: every authorization check ("can this coach see this
  # client?") and every dashboard list filters by one of them.
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE", index=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE", index=True)
  created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ClientCoachRelationship(SQLModelLU, table=True):
  __tablename__ = "client_coach_relationship"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  request_id : int = Field(foreign_key="client_coach_request.id", ondelete="CASCADE", index=True)
  created_at : datetime
  # Soft-end flag. We keep the row around (even after termination) so historical
  # joins — invoices, completed workouts, telemetry — still resolve. Hard
  # deletes were used previously but they orphaned downstream data and broke
  # admin reports that needed to render past relationships.
  is_active : bool = Field(default=True)

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
