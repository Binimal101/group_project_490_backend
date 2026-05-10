from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select
from src.api.dependencies import client_coach_request_context, client_coach_relationship_context

from src.database.session import get_session

from src.api.roles.coach.domain import DunderResponse
from src.database.account.models import Account, Notification
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.api.roles.services import cancel_payments_for_request

from src.api.roles.shared.domain import ClientCoachContext, DeleteRequestResponse
router = APIRouter(prefix="/roles/shared/client_coach_relationship", tags=["shared", "client_coach_relationship"])


@router.delete("/delete_coach_request/{request_id}", response_model=DeleteRequestResponse)
def delete_coach_request(
    request_id: int,
    context: dict[str, ClientCoachContext] = Depends(client_coach_request_context),
    db = Depends(get_session),
):
    """
    Deletes a coach request. Can be used by client to delete pending request, or by coach to reject a pending request
    """
    request = db.get(ClientCoachRequest, request_id)

    if request is None:
        raise HTTPException(404, detail="Request not found")

    if request.is_accepted is not None:
        raise HTTPException(
            409,
            detail="Cannot delete a resolved request; use terminate_relationship instead."
        )

    if context["other"].is_coach:
        message = f"{context['user'].account.name} has withdrawn their coaching request."
        details = "No further action is needed on your end."
    elif context["other"].is_client:
        message = f"Your request to hire {context['user'].account.name} was rejected."
        details = "You may submit a new request to another coach."

    n = Notification(
        account_id=context["other"].account.id,
        fav_category="relationship_request_deletion",
        message=message, # type: ignore
        details=details, # type: ignore
    )

    db.add(n)

    db.delete(request)
    db.commit()

    return DeleteRequestResponse()

@router.post("/terminate_relationship/{relationship_id}", response_model=DunderResponse)
def terminate_relationship(
    relationship_id: int,
    context: dict[str, ClientCoachContext] = Depends(client_coach_relationship_context),
    db = Depends(get_session),
):
    """
    Ends an active relationship by deleting the relationship row and cancelling
    all active subscriptions for the pair. The request row is kept for audit history.
    Row existence is the source of truth for an active relationship.
    """

    relationship = db.get(ClientCoachRelationship, relationship_id)
    if relationship is None:
        raise HTTPException(404, detail="Relationship not found")

    # notify both parties about termination
    if context["other"].account and context["other"].account.id is not None:
        db.add(Notification(
            account_id=context["other"].account.id,
            fav_category="relationship_termination",
            message=f"Your contract with {context['user'].account.name} has been terminated.",
            details="Your coaching relationship has ended. Any active subscriptions have been cancelled.",
        ))
    if context["user"].account and context["user"].account.id is not None:
        db.add(Notification(
            account_id=context["user"].account.id,
            fav_category="relationship_termination",
            message=f"You ended the contract with {context['other'].account.name}.",
            details="Your coaching relationship has ended. Any active subscriptions have been cancelled.",
        ))

    req = db.get(ClientCoachRequest, relationship.request_id)
    if req is not None:
        cancel_payments_for_request(db, req)

    # PRD v2: mark the client's prescribed library entries as revoked. We
    # don't sever the link — the coach can still keep editing their plan and
    # the client will keep seeing updates (default Q-NEW-1 = a, "live forever").
    # `revoked_at` is for the UI's "relationship ended" badge and for any
    # future snapshot/freeze flow we layer on.
    if req is not None:
        from datetime import datetime as _dt
        from src.database.workouts_and_activities.models import (
            PlanLibraryEntry, PlanLibrarySource,
        )
        coach_account = db.exec(
            select(Account).where(Account.coach_id == req.coach_id)
        ).first() if hasattr(req, "coach_id") else None
        client_account = db.exec(
            select(Account).where(Account.client_id == req.client_id)
        ).first() if hasattr(req, "client_id") else None
        if coach_account is not None and client_account is not None:
            entries = db.exec(
                select(PlanLibraryEntry)
                .where(PlanLibraryEntry.account_id == client_account.id)
                .where(PlanLibraryEntry.source == PlanLibrarySource.PRESCRIBED)
                .where(PlanLibraryEntry.source_coach_account_id == coach_account.id)
            ).all()
            now = _dt.utcnow()
            for entry in entries:
                if entry.revoked_at is None:
                    entry.revoked_at = now
                    db.add(entry)

    db.delete(relationship)
    db.commit()

    return DunderResponse()
