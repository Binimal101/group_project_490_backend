from fastapi import HTTPException
from pydantic import field_validator
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, date
from enum import Enum

from src.database.payment.services import luhn_sum
from src.database.base import SQLModelLU

class PaymentInformation(SQLModelLU, table=True):
  __tablename__ = "payment_information"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  ccnum : str
  cv : str
  exp_date : date

  @field_validator("ccnum")
  def validate_ccnum(cls, value): #use luhn algorithm to validate credit card number
    value = value.replace(" ", "").replace("-", "")
    if not value.isdigit():
        raise HTTPException(status_code=400, detail="Credit card number must contain only digits and spaces")

    if not (13 <= len(value) <= 19):
        raise HTTPException(status_code=400, detail="Credit card number must be between 13 and 19 digits long")
    
    # luhn algorithm
    total = luhn_sum(value)

    if total % 10 != 0:
        raise HTTPException(status_code=400, detail="Invalid credit card number, failed luhn check")

    return value

  @field_validator("cv")
  def validate_cv(cls, value):
    if not value.isdigit():
        raise HTTPException(status_code=400, detail="CV must contain only digits")

    if len(value) not in [3, 4]:
        raise HTTPException(status_code=400, detail="CV must be 3 or 4 digits long")
    return value
    
  @field_validator("exp_date")
  def validate_exp_date(cls, value):
    if value < date.today():
        raise HTTPException(status_code=400, detail="Card has expired")
    return value

class PricingInterval(str, Enum):
  MONTHLY = "monthly"
  YEARLY = "yearly"

class PricingPlan(SQLModelLU, table=True):
  __tablename__ = "pricing_plan"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  coach_id: int = Field(foreign_key="coach.id", ondelete="CASCADE")
  payment_interval: PricingInterval
  price_cents: int
  currency: str = Field(default="USD")
  trial_days: int = Field(default=0)
  open_to_entry: bool = Field(default=True)

class BillingCycle(SQLModelLU, table=True):
  __tablename__ = "billing_cycle"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  active : bool
  entry_date : date
  pricing_plan_id : int = Field(foreign_key="pricing_plan.id", ondelete="CASCADE")

class Invoice(SQLModelLU, table=True):
  __tablename__ = "invoice"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  billing_cycle_id : Optional[int] = Field(default=None, foreign_key="billing_cycle.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  amount : float
  outstanding_balance : float

class SubscriptionStatus(str, Enum):
  ACTIVE = "active"
  PAST_DUE = "past_due"
  UNPAID = "unpaid"
  CANCELED = "canceled"

class Subscription(SQLModelLU, table=True):
  __tablename__ = "subscription"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  client_id: int = Field(foreign_key="client.id", ondelete="CASCADE")
  pricing_plan_id: Optional[int] = Field(default=None, foreign_key="pricing_plan.id", ondelete="SET NULL")

  status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
  start_date: date = Field(default_factory=date.today)

  current_period_start: Optional[date] = None
  current_period_end: Optional[date] = None
  next_billing_date: Optional[date] = None
  cancel_at_period_end: bool = Field(default=False)

  canceled_at: Optional[date] = None
  created_at: datetime = Field(default_factory=datetime.utcnow)

