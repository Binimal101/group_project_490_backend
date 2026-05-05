from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List

from src.database.session import get_session
from src.database.account.models import Account, Notification
from src.api.dependencies import PaginationParams, get_active_account

from pydantic import BaseModel
from datetime import date
from typing import Optional

# Local Pydantic models for responses
class NotificationResponse(BaseModel):
    id: int
    account_id: int
    fav_category: Optional[str] = None
    message: str
    details: Optional[str] = None
    is_read: bool
    created_at: date


router = APIRouter(prefix="/roles/shared/notifications", tags=["shared", "notifications"])

@router.get("/query", response_model=List[NotificationResponse])
def query_notifications(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Get a sorted list of the current account's notifications (including id), newest first.
    """
    query = select(Notification).where(Notification.account_id == acc.id).order_by(Notification.created_at.desc(), Notification.id.desc())
    notifications = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return notifications

@router.post("/read/{notification_id}", response_model=NotificationResponse)
def read_notification(
    notification_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Mark a specific notification as read.
    """
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.account_id != acc.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this notification")

    notification.is_read = True
    db.add(notification)
    db.commit()
    db.refresh(notification)

    return notification

@router.post("/read_all", response_model=dict)
def read_all_notifications(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Mark all notifications for the current account as read.
    """
    notifications = db.exec(select(Notification).where(Notification.account_id == acc.id, Notification.is_read == False)).all()
    for notification in notifications:
        notification.is_read = True
        db.add(notification)
    
    db.commit()
    return {"message": f"{len(notifications)} notifications marked as read"}

