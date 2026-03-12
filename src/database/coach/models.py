from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Coach(SQLModel, table=True):
  __tablename__ = "coach"
  id : int = Field(primary_key=True)
  verified : bool
  coach_availability : Optional[int] = Field(foreign_key="coach_availability.id")
  last_updated : datetime

class CoachAvailability(SQLModel, table=True):
  __tablename__ = "coach_availability"
  id : int = Field(primary_key=True)
  is_weekly : bool
  last_updated : datetime

class CoachExperience(SQLModel, table=True):
  __tablename__ = "coach_experience"
  id : int = Field(primary_key=True)
  coach_id : int = Field(foreign_key="coach.id")
  experience_id : id = Field(foreign_key="experience.id")
  last_updated : datetime

class Experience(SQLModel, table=True):
  __tablename__ = "experience"
  id : int = Field(primary_key=True)
  experience_name : str
  experience_title : str
  experience_description : str
  experience_start: date
  experience_end : Optional[date]
  last_updated : datetime

class CoachCertifications(SQLModel, table=True):
  __tablename__ = "coach_certifications"
  id : int = Field(primary_key=True)
  coach_id = int = Field(foreign_key="coach.id")
  certification_id : int = Field(foreign_key="certification.id")
  last_updated : datetime

class Certifications(SQLModel, table=True):
  __tablename__ = "certifications"
  id : int = Field(primary_key=True)
  certification_name : str
  certification_date : date
  certification_score : Optional[str]
  certification_organization: str
  last_updated : datetime
