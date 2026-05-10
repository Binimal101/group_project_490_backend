from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

from src.database.base import SQLModelLU

# All FKs to account/client/coach/admin migrated from CASCADE to SET NULL —
# historical reports + reviews persist after the referenced user is deleted,
# just with null FKs. Each model's columns are now Optional to match.

class CoachReport(SQLModelLU, table=True):
  __tablename__ = "coach_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")
  report_summary : str

class CoachReviews(SQLModelLU, table=True):
  __tablename__ = "coach_reviews"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  rating : float
  review_text : str
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")

class AccountReport(SQLModelLU, table=True):
  """Generic account-vs-account report. Any account can report any other account."""
  __tablename__ = "account_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  reporter_id : Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="SET NULL")
  reportee_id : Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="SET NULL")
  reason : str


class ClientReport(SQLModelLU, table=True):
  __tablename__ = "client_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")
  report_summary : str
