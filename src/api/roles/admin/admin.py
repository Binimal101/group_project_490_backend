from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime

from src.database.session import get_session
from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.admin.models import Admin
from src.api.dependencies import get_admin_account, PaginationParams
from src.database.role_management.models import CoachRequest, RolePromotionResolution, Roles
from src.api.roles.admin.domain import ResolveCoachRequestInput

router = APIRouter(prefix="/roles/admin", tags=["admin"])

@router.get("/query/coach_requests")
def query_coach_requests(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account)
):
    query = select(CoachRequest).where(CoachRequest.role_promotion_resolution_id == None)
    requests = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return requests

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
        
    db.commit()
    
    return {"message": "Coach request resolved successfully", "resolution_id": resolution.id}