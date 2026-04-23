from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, model_validator

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



#Responses
class CreateWorkoutPlanResponse(BaseModel):
    workout_plan_id: int

class NewChatResponse(BaseModel):
    chat_id: int

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

