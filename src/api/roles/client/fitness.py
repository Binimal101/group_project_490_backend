from typing import Optional
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_client_account, PaginationParams
from src.database.client.models import ClientWorkoutPlan

router = APIRouter(prefix="/roles/client/fitness", tags=["client", "fitness"])

@router.get("/query/plans")
def query_client_workout_plans(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    query = select(ClientWorkoutPlan).where(ClientWorkoutPlan.client_id == acc.client_id)
    plans = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return plans
