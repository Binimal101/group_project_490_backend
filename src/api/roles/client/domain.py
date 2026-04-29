from datetime import datetime, date
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional
from fastapi import HTTPException
#Client
from src.database.client.models import FitnessGoals
from src.database.payment.models import PaymentInformation
from src.database.account.models import Availability, Account
from src.database.telemetry.models import HealthMetrics
from src.database.client.models import Client
from src.database.coach.models import Experience, Certifications
from src.database.reports.models import CoachReport, CoachReviews


class HirableCoachItem(BaseModel):
    coach_id: int
    name: str
    email: str
    age: Optional[int] = None
    gender: Optional[str] = None
    specialties: Optional[str] = None
    avg_rating: Optional[float] = None
    rating_count: int = 0
    experiences: Optional[List[Experience]] = None
    certifications: Optional[List[Certifications]] = None

class StepCountUpdateInput(BaseModel):
    step_count: int

    @field_validator("step_count")
    @classmethod
    def step_count_must_be_non_negative(cls, v):
        if 0 > v or v > 100000:
            raise ValueError("Step count must be a non-negative integer")
        return v
    
class StepCountUpdateOutput(BaseModel):
    step_count: int

class DunderInput(BaseModel):
    pass

class WeightUpdateInput(BaseModel):
    @field_validator("weight")
    @classmethod
    def weight_must_be_valid(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Weight must be greater than 0")
        return v
    weight: int

class InitialSurveyInput(BaseModel): #creates a client
    fitness_goals: FitnessGoals
    payment_information: PaymentInformation
    availabilities: List[Availability]
    initial_health_metric: HealthMetrics

    @model_validator(mode="after")
    def validate_nested_models(self):
        # Ensure nested SQLModel instances are fully validated/coerced
        # PaymentInformation
        if isinstance(self.payment_information, dict):
            self.payment_information = PaymentInformation.model_validate(self.payment_information)
        else:
            try:
                self.payment_information = PaymentInformation.model_validate(self.payment_information.model_dump())
            except Exception:
                # fallback: attempt to validate the instance directly
                self.payment_information = PaymentInformation.model_validate(self.payment_information)

        # Availabilities (list)
        validated_avails = []
        for a in self.availabilities:
            if isinstance(a, dict):
                validated_avails.append(Availability.model_validate(a))
            else:
                try:
                    validated_avails.append(Availability.model_validate(a.model_dump()))
                except Exception:
                    validated_avails.append(Availability.model_validate(a))

        self.availabilities = validated_avails

        return self

class UpdateClientInfoInput(BaseModel):
    fitness_goals: Optional[FitnessGoals] = Field(default=None) #reset fitness goals
    payment_information: Optional[PaymentInformation] = Field(default=None) #reset pmt info
    availabilities: Optional[List[Availability]] = Field(default=None) #new availabilities
    health_metrics: Optional[HealthMetrics] = Field(default=None)

    @model_validator(mode="after") #runs after model is validated from typing standards
    def ensure_not_empty(self):
        if not any((
            self.fitness_goals, 
            self.payment_information, 
            self.availabilities,
            self.health_metrics
        )):
            raise HTTPException(422, detail="Cannot update with no update parameters")
        
        return self #return the "safe" validated model, which is just itself (no need to cast / do anything else)

#Responses

class CoachReportResponse(BaseModel):
    report_id: int

class ReportsResponse(BaseModel):
    reports: List[CoachReport]

class CoachReviewResponse(BaseModel):
    review_id: int

class ReviewsResponse(BaseModel):
    reviews: List[CoachReviews]

class ClientCoachRequestResponse(BaseModel):
    request_id: int

class CreateClientResponse(BaseModel):
    client_id: int

class ClientAccountResponse(BaseModel):
    base_account: Account
    client_account: Client

class DunderResponse(BaseModel):
    details: str = "success"

class ClientInvoiceResponse(BaseModel):
    invoice_id: int
    amount: float
    outstanding_balance: float
    coach_name: str
    entry_date: date
    end_date: date

class ClientInvoicesListResponse(BaseModel):
    invoices: List[ClientInvoiceResponse]

class ClientBillingCycleResponse(BaseModel):
    coach_name: str
    entry_date: date
    end_date: date
    active: bool

class ClientBillingCyclesListResponse(BaseModel):
    cycles: List[ClientBillingCycleResponse]
