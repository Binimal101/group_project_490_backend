from decimal import Decimal
from datetime import datetime, date

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional
from fastapi import HTTPException


#Coach
from src.database.coach.models import Experience, Certifications, Coach
from src.database.account.models import Availability, Account, Weekday
from src.database.payment.models import PricingInterval
from src.database.workouts_and_activities.models import Equiptment, WorkoutPlanActivity, WorkoutType
from src.database.client.models import Client, FitnessGoals
from src.database.reports.models import ClientReport

class CoachRequestInput(BaseModel): #used for CRUD, mapping layer doesn't concern with mapping data->entities
    availabilities: List[Availability]
    experiences: List[Experience]
    certifications: List[Certifications]
    payment_interval: PricingInterval
    price_cents: int
    specialties: Optional[List[str]] = Field(default=None)

    @field_validator("price_cents")
    @classmethod
    def validate_price_cents(cls, v):
        if v < 0:
            raise ValueError("Price in cents must be a non-negative integer")
        return v

    @model_validator(mode="after")
    def validate_nested(self):
        # Ensure availabilities, experiences, and certifications are validated/coerced
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

        validated_exps = []
        for e in self.experiences:
            if isinstance(e, dict):
                validated_exps.append(Experience.model_validate(e))
            else:
                try:
                    validated_exps.append(Experience.model_validate(e.model_dump()))
                except Exception:
                    validated_exps.append(Experience.model_validate(e))
        self.experiences = validated_exps

        validated_certs = []
        for c in self.certifications:
            if isinstance(c, dict):
                validated_certs.append(Certifications.model_validate(c))
            else:
                try:
                    validated_certs.append(Certifications.model_validate(c.model_dump()))
                except Exception:
                    validated_certs.append(Certifications.model_validate(c))
        self.certifications = validated_certs

        return self

class UpdateCoachInfoInput(BaseModel):
    availabilities: Optional[List[Availability]] = Field(default=None)
    experiences: Optional[List[Experience]] = Field(default=None)
    certifications: Optional[List[Certifications]] = Field(default=None)
    specialties: Optional[List[str]] = Field(default=None)

    @model_validator(mode="after")
    def validate_nested(self):
        if self.availabilities is not None:
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

        if self.experiences is not None:
            validated_exps = []
            for e in self.experiences:
                if isinstance(e, dict):
                    validated_exps.append(Experience.model_validate(e))
                else:
                    try:
                        validated_exps.append(Experience.model_validate(e.model_dump()))
                    except Exception:
                        validated_exps.append(Experience.model_validate(e))
            self.experiences = validated_exps

        if self.certifications is not None:
            validated_certs = []
            for c in self.certifications:
                if isinstance(c, dict):
                    validated_certs.append(Certifications.model_validate(c))
                else:
                    try:
                        validated_certs.append(Certifications.model_validate(c.model_dump()))
                    except Exception:
                        validated_certs.append(Certifications.model_validate(c))
            self.certifications = validated_certs

        return self


class CoachDeniedRequestInput(BaseModel):
    coach_id: int
    is_accepted: bool = False

class WorkoutInput(BaseModel):
    name: str
    description: str
    instructions: str
    workout_type: WorkoutType
    equipment: Optional[List[Equiptment]]

class WorkoutActivityInput(BaseModel):
    workout_id: int
    intensity_measure: Optional[str] = None
    intensity_value: Optional[int] = None
    estimated_calories_per_unit_frequency: Decimal = Field(max_digits=10, decimal_places=6)

class WorkoutPlanInput(BaseModel):
    strata_name: str
    workout_activities: Optional[List[WorkoutPlanActivity]] = Field(default=None)

#Responses
class DunderResponse(BaseModel):
    details: str = "success"

class CoachEarningsResponse(BaseModel):
    total_earnings: float
    since: Optional[date] = None



class ClientRequestItem(BaseModel):
    client_id: int
    request_id: int

# Return a plain list of mappings: [{"client_id": x, "request_id": y}, ...]
RequestListResponse = List[ClientRequestItem]

class CoachAccountResponse(BaseModel):
    base_account: Account
    coach_account: Coach

class CreateCoachRequestResponse(BaseModel):
    #coach row created, attatched to user account, but has verified=False
    coach_request_id: int
    coach_id: int

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

class UpdateCoachInfoResponse(BaseModel):
    #coach row updated with new certs, exps, and avails, but still has verified=False
    coach_id: int

class CoachRequestDeniedResponse(BaseModel):
    #coach row deleted along with certs, exps, and avails, user account set to coach_id=null
    coach_request_id: int
    coach_id: int

class CoachAvailabilityResponse(BaseModel):
    coach_availabilities: List[Availability]

class AcceptedClientResponse(BaseModel):
    #client request accepted, row added to client_coach_relationship
    relationship_id: int

class DeniedClientResponse(BaseModel):
    #client request denied
    relationship_id: int


class AccountPublic(BaseModel):
    id: int
    name: str
    email: str
    is_active: bool
    gcp_user_id: Optional[str] = None
    gender: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = None
    pfp_url: Optional[str] = None
    client_id: Optional[int] = None
    coach_id: Optional[int] = None
    admin_id: Optional[int] = None
    created_at: Optional[datetime] = None


class ClientLookupResponse(BaseModel):
    base_account: AccountPublic
    client_account: Client
    availabilities: Optional[List[Availability]] = None
    fitness_goals: Optional[List[FitnessGoals]] = None


class ClientReportResponse(BaseModel):
    report_id: int

class ReportsResponse(BaseModel):
    reports: List[ClientReport]
