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