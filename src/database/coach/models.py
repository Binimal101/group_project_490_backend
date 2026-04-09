from datetime import date, datetime
from typing import Optional

from sqlmodel import Field

from src.database.base import SQLModelLU

class Coach(SQLModelLU, table=True):
  __tablename__ = "coach"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  verified : bool = Field(default=False) #false in system flow, gets created as a request, needs admin approval
  coach_availability : Optional[int] = Field(default=None, foreign_key="coach_availability.id")

class CoachAvailability(SQLModelLU, table=True):
  __tablename__ = "coach_availability"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)

class CoachExperience(SQLModelLU, table=True):
  __tablename__ = "coach_experience"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  experience_id : int = Field(foreign_key="experience.id")

class Experience(SQLModelLU, table=True):
  __tablename__ = "experience"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  experience_name : str
  experience_title : str
  experience_description : str
  experience_start: date
  experience_end : Optional[date]

class CoachCertifications(SQLModelLU, table=True):
  __tablename__ = "coach_certifications"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")
  certification_id : int = Field(foreign_key="certifications.id")

class Certifications(SQLModelLU, table=True):
  __tablename__ = "certifications"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  certification_name : str
  certification_date : date
  certification_score : Optional[str]
  certification_organization: str
