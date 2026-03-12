from sqlmodel import SQLModel, Field
from datetime import datetime, date

class PaymentInformation(SQLModel, table=True):
  __tablename__ = "payment_information"
  id : int = Field(primary_key=True)
  ccnum : str
  cv : str
  exp_date : date
  last_updated : datetime

class PricingPlan(SQLModel, table=True):
  __tablename__ = "pricing_plan"
  id : int = Field(primary_key=True)
  payment_interval : str
  payment_amount : float
  open_to_entry : bool
  coach_id : int = Field(foreign_key="coach.id")
  last_updated : datetime

class BillingCycle(SQLModel, table=True):
  __tablename__ = "billing_cycle"
  id :int = Field(primary_key=True)
  active : bool
  entry_date : date
  pricing_plan_id : int = Field(foreign_key="pricing_plan.id")
  last_updated : datetime

class Invoice(SQLModel, table=True):
  __tablename__ = "invoice"
  id : int = Field(primary_key=True)
  amount : float
  billing_cycle_id : int = Field(foreign_key="billing_cycle.id")
  client_id : int = Field(foreign_key="client.id")
  outstanding_balance : float
  last_updated : datetime

