from pydantic import BaseModel
from typing import List, Optional

class CreateCoachRequestResponse(BaseModel):
    #coach row created, attatched to user account, but has verified=False
    coach_request_id: int
    coach_id: int

#Coach
from src.database.coach.models import Experience, Certifications, Coach
from src.database.account.models import Availability, Account

class CoachRequestInput(BaseModel): #used for CRUD, mapping layer doesn't concern with mapping data->entities
    availabilities: List[Availability]
    experiences: List[Experience]
    certifications: List[Certifications]

class CoachAccountResponse(BaseModel):
    base_account: Account
    coach_account: Coach

class WorkoutEquipmentInput(BaseModel):
    equiptment_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_required: bool = True
    is_recommended: bool = True

class CreateWorkoutInput(BaseModel):
    name: str
    description: str
    instructions: str
    workout_type: str
    equipment: List[WorkoutEquipmentInput] = []

class CreateWorkoutResponse(BaseModel):
    workout_id: int

class CreateActivityInput(BaseModel):
    workout_id: int
    intensity_measure: Optional[str] = None
    intensity_value: Optional[int] = None
    estimated_calories_per_unit_frequency: float

class CreateActivityResponse(BaseModel):
    workout_activity_id: int
