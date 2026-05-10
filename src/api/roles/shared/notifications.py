from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from sqlalchemy import func
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


class NotificationSnapshotResponse(BaseModel):
    """Bundle reply for the inbox header / bell.

    Fields:
      total_count    — total notifications for this account (any state).
      unread_count   — unread bell-counter; renders the red dot.
      categories     — count per fav_category, both unread and total.
      recent         — newest N notifications, full rows (default 25).
                       For older history call /query with skip+limit.
    """
    total_count: int
    unread_count: int
    categories: dict
    recent: List[NotificationResponse]


router = APIRouter(prefix="/roles/shared/notifications", tags=["shared", "notifications"])


@router.get("/snapshot", response_model=NotificationSnapshotResponse)
def notifications_snapshot(
    recent_limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """One-call inbox payload: counts + a recent slice.

    Replaces the dashboard's old pattern of (a) `/query` for the list, then
    (b) a separate count derive on the client. The snapshot powers the bell
    badge AND the dropdown's first page in a single round trip; older pages
    fall through to `/query` with a `skip` cursor.
    """
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")

    base = select(Notification).where(Notification.account_id == acc.id)

    # Aggregates: doing them here means we don't reload the row set in JS.
    total_count = db.exec(
        select(func.count()).select_from(Notification).where(Notification.account_id == acc.id)
    ).one()
    unread_count = db.exec(
        select(func.count()).select_from(Notification).where(
            Notification.account_id == acc.id,
            Notification.is_read == False,  # noqa: E712
        )
    ).one()

    # Per-category breakdown (e.g. relationship vs payment vs plan_changed).
    category_rows = db.exec(
        select(Notification.fav_category, Notification.is_read, func.count())  # type: ignore
        .where(Notification.account_id == acc.id)
        .group_by(Notification.fav_category, Notification.is_read)
    ).all()
    categories: dict = {}
    for cat, is_read, cnt in category_rows:
        slot = categories.setdefault(cat or "uncategorized", {"total": 0, "unread": 0})
        slot["total"] += int(cnt)
        if not is_read:
            slot["unread"] += int(cnt)

    recent = db.exec(
        base.order_by(Notification.created_at.desc(), Notification.id.desc())  # type: ignore
            .limit(recent_limit)
    ).all()

    return NotificationSnapshotResponse(
        total_count=int(total_count or 0),
        unread_count=int(unread_count or 0),
        categories=categories,
        recent=recent,
    )


@router.get("/query", response_model=List[NotificationResponse])
def query_notifications(
    only_unread: bool = False,
    category: Optional[str] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Paginated/filtered notifications. Use this for the "see all" page or
    category-scoped views; for the dashboard's bell badge use /snapshot.
    """
    query = select(Notification).where(Notification.account_id == acc.id)
    if only_unread:
        query = query.where(Notification.is_read == False)  # noqa: E712
    if category:
        query = query.where(Notification.fav_category == category)
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc())  # type: ignore
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

