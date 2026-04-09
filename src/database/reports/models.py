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

class ClientReport(SQLModelLU, table=True):
  __tablename__ = "client_report"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  report_summary : str
