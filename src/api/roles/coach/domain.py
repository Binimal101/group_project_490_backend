from pydantic import BaseModel
from typing import List, Optional

class CreateCoachRequestResponse(BaseModel):
    #coach row created, attatched to user account, but has verified=False
    coach_request_id: int
    coach_id: int

#Coach
from src.database.coach.models import Experience, Certifications
class CoachDetails(BaseModel): #used for CRUD, mapping layer doesn't concern with mapping data->entities
    #TODO get availability
    experiences: List[Experience]
    certifications: List[Certifications]