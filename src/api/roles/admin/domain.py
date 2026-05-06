from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import List, Optional

from src.api.roles.coach.domain import AccountPublic
from src.database.coach.models import Experience, Certifications


class AdminAccountItem(BaseModel):
    id: int
    name: str
    email: str
    role: str
    roles: List[str]
    status: str
    is_active: bool
    created_at: Optional[datetime] = None
    last_active: Optional[str] = None


class PotentialCoachItem(BaseModel):
    coach_request_id: int
    id: Optional[int] = None
    coach_id: int
    base_account: Optional[AccountPublic] = None
    experiences: Optional[List[Experience]] = None
    certifications: Optional[List[Certifications]] = None

    @model_validator(mode="after")
    def set_id(self):
        if self.id is None:
            self.id = self.coach_request_id
        return self

class AdminTransactionsResponse(BaseModel):
    total_transacted: float

class ResolveCoachRequestInput(BaseModel):
    coach_request_id: int
    is_approved: bool
