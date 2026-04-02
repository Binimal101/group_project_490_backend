from pydantic import BaseModel
from typing import List

#Client
from src.database.client.models import FitnessGoals
from src.database.payment.models import PaymentInformation
from src.database.account.models import Availability, Account
from src.database.telemetry.models import HealthMetrics
from src.database.client.models import Client

class InitialSurveyInput(BaseModel):
    fitness_goals: FitnessGoals
    payment_information: PaymentInformation
    availabilities: List[Availability]
    initial_health_metric: HealthMetrics

class CreateClientResponse(BaseModel):
    client_id: int

class ClientAccountResponse(BaseModel):
    base_account: Account
    client_account: Client