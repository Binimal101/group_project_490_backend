from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy import delete
from datetime import datetime
from typing import List

from src.database.session import get_session
from src.database.account.models import Account
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.admin.models import Admin
from src.api.dependencies import get_admin_account, PaginationParams
from src.database.role_management.models import CoachRequest, RolePromotionResolution, Roles
from src.database.payment.models import Invoice
from src.api.roles.admin.domain import ResolveCoachRequestInput, PotentialCoachItem, AdminTransactionsResponse

from sqlmodel import func

router = APIRouter(prefix="/roles/admin", tags=["admin"])

@router.get("/total_transactions", response_model=AdminTransactionsResponse)
def get_total_transactions(db = Depends(get_session), acc: Account = Depends(get_admin_account)):
    """
    Get all money transacted on the website (sum of all paid invoice amounts minus their outstanding balance)
    """
    
    result = db.exec(select(func.sum(Invoice.amount - Invoice.outstanding_balance))).first()
    total = float(result) if result is not None else 0.0

    return AdminTransactionsResponse(total_transacted=total)

@router.get("/query/coach_requests", response_model=List[PotentialCoachItem])
def query_coach_requests(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account)
):
    query = select(CoachRequest).where(CoachRequest.role_promotion_resolution_id == None)
    requests = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    items: List[PotentialCoachItem] = []
    for req in requests:
        coach = db.get(Coach, req.coach_id)

        account = db.exec(select(Account).where(Account.coach_id == coach.id)).first()

        base_account = None
        if account:
            base_account = {
                "id": account.id,
                "name": account.name,
                "email": account.email,
                "is_active": account.is_active,
                "gcp_user_id": account.gcp_user_id,
                "gender": account.gender,
                "bio": account.bio,
                "age": account.age,
                "pfp_url": account.pfp_url,
                "client_id": account.client_id,
                "coach_id": account.coach_id,
                "admin_id": account.admin_id,
                "created_at": account.created_at,
            }

        exps = db.exec(
            select(Experience).join(CoachExperience, CoachExperience.experience_id == Experience.id).where(CoachExperience.coach_id == coach.id)
        ).all()

        certs = db.exec(
            select(Certifications).join(CoachCertifications, CoachCertifications.certification_id == Certifications.id).where(CoachCertifications.coach_id == coach.id)
        ).all()

        items.append(
            PotentialCoachItem(
                coach_request_id=req.id,
                coach_id=coach.id,
                base_account=base_account,
                experiences=exps,
                certifications=certs,
            )
        )

    return items

@router.post("/resolve_coach_request")
def resolve_coach_request(
    payload: ResolveCoachRequestInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account)
):
    # Find the coach request
    req = db.get(CoachRequest, payload.coach_request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Coach request not found")
        
    if req.role_promotion_resolution_id is not None:
        raise HTTPException(status_code=400, detail="Coach request already resolved")
        
    # Get the associated coach
    coach = db.get(Coach, req.coach_id)
    if not coach:
        raise HTTPException(status_code=404, detail="Associated coach not found")
        
    # Find the account that submitted the request
    account = db.exec(select(Account).where(Account.coach_id == coach.id)).first()
    if not account:
        raise HTTPException(status_code=404, detail="Associated account not found")
        
    # Create the resolution
    resolution = RolePromotionResolution(
        role=Roles.COACH,
        admin_id=acc.admin_id,
        account_id=account.id,
        is_approved=payload.is_approved
    )
    db.add(resolution)
    db.flush()
    # Update the request with the resolution id
    req.role_promotion_resolution_id = resolution.id
    db.add(req)

    # If approved, mark the coach as verified
    if payload.is_approved:
        coach.verified = True
        db.add(coach)
    else:
        # If denied: remove the coach record and clear the account's coach_id
        db.exec(delete(Coach).where(Coach.id == coach.id))
        account.coach_id = None
        db.add(account)

    db.commit()

    return {"message": "Coach request resolved successfully", "resolution_id": resolution.id}