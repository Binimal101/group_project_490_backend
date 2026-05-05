from fastapi import APIRouter, Depends, UploadFile, HTTPException

from src.database.session import get_session
from src.database.account.models import Account, Availability
from src.database.client.models import Client, FitnessGoals
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.payment.models import PricingPlan
from src.api.dependencies import get_account_from_bearer
from src.api.storage import upload_public_file_to_supabase
from src.api.roles.shared.domain import FullProfileResponse, AccountResponse, UpdateAccountInput
from sqlmodel import Session, select, desc
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/roles/shared/account", tags=["shared", "account"])


@router.get("/me", response_model=FullProfileResponse)
def get_full_profile(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_account_from_bearer),
):
    """
    Returns a unified profile object with account info, roles, and role-specific details
    (fitness goals, availability, coach certifications/experience, etc.)
    """
    roles: List[str] = []
    client_details = None
    coach_details = None

    # Gather roles
    if acc.client_id is not None:
        roles.append("client")
        client = db.get(Client, acc.client_id)
        if client:
            goals = db.exec(select(FitnessGoals).where(FitnessGoals.client_id == client.id)).all()
            availabilities = db.exec(select(Availability).where(Availability.client_availability_id == client.client_availability_id)).all()
            client_details = {
                "id": client.id,
                "fitness_goals": [g.goal_enum for g in goals],
                "availabilities": availabilities
            }
        
    if acc.coach_id is not None:
        coach = db.get(Coach, acc.coach_id)
        if coach:
            if coach.verified:
                roles.append("coach")
            else:
                roles.append("coach_pending_or_denied")
            
            # Fetch coach-specific info
            # Certs
            certs = db.exec(
                select(Certifications)
                .join(CoachCertifications)
                .where(CoachCertifications.coach_id == coach.id)
            ).all()
            
            # Experiences
            exps = db.exec(
                select(Experience)
                .join(CoachExperience)
                .where(Experience.id == CoachExperience.experience_id) # Explicit join condition just in case
                .where(CoachExperience.coach_id == coach.id)
            ).all()
            
            # Availability
            availabilities = db.exec(select(Availability).where(Availability.coach_availability_id == coach.coach_availability)).all()
            
            # Pricing (latest)
            pricing = db.exec(select(PricingPlan).where(PricingPlan.coach_id == coach.id).order_by(desc(PricingPlan.id))).first()

            coach_details = {
                "id": coach.id,
                "verified": coach.verified,
                "specialties": coach.specialties.split(",") if coach.specialties else [],
                "certifications": certs,
                "experiences": exps,
                "availabilities": availabilities,
                "pricing": pricing
            }

    if acc.admin_id is not None:
        roles.append("admin")

    return FullProfileResponse(
        account=acc,
        roles=roles,
        client_details=client_details,
        coach_details=coach_details
    )


@router.post("/update_pfp")
def update_profile_picture(
    file: UploadFile,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_account_from_bearer),
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


@router.post("/deactivate", response_model=DeactivateAccountResponse)
def deactivate_account(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Deactivate the current user's account. This sets is_active to False and prevents login/access.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")
    if not account.is_active:
        return DeactivateAccountResponse(success=False, message="Account is already deactivated.")
    account.is_active = False
    db.add(account)
    db.commit()
    db.refresh(account)
    return DeactivateAccountResponse(success=True, message="Account deactivated successfully.")


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
