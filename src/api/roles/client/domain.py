from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional
from fastapi import HTTPException
#Client
from src.database.client.models import FitnessGoals
from src.database.payment.models import PaymentInformation
from src.database.account.models import Availability, Account
from src.database.telemetry.models import HealthMetrics
from src.database.client.models import Client

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

class CreateClientResponse(BaseModel):
    client_id: int

class ClientAccountResponse(BaseModel):
    base_account: Account
    client_account: Client

class DunderResponse(BaseModel):
    details: str = "success"