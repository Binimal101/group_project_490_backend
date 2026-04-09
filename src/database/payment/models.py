from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, date

from src.database.base import SQLModelLU

class PaymentInformation(SQLModelLU, table=True):
  __tablename__ = "payment_information"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  ccnum : str
  cv : str
  exp_date : date

class PricingPlan(SQLModelLU, table=True):
  __tablename__ = "pricing_plan"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  payment_interval : str
  payment_amount : float
  open_to_entry : bool
  coach_id : int = Field(foreign_key="coach.id", ondelete="CASCADE")

class BillingCycle(SQLModelLU, table=True):
  __tablename__ = "billing_cycle"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  active : bool
  entry_date : date
  pricing_plan_id : int = Field(foreign_key="pricing_plan.id", ondelete="CASCADE")

class Invoice(SQLModelLU, table=True):
  __tablename__ = "invoice"  # type: ignore
  id : Optional[int] = Field(default=None, primary_key=True)
  amount : float
  billing_cycle_id : int = Field(foreign_key="billing_cycle.id", ondelete="CASCADE")
  client_id : int = Field(foreign_key="client.id", ondelete="CASCADE")
  outstanding_balance : float

