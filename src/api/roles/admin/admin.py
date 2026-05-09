from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from sqlalchemy import delete
from datetime import datetime, timedelta, timezone, date as date_cls
from typing import List, Literal, Optional

from src.database.session import get_session
from src.database.account.models import Account
from src.database.client.models import Client
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.admin.models import Admin
from src.api.dependencies import get_admin_account, PaginationParams
from src.database.role_management.models import CoachRequest, RolePromotionResolution, Roles
from src.database.payment.models import Invoice
from src.database.coach_client_relationship.models import ClientCoachRelationship, ChatMessage
from src.database.reports.models import CoachReport, ClientReport
from src.database.telemetry.models import ClientTelemetry
from src.api.roles.admin.domain import (
    AdminAccountItem,
    ResolveCoachRequestInput,
    PotentialCoachItem,
    AdminTransactionsResponse,
    AdminEngagementResponse,
    AdminReportItem,
    AdminAnalyticsPoint,
    AdminAnalyticsResponse,
)
from src.api.roles.shared.account import (
    DeactivateAccountResponse,
    ActivateAccountResponse,
    DeleteAccountResponse,
    get_affected_accounts,
    notify_affected_accounts,
    delete_client_coach_mappings,
    purge_account_data,
)

from sqlmodel import func

router = APIRouter(prefix="/roles/admin", tags=["admin"])

def admin_account_role(account: Account) -> str:
    if account.admin_id is not None:
        return "admin"
    if account.coach_id is not None:
        return "coach"
    return "client"

def admin_account_roles(account: Account) -> List[str]:
    roles: List[str] = []
    if account.client_id is not None:
        roles.append("client")
    if account.coach_id is not None:
        roles.append("coach")
    if account.admin_id is not None:
        roles.append("admin")
    return roles or ["client"]

def serialize_admin_account(account: Account) -> AdminAccountItem:
    return AdminAccountItem(
        id=account.id,
        name=account.name,
        email=str(account.email),
        role=admin_account_role(account),
        roles=admin_account_roles(account),
        status="active" if account.is_active else "deactivated",
        is_active=account.is_active,
        is_suspended=account.is_suspended,
        created_at=account.created_at,
        last_active=None,
    )


