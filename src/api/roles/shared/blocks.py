from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, or_

from src.api.dependencies import get_active_account
from src.database.session import get_session

from src.database.account.models import Account, AccountBlock, Notification
from src.database.coach_client_relationship.models import (
    ClientCoachRelationship,
    ClientCoachRequest,
)
from src.api.roles.services import cancel_payments_for_request


router = APIRouter(prefix="/roles/shared/blocks", tags=["shared", "blocks"])


# ─── domain ─────────────────────────────────────────────────────────────────
class BlockResponse(BaseModel):
    blocker_id: int
    blockee_id: int
    cancelled_relationships: int


class BlockedAccountSummary(BaseModel):
    account_id: int
    name: Optional[str] = None
    blocked_at: Optional[str] = None


class BlockedListResponse(BaseModel):
    blocked: list[BlockedAccountSummary]


def is_blocked_between(db, account_a_id: int, account_b_id: int) -> bool:
    """True iff a block row exists in either direction between these accounts."""
    return db.exec(
        select(AccountBlock).where(
            or_(
                (AccountBlock.blocker_id == account_a_id) & (AccountBlock.blockee_id == account_b_id),
                (AccountBlock.blocker_id == account_b_id) & (AccountBlock.blockee_id == account_a_id),
            )
        )
    ).first() is not None


# ─── helpers ────────────────────────────────────────────────────────────────
def _cancel_relationships_between(db, account_a: Account, account_b: Account) -> int:
    """Delete every relationship row between these two accounts (in either direction)
    and cancel any tied subscriptions/billing. Returns the number of relationships ended.
    Row existence is the source of truth for an active relationship.
    """
    candidate_rels: list[ClientCoachRelationship] = []

    if account_a.client_id is not None and account_b.coach_id is not None:
        candidate_rels.extend(
            db.exec(
                select(ClientCoachRelationship)
                .join(ClientCoachRequest, ClientCoachRequest.id == ClientCoachRelationship.request_id)
                .where(
                    ClientCoachRequest.client_id == account_a.client_id,
                    ClientCoachRequest.coach_id == account_b.coach_id,
                )
            ).all()
        )

    if account_a.coach_id is not None and account_b.client_id is not None:
        candidate_rels.extend(
            db.exec(
                select(ClientCoachRelationship)
                .join(ClientCoachRequest, ClientCoachRequest.id == ClientCoachRelationship.request_id)
                .where(
                    ClientCoachRequest.client_id == account_b.client_id,
                    ClientCoachRequest.coach_id == account_a.coach_id,
                )
            ).all()
        )

    cancelled = 0
    for rel in candidate_rels:
        req = db.get(ClientCoachRequest, rel.request_id)
        if req is not None:
            cancel_payments_for_request(db, req)
        db.delete(rel)
        cancelled += 1

    return cancelled


def _coach_has_active_relationship_with_client(db, coach_account: Account, client_account: Account) -> bool:
    """The "no rip-off" check: a coach in an active contract cannot block their client.
    Active = a relationship row exists.
    """
    if coach_account.coach_id is None or client_account.client_id is None:
        return False
    return db.exec(
        select(ClientCoachRelationship)
        .join(ClientCoachRequest, ClientCoachRequest.id == ClientCoachRelationship.request_id)
        .where(
            ClientCoachRequest.coach_id == coach_account.coach_id,
            ClientCoachRequest.client_id == client_account.client_id,
        )
    ).first() is not None


# ─── endpoints ──────────────────────────────────────────────────────────────
@router.post("/{account_id}", response_model=BlockResponse)
def block_account(
    account_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Block another account.

    Side effects:
    - Any active relationship between these two accounts (in either direction) is terminated.
    - The caller cannot block when they are the *coach* in an active relationship with
      the target client (a coach owes service to their paying clients).
    - Idempotent: re-blocking is a no-op (returns 200 with cancelled_relationships=0).
    """
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")
    if acc.id == account_id:
        raise HTTPException(400, detail="Cannot block yourself")

    target = db.get(Account, account_id)
    if target is None or target.id is None:
        raise HTTPException(404, detail="Account not found")

    # If the target has already blocked the caller, the caller cannot retaliate.
    # Block enforcement is one-directional: the first block "wins".
    they_blocked_me = db.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == target.id,
            AccountBlock.blockee_id == acc.id,
        )
    ).first()
    if they_blocked_me is not None:
        raise HTTPException(
            403,
            detail="You cannot block an account that has already blocked you.",
        )

    if _coach_has_active_relationship_with_client(db, acc, target):
        raise HTTPException(
            403,
            detail="Coaches cannot block clients during an active relationship; terminate the contract first.",
        )

    cancelled = _cancel_relationships_between(db, acc, target)

    existing = db.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == acc.id,
            AccountBlock.blockee_id == target.id,
        )
    ).first()
    if existing is None:
        db.add(AccountBlock(blocker_id=acc.id, blockee_id=target.id))

    if cancelled > 0:
        db.add(
            Notification(
                account_id=target.id,
                fav_category="relationship_termination",
                message=f"Your contract with {acc.name} was ended.",
                details="Relationship was terminated as a result of an account block.",
            )
        )

    db.commit()

    return BlockResponse(
        blocker_id=acc.id,
        blockee_id=target.id,
        cancelled_relationships=cancelled,
    )


@router.delete("/{account_id}", response_model=BlockResponse)
def unblock_account(
    account_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Remove a block. Does NOT resurrect any cancelled relationship — those stay terminated."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")
    if acc.id == account_id:
        raise HTTPException(400, detail="Cannot unblock yourself")

    target = db.get(Account, account_id)
    if target is None or target.id is None:
        raise HTTPException(404, detail="Account not found")

    existing = db.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == acc.id,
            AccountBlock.blockee_id == target.id,
        )
    ).first()

    if existing is not None:
        db.delete(existing)
        db.commit()

    return BlockResponse(blocker_id=acc.id, blockee_id=target.id, cancelled_relationships=0)


class BlockStatusResponse(BaseModel):
    partner_id: int
    i_blocked_them: bool
    they_blocked_me: bool


@router.get("/status/{account_id}", response_model=BlockStatusResponse)
def block_status(
    account_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Authoritative block-direction probe between caller and target.
    The frontend should never cache this — always re-fetch when rendering
    chat affordances so unblock state on the other side is visible immediately."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")

    i_blocked_them = db.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == acc.id,
            AccountBlock.blockee_id == account_id,
        )
    ).first() is not None

    they_blocked_me = db.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == account_id,
            AccountBlock.blockee_id == acc.id,
        )
    ).first() is not None

    return BlockStatusResponse(
        partner_id=account_id,
        i_blocked_them=i_blocked_them,
        they_blocked_me=they_blocked_me,
    )


@router.get("", response_model=BlockedListResponse)
def list_blocked_accounts(
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List of accounts the caller has blocked."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")

    rows = db.exec(
        select(AccountBlock, Account)
        .join(Account, Account.id == AccountBlock.blockee_id)
        .where(AccountBlock.blocker_id == acc.id)
    ).all()

    out: list[BlockedAccountSummary] = []
    for block, target in rows:
        out.append(
            BlockedAccountSummary(
                account_id=target.id,  # type: ignore
                name=target.name,
                blocked_at=block.last_updated.isoformat() if block.last_updated else None,
            )
        )

    return BlockedListResponse(blocked=out)
