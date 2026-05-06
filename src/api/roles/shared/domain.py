from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

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
    name: Optional[str] = None
    age: Optional[int] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    pfp_url: Optional[str] = None
    gender: Optional[str] = None

#Responses
class ChatWithAccountResponse(BaseModel):
    messages: List[ChatMessage]

class CreateWorkoutPlanResponse(BaseModel):
    workout_plan_id: int

class NewChatResponse(BaseModel):
    chat_id: int

# /me sub-models

class AvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    weekday: str
    start_time: time
    end_time: time
    max_time_commitment_seconds: Optional[Decimal] = None


class PaymentInfoResponse(BaseModel):
    id: int
    last_four: str
    cv: str        # always "***" from the server
    exp_date: str
    ccnum: str


class SubscriptionResponse(BaseModel):
    id: int
    coach_id: Optional[int] = None
    coach_name: str
    status: str
    start_date: Optional[str] = None
    canceled_at: Optional[str] = None
    payment_interval: str
    price_cents: int


class InvoiceResponse(BaseModel):
    invoice_id: int
    amount: float
    outstanding_balance: float
    coach_name: str
    entry_date: str
    end_date: str


class BillingCycleResponse(BaseModel):
    coach_name: str
    entry_date: str
    end_date: str
    price_cents: int
    payment_interval: str


class ProgressPictureResponse(BaseModel):
    id: int
    client_telemetry_id: Optional[int] = None
    url: str
    date: Optional[str] = None


class ClientDetailsResponse(BaseModel):
    id: int
    primary_goal: Optional[str] = None
    fitness_goals: List[str]
    availabilities: List[AvailabilityResponse]
    payment_information: Optional[PaymentInfoResponse] = None
    subscriptions: List[SubscriptionResponse]
    invoices: List[InvoiceResponse]
    billing_cycles: List[BillingCycleResponse]
    progress_pictures: List[ProgressPictureResponse]


class CertificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    certification_name: str
    certification_date: date
    certification_score: Optional[str] = None
    certification_organization: str


class ExperienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    experience_name: str
    experience_title: str
    experience_description: str
    experience_start: date
    experience_end: Optional[date] = None


class PricingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    coach_id: int
    payment_interval: str
    price_cents: int
    open_to_entry: bool


class CoachDetailsResponse(BaseModel):
    id: int
    verified: bool
    specialties: List[str]
    certifications: List[CertificationResponse]
    experiences: List[ExperienceResponse]
    availabilities: List[AvailabilityResponse]
    pricing: Optional[PricingPlanResponse] = None
    client_count: int
    total_earnings: float
    avg_rating: float
    review_count: int
    joined_date: Optional[str] = None


# Top-level response

class FullProfileResponse(BaseModel):
    account: Account
    roles: List[str]
    client_details: Optional[ClientDetailsResponse] = None
    coach_details: Optional[CoachDetailsResponse] = None

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

