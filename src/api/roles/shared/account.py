from fastapi import APIRouter, Depends, UploadFile, HTTPException

from src.database.session import get_session
from src.database.account.models import Account, Availability, Notification
from src.database.client.models import Client, FitnessGoals
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.payment.models import PricingPlan, PaymentInformation, Subscription, BillingCycle, Invoice
from src.database.telemetry.models import HealthMetrics, ClientTelemetry, DailyProgressPicture
from src.database.coach_client_relationship.models import ClientCoachRelationship, ClientCoachRequest
from src.database.reports.models import CoachReviews
from src.api.dependencies import get_account_from_bearer, get_active_account, get_account_even_if_inactive
from src.api.storage import upload_public_file_to_supabase
from src.api.roles.shared.domain import FullProfileResponse, AccountResponse, UpdateAccountInput
from sqlmodel import Session, select, desc, func
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/roles/shared/account", tags=["shared", "account"])


@router.get("/me", response_model=FullProfileResponse)
def get_full_profile(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Returns a unified profile object with account info, roles, and role-specific details
    (fitness goals, availability, coach certifications/experience, etc.)
    """
    roles: List[str] = []
    client_details = None
    coach_details = None

    if acc.client_id is not None:
        roles.append("client")
        client = db.get(Client, acc.client_id)
        if client:
            goals = db.exec(select(FitnessGoals).where(FitnessGoals.client_id == client.id)).all()
            fitness_goals_out = [
                getattr(g.goal_enum, "value", g.goal_enum)
                for g in goals
                if g.goal_enum
            ]
            primary_goal = fitness_goals_out[0] if fitness_goals_out else None
            availabilities = db.exec(select(Availability).where(Availability.client_availability_id == client.client_availability_id)).all()

            # Payment information (censored)
            payment_info = None
            if client.payment_information_id:
                pi = db.get(PaymentInformation, client.payment_information_id)
                if pi:
                    payment_info = {
                        "id": pi.id,
                        "last_four": str(pi.ccnum)[-4:] if pi.ccnum else "",
                        "cv": "***",
                        "exp_date": str(pi.exp_date) if pi.exp_date else "",
                        "ccnum": pi.ccnum,
                    }

            # Active subscriptions with coach name
            subscriptions_out = []
            subs = db.exec(
                select(Subscription, PricingPlan, Account)
                .join(PricingPlan, Subscription.pricing_plan_id == PricingPlan.id)
                .join(Account, PricingPlan.coach_id == Account.coach_id)
                .where(Subscription.client_id == client.id)
                .order_by(desc(Subscription.id))
            ).all()
            for sub, plan, coach_acc_row in subs:
                subscriptions_out.append({
                    "id": sub.id,
                    "coach_id": plan.coach_id,
                    "coach_name": coach_acc_row.name,
                    "status": sub.status,
                    "start_date": str(sub.start_date) if sub.start_date else None,
                    "canceled_at": str(sub.canceled_at) if sub.canceled_at else None,
                    "payment_interval": plan.payment_interval,
                    "price_cents": plan.price_cents,
                })

            # Invoices
            invoices_out = []
            invoices = db.exec(
                select(Invoice, BillingCycle, PricingPlan, Account)
                .join(BillingCycle, Invoice.billing_cycle_id == BillingCycle.id)
                .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
                .join(Account, PricingPlan.coach_id == Account.coach_id)
                .where(Invoice.client_id == client.id)
                .order_by(desc(Invoice.id))
            ).all()
            for inv, cycle, plan, coach_acc_row in invoices:
                invoices_out.append({
                    "invoice_id": inv.id,
                    "amount": inv.amount,
                    "outstanding_balance": inv.outstanding_balance,
                    "coach_name": coach_acc_row.name,
                    "entry_date": str(cycle.entry_date),
                    "end_date": str(cycle.end_date),
                })

            # Active billing cycles
            billing_cycles_out = []
            cycles = db.exec(
                select(BillingCycle, PricingPlan, Account)
                .join(Subscription, BillingCycle.subscription_id == Subscription.id)
                .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
                .join(Account, PricingPlan.coach_id == Account.coach_id)
                .where(
                    Subscription.client_id == client.id,
                    Subscription.status == "active",
                    BillingCycle.active == True,
                )
                .order_by(desc(BillingCycle.id))
            ).all()
            for cycle, plan, coach_acc_row in cycles:
                billing_cycles_out.append({
                    "coach_name": coach_acc_row.name,
                    "entry_date": str(cycle.entry_date),
                    "end_date": str(cycle.end_date),
                    "price_cents": plan.price_cents,
                    "payment_interval": plan.payment_interval,
                })

            # Progress pictures from DailyProgressPicture (one per day, upserted)
            progress_pics_out = []
            pics = db.exec(
                select(DailyProgressPicture, ClientTelemetry)
                .join(ClientTelemetry, DailyProgressPicture.client_telemetry_id == ClientTelemetry.id)
                .where(ClientTelemetry.client_id == client.id)
                .order_by(desc(DailyProgressPicture.id))
            ).all()
            for dpp, ct in pics:
                progress_pics_out.append({
                    "id": dpp.id,
                    "client_telemetry_id": ct.id,
                    "url": dpp.url,
                    "date": str(ct.date) if ct.date else None,
                })

            client_details = {
                "id": client.id,
                "primary_goal": primary_goal,
                "fitness_goals": fitness_goals_out,
                "availabilities": availabilities,
                "payment_information": payment_info,
                "subscriptions": subscriptions_out,
                "invoices": invoices_out,
                "billing_cycles": billing_cycles_out,
                "progress_pictures": progress_pics_out,
            }

    if acc.coach_id is not None:
        coach = db.get(Coach, acc.coach_id)
        if coach:
            if coach.verified:
                roles.append("coach")
            else:
                roles.append("coach_pending_or_denied")

            certs = db.exec(
                select(Certifications)
                .join(CoachCertifications)
                .where(CoachCertifications.coach_id == coach.id)
            ).all()

            exps = db.exec(
                select(Experience)
                .join(CoachExperience)
                .where(Experience.id == CoachExperience.experience_id)
                .where(CoachExperience.coach_id == coach.id)
            ).all()

            availabilities = db.exec(select(Availability).where(Availability.coach_availability_id == coach.coach_availability)).all()

            pricing = db.exec(select(PricingPlan).where(PricingPlan.coach_id == coach.id).order_by(desc(PricingPlan.id))).first()

            # Client count (active relationships)
            client_count = db.exec(
                select(func.count())
                .select_from(ClientCoachRelationship)
                .join(ClientCoachRequest, ClientCoachRelationship.request_id == ClientCoachRequest.id)
                .where(ClientCoachRequest.coach_id == coach.id, ClientCoachRelationship.is_active == True)
            ).one()

            # Earnings: sum of paid invoice amounts
            total_earnings_raw = db.exec(
                select(func.coalesce(func.sum(Invoice.amount - Invoice.outstanding_balance), 0))
                .join(BillingCycle, Invoice.billing_cycle_id == BillingCycle.id)
                .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
                .where(PricingPlan.coach_id == coach.id)
            ).one()
            total_earnings = float(total_earnings_raw or 0)

            # Rating
            avg_rating_raw = db.exec(
                select(func.avg(CoachReviews.rating)).where(CoachReviews.coach_id == coach.id)
            ).one()
            review_count = db.exec(
                select(func.count()).select_from(CoachReviews).where(CoachReviews.coach_id == coach.id)
            ).one()

            coach_details = {
                "id": coach.id,
                "verified": coach.verified,
                "specialties": coach.specialties.split(",") if coach.specialties else [],
                "certifications": certs,
                "experiences": exps,
                "availabilities": availabilities,
                "pricing": pricing,
                "client_count": client_count or 0,
                "total_earnings": total_earnings,
                "avg_rating": round(float(avg_rating_raw), 1) if avg_rating_raw else 0,
                "review_count": review_count or 0,
                "joined_date": str(acc.created_at) if acc.created_at else None,
            }

    if acc.admin_id is not None:
        roles.append("admin")

    return FullProfileResponse(
        account=acc,
        roles=roles,
        client_details=client_details,
        coach_details=coach_details,
    )


@router.post("/update_pfp")
def update_profile_picture(
    file: UploadFile,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Uploads the provided file to the `profile_picture` bucket and updates the
    current account's `pfp_url` to the public URL for the uploaded object.
    """
    public_url = upload_public_file_to_supabase(file, "profile_picture", str(acc.id))

    # persist to account
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")

    account.pfp_url = public_url
    db.add(account)
    db.commit()
    db.refresh(account)

    return {"url": public_url}


class UpdateAccountInput(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    pfp_url: Optional[str] = None
    gender: Optional[str] = None


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


class DeactivateAccountResponse(BaseModel):
    success: bool
    message: str

class ActivateAccountResponse(BaseModel):
    success: bool
    message: str


def get_affected_accounts(db: Session, account: Account) -> list[Account]:
    affected_accounts_by_id: dict[int, Account] = {}

    def add_affected_account(affected_account: Account | None):
        if affected_account is None:
            return
        if affected_account.id is None or affected_account.id == account.id:
            return
        affected_accounts_by_id[affected_account.id] = affected_account

    # If the deactivated account is a client, notify their active coach(es)
    if account.client_id is not None:
        relationships = db.exec(
            select(ClientCoachRequest, ClientCoachRelationship)
            .join(
                ClientCoachRelationship,
                ClientCoachRelationship.request_id == ClientCoachRequest.id,
            )
            .where(
                ClientCoachRequest.client_id == account.client_id,
                ClientCoachRelationship.is_active == True,
            )
        ).all()

        for request, relationship in relationships:
            coach_account = db.exec(
                select(Account).where(Account.coach_id == request.coach_id)
            ).first()

            add_affected_account(coach_account)

    # If the deactivated account is a coach, notify their active client(s)
    if account.coach_id is not None:
        relationships = db.exec(
            select(ClientCoachRequest, ClientCoachRelationship)
            .join(
                ClientCoachRelationship,
                ClientCoachRelationship.request_id == ClientCoachRequest.id,
            )
            .where(
                ClientCoachRequest.coach_id == account.coach_id,
                ClientCoachRelationship.is_active == True,
            )
        ).all()

        for request, relationship in relationships:
            client_account = db.exec(
                select(Account).where(Account.client_id == request.client_id)
            ).first()

            add_affected_account(client_account)

    return list(affected_accounts_by_id.values())


def notify_affected_accounts(
    db: Session,
    deactivated_account: Account,
    affected_accounts: list[Account],
):
    for affected_account in affected_accounts:
        if affected_account.id is None:
            continue

        role = "account"
        if deactivated_account.client_id is not None:
            role = "client"
        elif deactivated_account.coach_id is not None:
            role = "coach"

        db.add(
            Notification(
                account_id=affected_account.id,
                fav_category="account_deactivated",
                message=f"{deactivated_account.name} has deactivated their account.",
                details=f"{role.capitalize()} account {deactivated_account.id} was deactivated.",
                is_read=False,
            )
        )


def delete_client_coach_mappings(db: Session, account: Account):
    if account.client_id is not None:
        requests = db.exec(
            select(ClientCoachRequest)
            .where(ClientCoachRequest.client_id == account.client_id)
        ).all()

        for request in requests:
            relationships = db.exec(
                select(ClientCoachRelationship)
                .where(ClientCoachRelationship.request_id == request.id)
            ).all()

            for relationship in relationships:
                db.delete(relationship)

            db.delete(request)

    if account.coach_id is not None:
        requests = db.exec(
            select(ClientCoachRequest)
            .where(ClientCoachRequest.coach_id == account.coach_id)
        ).all()

        for request in requests:
            relationships = db.exec(
                select(ClientCoachRelationship)
                .where(ClientCoachRelationship.request_id == request.id)
            ).all()

            for relationship in relationships:
                db.delete(relationship)

            db.delete(request)

@router.post("/deactivate", response_model=DeactivateAccountResponse)
def deactivate_account(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Deactivate the current user's account.
    This sets is_active to False and prevents access to protected routes.
    It also notifies affected coaches/clients.
    """
    account = db.get(Account, acc.id)

    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if not account.is_active:
        return DeactivateAccountResponse(
            success=False,
            message="Account is already deactivated.",
        )

    affected_accounts = get_affected_accounts(db, account)

    account.is_active = False
    db.add(account)

    notify_affected_accounts(db, account, affected_accounts)

    delete_client_coach_mappings(db, account)

    db.commit()
    db.refresh(account)

    return DeactivateAccountResponse(
        success=True,
        message="Account deactivated successfully.",
    )

@router.post("/activate", response_model=ActivateAccountResponse)
def activate_account(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_account_even_if_inactive),
):
    """
    Activate the current user's account. This sets is_active to True and allows login/access.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")
    if account.is_active:
        return ActivateAccountResponse(success=False, message="Account is already active.")
    account.is_active = True
    db.add(account)
    db.commit()
    db.refresh(account)
    return ActivateAccountResponse(success=True, message="Account activated successfully.")


@router.patch("/update", response_model=AccountResponse)
def update_account(
    payload: UpdateAccountInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Update mutable fields on the current user's Account: `age`, `email`, `bio`, `pfp_url`, and `gender`.
    Only fields present in the payload are updated.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")

    if payload.name is not None:
        account.name = payload.name
    if payload.age is not None:
        account.age = payload.age
    if payload.email is not None:
        account.email = payload.email
    if payload.bio is not None:
        account.bio = payload.bio
    if payload.pfp_url is not None:
        account.pfp_url = payload.pfp_url
    if payload.gender is not None:
        account.gender = payload.gender

    db.add(account)
    db.commit()
    db.refresh(account)

    # Return the account using the response_model which will exclude sensitive fields
    return account
