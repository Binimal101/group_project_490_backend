import os
from datetime import date, timedelta

from sqlmodel import select
from fastapi import Depends, FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.dependencies import get_account_from_bearer
from src.database.session import get_session
from src.database.account.models import Account, Notification

# payment models
from src.database.payment.models import Subscription, BillingCycle, Invoice, PricingPlan, PricingInterval
from src.api.auth.services import serialize_account

#Routers
from src.api.auth.auth import router as auth_router
from src.api.roles.coach.coach import router as coach_router
from src.api.roles.client.client import router as client_router
from src.api.roles.shared.fitness import router as shared_fitness_router
from src.api.roles.shared.account import router as shared_account_router
from src.api.roles.shared.chat import router as shared_chat_router
from src.api.roles.shared.client_coach_relationship import router as shared_client_coach_relationship_router
from src.api.roles.shared.notifications import router as shared_notifications_router
from src.api.roles.client.fitness import router as client_fitness_router
from src.api.roles.client.telemetry import router as client_telemetry_router
from src.api.roles.coach.fitness import router as coach_fitness_router
from src.api.roles.admin.admin import router as admin_router

app = FastAPI(title="Group 6 490 Project API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)  # includes login, signup, and token routes
app.include_router(coach_router)
app.include_router(client_router)
app.include_router(shared_fitness_router)
app.include_router(shared_account_router)
app.include_router(shared_chat_router)
app.include_router(shared_client_coach_relationship_router)
app.include_router(shared_notifications_router)
app.include_router(client_fitness_router)
app.include_router(client_telemetry_router)
app.include_router(coach_fitness_router)
app.include_router(admin_router)

@app.get("/me")  # get_current_account assumes they pass a valid jwt as bearer
def read_current_account(user = Depends(get_account_from_bearer)):
    return serialize_account(user)

@app.get("/")
def health():
    return


@app.post("/refresh_payments")
def refresh_payments(payload: dict = Body(...), db = Depends(get_session)):
    """Settle outstanding balances for subscriptions and create next billing cycles.

    - For each subscription with a pricing plan, find the most recent billing cycle.
    - If any invoices for that billing cycle have outstanding_balance > 0, treat them as paid:
      - Create a new Invoice representing the payment (amount == total outstanding) with outstanding_balance = 0.
      - Zero out outstanding_balance on prior invoices for that billing cycle.
    - Create the next BillingCycle for the subscription based on the plan interval.
    """

    # validate cron secret from payload against environment
    provided = payload.get("cron_secret")
    expected = os.getenv("CRON_SECRET")
    if expected is None:
        raise HTTPException(status_code=500, detail="Server cron secret not configured")
    if provided != expected:
        raise HTTPException(status_code=403, detail="Invalid cron secret")

    subs = db.exec(select(Subscription)).all()

    for s in subs:
        # skip subscriptions without a pricing plan
        if not s.pricing_plan_id:
            continue

        # load current pricing plan for this subscription early (used for notifications)
        plan = db.get(PricingPlan, s.pricing_plan_id)
        if plan is None:
            continue

        # find most recent billing cycle for this subscription
        last_cycle = db.exec(
            select(BillingCycle).where(BillingCycle.subscription_id == s.id).order_by(BillingCycle.entry_date.desc())
        ).first()

        # if no existing cycle, create one starting today
        if last_cycle is None:
            last_cycle = BillingCycle(
                active=True,
                entry_date=date.today(),
                end_date=date.today(),
                subscription_id=s.id,
                pricing_plan_id=s.pricing_plan_id,
            )
            db.add(last_cycle)
            db.flush()

        # collect outstanding invoices for that billing cycle
        invoices = db.exec(select(Invoice).where(Invoice.billing_cycle_id == last_cycle.id, Invoice.outstanding_balance > 0)).all()
        total_outstanding = sum((inv.outstanding_balance or 0) for inv in invoices)

        if total_outstanding > 0:
            # zero out old outstanding invoices
            for inv in invoices:
                inv.outstanding_balance = 0.0
                db.add(inv)

            # create a new invoice representing the payment (mocked as successful)
            paid_invoice = Invoice(billing_cycle_id=last_cycle.id, client_id=s.client_id, amount=total_outstanding, outstanding_balance=0.0)
            db.add(paid_invoice)
            db.flush()

            # send notifications to client and coach about the payment
            client_account = db.exec(select(Account).where(Account.client_id == paid_invoice.client_id)).first()
            coach_account = db.exec(select(Account).where(Account.coach_id == plan.coach_id)).first()
            if client_account and client_account.id is not None:
                db.add(Notification(account_id=client_account.id, fav_category="payment", message=f"Your payment of ${total_outstanding:.2f} was processed.", details=f"Invoice {paid_invoice.id} for billing cycle {last_cycle.id} was paid."))
            if coach_account and coach_account.id is not None:
                db.add(Notification(account_id=coach_account.id, fav_category="payment", message=f"A payment of ${total_outstanding:.2f} was received from client {paid_invoice.client_id}.", details=f"Invoice {paid_invoice.id} for billing cycle {last_cycle.id} was paid."))

        # create next billing cycle based on pricing interval
        # determine next_start
        if last_cycle is None or last_cycle.end_date is None:
            next_start = date.today()
        else:
            next_start = last_cycle.end_date + timedelta(days=1)

        # choose the pricing plan for the next billing cycle. If the current plan is not open to entry,
        # select the newest pricing plan for the same coach that is open_to_entry.
        next_plan = plan
        if not getattr(next_plan, "open_to_entry", True):
            candidate = db.exec(
                select(PricingPlan).where(PricingPlan.coach_id == next_plan.coach_id, PricingPlan.open_to_entry == True).order_by(PricingPlan.id.desc())
            ).first()
            if candidate:
                next_plan = candidate

        if next_plan.payment_interval == PricingInterval.MONTHLY:
            next_end = next_start + timedelta(days=30)
        else:
            next_end = next_start + timedelta(days=365)

        new_cycle = BillingCycle(active=True, entry_date=next_start, end_date=next_end, subscription_id=s.id, pricing_plan_id=next_plan.id)
        db.add(new_cycle)

    db.commit()

    return {"status": "ok", "processed_subscriptions": len(subs)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)    