@router.post("/accounts/{account_id}/suspend", response_model=DeactivateAccountResponse)
def suspend_account(
    account_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    target = db.get(Account, account_id)
    if target is None:
        raise HTTPException(404, detail="Account not found")
    target.is_suspended = True
    db.add(target)
    db.commit()

    affected_accounts = get_affected_accounts(db, target)
    notify_affected_accounts(db, target, affected_accounts)
    delete_client_coach_mappings(db, target)

    db.refresh(target)
    return DeactivateAccountResponse(success=True, message="Account suspended")


@router.post("/accounts/{account_id}/unsuspend", response_model=ActivateAccountResponse)
def unsuspend_account(
    account_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    target = db.get(Account, account_id)
    if target is None:
        raise HTTPException(404, detail="Account not found")
    target.is_suspended = False
    db.add(target)
    db.commit()

    db.refresh(target)
    return ActivateAccountResponse(success=True, message="Account unsuspended")

@router.get("/accounts", response_model=List[AdminAccountItem])
def query_accounts(
    pagination: PaginationParams = Depends(PaginationParams),
    sort_by: Literal["name", "email"] = Query("name", description="Account field to sort by"),
    sort_dir: Literal["asc", "desc"] = Query("asc", description="Sort direction"),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    sort_column = Account.name if sort_by == "name" else Account.email
    sort_expression = sort_column.desc() if sort_dir == "desc" else sort_column.asc()
    accounts = db.exec(
        select(Account)
        .order_by(sort_expression, Account.id.asc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()

    return [serialize_admin_account(account) for account in accounts if account.id is not None]

@router.get("/total_transactions", response_model=AdminTransactionsResponse)
def get_total_transactions(db = Depends(get_session), acc: Account = Depends(get_admin_account)):
    """
    Get all money transacted on the website (sum of all paid invoice amounts minus their outstanding balance)
    """
    
    result = db.exec(select(func.sum(Invoice.amount - Invoice.outstanding_balance))).first()
    total = float(result) if result is not None else 0.0

    return AdminTransactionsResponse(total_transacted=total)


@router.get("/reports", response_model=List[AdminReportItem])
def get_reports(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Platform-wide reports feed for the admin dashboard. Merges:
      - client_report (a coach reporting a client)
      - coach_report  (a client reporting a coach)
    into one chronologically-sorted list, joining each row to the reporter's
    and reported user's display names so the UI can render the
    "X reported Y" headline without further lookups."""
    items: List[AdminReportItem] = []

    # Coach-on-client reports: reporter is the coach, target is the client.
    client_reports = db.exec(select(ClientReport)).all()
    for r in client_reports:
        reporter_name = "Unknown coach"
        reported_name = "Unknown client"
        reported_account_id: Optional[int] = None
        coach_acc = db.exec(select(Account).where(Account.coach_id == r.coach_id)).first()
        if coach_acc:
            reporter_name = coach_acc.name
        client_acc = db.exec(select(Account).where(Account.client_id == r.client_id)).first()
        if client_acc:
            reported_name = client_acc.name
            reported_account_id = client_acc.id
        items.append(AdminReportItem(
            id=r.id,
            kind="coach_on_client",
            reporter_name=reporter_name,
            reported_name=reported_name,
            reported_account_id=reported_account_id,
            reason=r.report_summary or "",
            created_at=r.last_updated,
        ))

    # Client-on-coach reports: reporter is the client, target is the coach.
    coach_reports = db.exec(select(CoachReport)).all()
    for r in coach_reports:
        reporter_name = "Unknown client"
        reported_name = "Unknown coach"
        reported_account_id = None
        client_acc = db.exec(select(Account).where(Account.client_id == r.client_id)).first()
        if client_acc:
            reporter_name = client_acc.name
        coach_acc = db.exec(select(Account).where(Account.coach_id == r.coach_id)).first()
        if coach_acc:
            reported_name = coach_acc.name
            reported_account_id = coach_acc.id
        items.append(AdminReportItem(
            id=r.id,
            kind="client_on_coach",
            reporter_name=reporter_name,
            reported_name=reported_name,
            reported_account_id=reported_account_id,
            reason=r.report_summary or "",
            created_at=r.last_updated,
        ))

    # Newest first, then page.
    items.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    return items[pagination.skip : pagination.skip + pagination.limit]


@router.delete("/reports/{kind}/{report_id}")
def delete_report(
    kind: Literal["coach_on_client", "client_on_coach"],
    report_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Resolve a report by removing it from the feed.
    Used by both Dismiss (admin reviewed and decided no action needed) and the
    Suspend escalation flow (account was suspended, the report itself can now
    go away). The two report tables have independent primary keys so we need
    `kind` plus `id` to pick the right row."""
    model = ClientReport if kind == "coach_on_client" else CoachReport
    target = db.get(model, report_id)
    if target is None:
        raise HTTPException(404, detail="Report not found.")
    db.delete(target)
    db.commit()
    return {"success": True, "message": "Report dismissed."}


@router.get("/platform_engagement", response_model=AdminEngagementResponse)
def get_platform_engagement(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Two engagement aggregates that fill the slots formerly occupied by the
    fake 'this month' / 'active subscriptions' cards on the admin dashboard:
      - Active coach-client pairs (relationships still flagged is_active)
      - Total chat messages ever sent on the platform
    Both come from real tables and don't duplicate any other admin metric."""
    active_pairs = db.exec(
        select(func.count(ClientCoachRelationship.id))
    ).one()

    total_messages = db.exec(select(func.count(ChatMessage.id))).one()

    return AdminEngagementResponse(
        active_coach_client_pairs=int(active_pairs or 0),
        total_messages_sent=int(total_messages or 0),
    )


def _bucket_daily(
    telemetry_dates: List[tuple],  # [(client_id, date)]
    signup_dates: List[date_cls],
    today: date_cls,
    days: int,
) -> List[AdminAnalyticsPoint]:
    """One bucket per day for the last `days` days, oldest → newest. The
    `set` for active users dedupes the same client showing up multiple times
    in a single day (e.g. logging mood + steps + meal)."""
    buckets: dict[date_cls, dict] = {
        today - timedelta(days=i): {"active": set(), "signups": 0}
        for i in range(days - 1, -1, -1)
    }
    for client_id, d in telemetry_dates:
        if d in buckets:
            buckets[d]["active"].add(client_id)
    for d in signup_dates:
        if d in buckets:
            buckets[d]["signups"] += 1
    return [
        AdminAnalyticsPoint(
            label=d.strftime("%b %d"),
            active_users=len(b["active"]),
            new_signups=b["signups"],
        )
        for d, b in sorted(buckets.items())
    ]


def _bucket_weekly(
    telemetry_dates: List[tuple],
    signup_dates: List[date_cls],
    today: date_cls,
    weeks: int,
) -> List[AdminAnalyticsPoint]:
    """One bucket per ISO week. Bucket key = the Monday of that week so
    rollover from Sunday → Monday lands in the next bucket cleanly."""
    def monday_of(d: date_cls) -> date_cls:
        return d - timedelta(days=d.weekday())

    this_week = monday_of(today)
    buckets: dict[date_cls, dict] = {
        this_week - timedelta(weeks=i): {"active": set(), "signups": 0}
        for i in range(weeks - 1, -1, -1)
    }
    for client_id, d in telemetry_dates:
        m = monday_of(d)
        if m in buckets:
            buckets[m]["active"].add(client_id)
    for d in signup_dates:
        m = monday_of(d)
        if m in buckets:
            buckets[m]["signups"] += 1
    return [
        AdminAnalyticsPoint(
            label=f"Wk {m.isocalendar()[1]}",
            active_users=len(b["active"]),
            new_signups=b["signups"],
        )
        for m, b in sorted(buckets.items())
    ]


def _bucket_monthly(
    telemetry_dates: List[tuple],
    signup_dates: List[date_cls],
    today: date_cls,
    months: int,
) -> List[AdminAnalyticsPoint]:
    """One bucket per calendar month. Walk backwards in (year, month) tuples
    to avoid date-arithmetic edge cases at month boundaries."""
    def add_month(y: int, m: int, delta: int) -> tuple:
        idx = (y * 12 + (m - 1)) + delta
        return idx // 12, (idx % 12) + 1

    keys: List[tuple] = [add_month(today.year, today.month, -i) for i in range(months - 1, -1, -1)]
    buckets: dict[tuple, dict] = {k: {"active": set(), "signups": 0} for k in keys}

    for client_id, d in telemetry_dates:
        k = (d.year, d.month)
        if k in buckets:
            buckets[k]["active"].add(client_id)
    for d in signup_dates:
        k = (d.year, d.month)
        if k in buckets:
            buckets[k]["signups"] += 1

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return [
        AdminAnalyticsPoint(
            label=f"{month_names[m - 1]} {y % 100:02d}",
            active_users=len(b["active"]),
            new_signups=b["signups"],
        )
        for (y, m), b in sorted(buckets.items())
    ]


@router.get("/analytics", response_model=AdminAnalyticsResponse)
def get_analytics(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Engagement bar-chart data for the admin dashboard.
    Bucketing strategy: pull the raw rows (telemetry + signups) once across a
    13-month window, then bucket in Python three different ways so the
    frontend can flip Daily/Weekly/Monthly tabs without refetching.
    Active users = COUNT(DISTINCT client_id) from client_telemetry in bucket;
    new signups = COUNT(account.id) whose created_at falls in bucket.
    The two cutoff dates use different tz-handling — ClientTelemetry.date is
    tz-aware UTC, Account.created_at is naive — so each query gets its own."""
    today = datetime.utcnow().date()
    cutoff = today - timedelta(days=400)
    cutoff_aware = datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc)
    cutoff_naive = datetime.combine(cutoff, datetime.min.time())

    # Pull full models (avoids the SQLModel scalar-vs-tuple unpacking
    # ambiguity from selecting individual columns) and reduce to the fields
    # we need before bucketing.
    telemetry_rows = db.exec(
        select(ClientTelemetry).where(ClientTelemetry.date >= cutoff_aware)
    ).all()
    telemetry_dates = [(t.client_id, t.date.date()) for t in telemetry_rows]

    signup_rows = db.exec(
        select(Account).where(Account.created_at >= cutoff_naive)
    ).all()
    signup_dates = [a.created_at.date() for a in signup_rows if a.created_at]

    return AdminAnalyticsResponse(
        # 7 daily / 8 weekly / 6 monthly buckets — sized so each rollup
        # fits cleanly in the chart card without thin slivers or wasted
        # whitespace from empty bookend days.
        daily=_bucket_daily(telemetry_dates, signup_dates, today, days=7),
        weekly=_bucket_weekly(telemetry_dates, signup_dates, today, weeks=8),
        monthly=_bucket_monthly(telemetry_dates, signup_dates, today, months=6),
    )

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


# ─── Admin actions on other accounts ────────────────────────────────────────
# An admin can deactivate/reactivate/delete other users via these routes. Self
# actions go through the shared/account routes — there's an explicit guard
# against using the admin route on your own account so the audit trail stays
# meaningful and to avoid confusion about which path is canonical.

def _block_self_action(target_id: int, current_id: int) -> None:
    if target_id == current_id:
        raise HTTPException(
            400,
            detail="Use the /roles/shared/account routes to act on your own account.",
        )


def _block_last_admin_removal(db: Session, target: Account) -> None:
    """Refuse to remove the only remaining active admin so the platform isn't
    locked out. An "active admin" is an Account with admin_id != NULL and
    is_active = True (other than the target)."""
    if target.admin_id is None:
        return
    remaining = db.exec(
        select(func.count(Account.id))
        .where(
            Account.admin_id.isnot(None),
            Account.is_active == True,  # noqa: E712 — SQLAlchemy expression
            Account.id != target.id,
        )
    ).one()
    if remaining == 0:
        raise HTTPException(409, detail="Cannot remove the last active admin.")


@router.post("/accounts/{account_id}/deactivate", response_model=DeactivateAccountResponse)
def admin_deactivate_account(
    account_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Deactivate another user's account (sets is_active=False, notifies their
    active coach/client peers, and tears down any active client-coach mappings).
    Idempotent — calling on an already-deactivated account is a no-op."""
    _block_self_action(account_id, acc.id)

    target = db.get(Account, account_id)
    if target is None:
        raise HTTPException(404, detail="Account not found.")

    if not target.is_active:
        return DeactivateAccountResponse(
            success=False, message="Account is already deactivated."
        )

    _block_last_admin_removal(db, target)

    affected_accounts = get_affected_accounts(db, target)
    target.is_active = False
    db.add(target)
    notify_affected_accounts(db, target, affected_accounts)
    delete_client_coach_mappings(db, target)
    db.commit()
    db.refresh(target)
    return DeactivateAccountResponse(
        success=True,
        message=f"{target.name}'s account has been deactivated.",
    )


@router.post("/accounts/{account_id}/activate", response_model=ActivateAccountResponse)
def admin_activate_account(
    account_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Reactivate a deactivated user's account."""
    _block_self_action(account_id, acc.id)

    target = db.get(Account, account_id)
    if target is None:
        raise HTTPException(404, detail="Account not found.")

    if target.is_active:
        return ActivateAccountResponse(
            success=False, message="Account is already active."
        )

    target.is_active = True
    db.add(target)
    db.commit()
    db.refresh(target)
    return ActivateAccountResponse(
        success=True,
        message=f"{target.name}'s account has been reactivated.",
    )


@router.delete("/accounts/{account_id}", response_model=DeleteAccountResponse)
def admin_delete_account(
    account_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Permanently delete another user's account and all associated data.
    Same cascade chain as the self-delete route."""
    _block_self_action(account_id, acc.id)

    target = db.get(Account, account_id)
    if target is None:
        raise HTTPException(404, detail="Account not found.")

    _block_last_admin_removal(db, target)

    purge_account_data(db, target)
    db.delete(target)
    db.commit()
    return DeleteAccountResponse(
        success=True,
        message=f"{target.name}'s account has been deleted.",
    )
