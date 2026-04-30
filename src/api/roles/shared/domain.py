from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, EmailStr, EmailStr, model_validator

from src.database.account.models import Account
from src.database.coach_client_relationship.models import ChatMessage

class WorkoutPlanActivityInput(BaseModel):
    workout_activity_id: int
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def validate_one_time_metric(cls, data: dict):
        has_duration = data.get("planned_duration") is not None
        has_reps = data.get("planned_reps") is not None
        has_sets = data.get("planned_sets") is not None

        if has_duration and (has_reps or has_sets):
            raise ValueError(
                "An activity cannot have both a planned_duration and planned_reps/sets. "
                "Specify either duration for time-based activities or reps/sets for repetition-based ones."
            )
        
        if not has_duration and not (has_reps and has_sets):
            raise ValueError(
                "An activity must have either a planned_duration or both planned_reps and planned_sets."
            )
            
        return data

class CreateWorkoutPlanInput(BaseModel):
    strata_name: str
    activities: List[WorkoutPlanActivityInput]

class CreateNewChatInput(BaseModel):
    relationship_id: int


class ClientCoachContext(BaseModel):
    is_client: bool
    is_coach: bool
    account: Account

    @model_validator(mode="after")
    def validate_roles(cls, data):
        if not data.is_client and not data.is_coach:
            raise ValueError("Context user must be either client or coach in the relationship")
        return data

class UpdateAccountInput(BaseModel):
    age: Optional[int] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    pfp_url: Optional[str] = None
    gender: Optional[str] = None

#Responses
class CreateWorkoutPlanResponse(BaseModel):
    workout_plan_id: int

class NewChatResponse(BaseModel):
    chat_id: int

class FullProfileResponse(BaseModel):
    account: Account
    roles: List[str]
    client_details: Optional[dict] = None
    coach_details: Optional[dict] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    gender: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = None
    pfp_url: Optional[str] = None
    client_id: Optional[int] = None
    coach_id: Optional[int] = None
    admin_id: Optional[int] = None
    created_at: Optional[datetime] = None

class SendMessageResponse(BaseModel):
    message_id: int
    message_text: str
    from_account_id: int

class GetMessagesResponse(BaseModel):
    messages: List[ChatMessage]

class DeleteRequestResponse(BaseModel):
    message: str = "Request deleted successfully"

class DunderResponse(BaseModel):
    details: str = "success"

