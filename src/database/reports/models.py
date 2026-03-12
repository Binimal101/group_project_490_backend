from sqlmodel import SQLModel, Field
from datetime import datetime

class CoachReport(SQLModel, table=True):
  __tablename__ = "coach_report"
  id : int = Field(primary_key=True)
  coach_id : int = Field(foreign_key="coach.id")
  client_id : int = Field(foreign_key="client.id")
  report_summary : str
  last_updated : datetime

class CoachReviews(SQLModel, table=True):
  __tablename__ = "coach_reviews"
  id : int = Field(primary_key=True)
  rating : float
  review_text : str
  coach_id : int = Field(foreign_key="coach.id")
  client_id : int = Field(foreign_key="client.id")
  last_updated : datetime

class ClientReport(SQLModel, table=True):
  __tablename__ = "client_report"
  id : int = Field(primary_key=True)
  coach_id : int = Field(foreign_key="coach.id")
  client_id : int = Field(foreign_key="client.id")
  report_summary : str
  last_updated : datetime
