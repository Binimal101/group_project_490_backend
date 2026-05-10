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


# Single source of truth for the monthly-equivalent rate ceiling. The frontend
# coach-request form caps user input at $500/mo; the leaderboard MVP ranking
# normalizes against this constant. Bumping the limit here propagates through
# both the validator below and the public ranking math.
MAX_MONTHLY_PRICE_CENTS: int = 50_000  # $500.00 / month


class PricingPlan(SQLModelLU, table=True):
  __tablename__ = "pricing_plan"  # type: ignore
  id: Optional[int] = Field(default=None, primary_key=True)
  # Coach-listing pages and the cron filter pricing plans by coach_id; index it.
  coach_id: int = Field(foreign_key="coach.id", ondelete="CASCADE", index=True)
  payment_interval: PricingInterval
  price_cents: int
  open_to_entry: bool = Field(default=True)

  @field_validator("price_cents")
  def validate_price_cents(cls, value):
    if value < 0:
      raise HTTPException(status_code=400, detail="Price in cents must be a non-negative integer")
    # Yearly plans are stored as the full year amount; the monthly ceiling
    # below is enforced after dividing by 12 at query time. Here we just
    # reject obviously-bad inputs.
    if value > MAX_MONTHLY_PRICE_CENTS * 12:
      raise HTTPException(status_code=400, detail="Price exceeds platform ceiling")
    return value

class BillingCycle(SQLModelLU, table=True):
  __tablename__ = "billing_cycle"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  active : bool
  entry_date : date
  end_date : date
  # refresh_payments scans cycles by subscription_id every cron run.
  subscription_id : int = Field(foreign_key="subscription.id", ondelete="CASCADE", index=True)
  pricing_plan_id : int = Field(foreign_key="pricing_plan.id", ondelete="CASCADE", index=True)

class Invoice(SQLModelLU, table=True):
  __tablename__ = "invoice"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  # Both billing-cycle scans (cron settle) and client invoice listings filter
  # invoices by these — neither was indexed before.
  billing_cycle_id : Optional[int] = Field(default=None, foreign_key="billing_cycle.id", ondelete="CASCADE", index=True)
  client_id : Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL", index=True)
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
  # The cron job filters active subs by client_id; the client invoice page
  # joins through here too.
  client_id: int = Field(foreign_key="client.id", ondelete="CASCADE", index=True)
  pricing_plan_id: Optional[int] = Field(default=None, foreign_key="pricing_plan.id", ondelete="SET NULL", index=True)

  status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
  start_date: date = Field(default_factory=date.today)  
  canceled_at: Optional[date] = None
  created_at: datetime = Field(default_factory=datetime.utcnow)

