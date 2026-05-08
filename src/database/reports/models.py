from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

from src.database.base import SQLModelLU

class CoachReport(SQLModelLU, table=True):
  __tablename__ = "coach_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  report_summary : str

class CoachReviews(SQLModelLU, table=True):
  __tablename__ = "coach_reviews"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  rating : float
  review_text : str
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")

class AccountReport(SQLModelLU, table=True):
  """Generic account-vs-account report. Any account can report any other account."""
  __tablename__ = "account_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  reporter_id : int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
  reportee_id : int = Field(foreign_key="account.id", index=True, ondelete="CASCADE")
  reason : str


class ClientReport(SQLModelLU, table=True):
  __tablename__ = "client_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  report_summary : str
