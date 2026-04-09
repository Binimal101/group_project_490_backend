from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from fastapi import HTTPException


#Coach
from src.database.coach.models import Experience, Certifications, Coach
from src.database.account.models import Availability, Account
class CoachRequestInput(BaseModel): #used for CRUD, mapping layer doesn't concern with mapping data->entities
    availabilities: List[Availability]
    experiences: List[Experience]
    certifications: List[Certifications]

class UpdateCoachInfoInput(BaseModel):
    availabilities: Optional[List[Availability]] = Field(default=None)
    experiences: Optional[List[Experience]] = Field(default=None)
    certifications: Optional[List[Certifications]] = Field(default=None)

class ClientCoachRequestInput(BaseModel):
    id: int
    is_accepted: bool
    client_id: int
    coach_id: int


#Responses
class DunderResponse(BaseModel):
    details: str = "success"


class CoachAccountResponse(BaseModel):
    base_account: Account
    coach_account: Coach

class CreateCoachRequestResponse(BaseModel):
    #coach row created, attatched to user account, but has verified=False
    coach_request_id: int
    coach_id: int

class UpdateCoachInfoResponse(BaseModel):
    #coach row updated with new certs, exps, and avails, but still has verified=False
    coach_id: int

class CoachRequestDeniedResponse(BaseModel):
    #coach row deleted along with certs, exps, and avails, user account set to coach_id=null
    coach_request_id: int
    coach_id: int

class AcceptedClientResponse(BaseModel):
    #client request accepted, row added to client_coach_relationship
    client_coach_request_id: int
    client_id: int
    coach_id: int
