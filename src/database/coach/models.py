from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from pydantic import field_validator, model_validator
from sqlmodel import Field

from src.database.base import SQLModelLU

class Coach(SQLModelLU, table=True):
  __tablename__ = "coach"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  verified : bool = Field(default=False, nullable=False) #false in system flow, gets created as a request, needs admin approval
  specialties : Optional[str] = Field(default=None)
  coach_availability : Optional[int] = Field(default=None, foreign_key="coach_availability.id")

class CoachAvailability(SQLModelLU, table=True):
  __tablename__ = "coach_availability"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)

class CoachExperience(SQLModelLU, table=True):
  __tablename__ = "coach_experience"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  # SET NULL (was CASCADE) — coach can be deleted without erasing the
  # experience record (the underlying Experience row is shared / immutable).
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  experience_id : int = Field(foreign_key="experience.id")

class Experience(SQLModelLU, table=True):
  __tablename__ = "experience"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  experience_name : str
  experience_title : str
  experience_description : str
  experience_start: date
  experience_end : Optional[date]

  @model_validator(mode="after")
  def validate_time(self):
      start_time = self.experience_start
      end_time = self.experience_end
      if end_time is not None and start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")
      return self

class CoachCertifications(SQLModelLU, table=True):
  __tablename__ = "coach_certifications"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  coach_id : Optional[int] = Field(default=None, foreign_key="coach.id", ondelete="SET NULL")
  certification_id : int = Field(foreign_key="certifications.id")

class Certifications(SQLModelLU, table=True):
  __tablename__ = "certifications"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  certification_name : str
  certification_date : date
  certification_score : Optional[str] = Field(default=None)
  certification_organization: str
