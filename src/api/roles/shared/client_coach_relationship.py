from fastapi import APIRouter, HTTPException, Depends
from src.api.dependencies import client_coach_request_context, client_coach_relationship_context

from src.database.session import get_session
from sqlmodel import select
from datetime import date
from src.database.payment.models import Subscription, SubscriptionStatus, BillingCycle, PricingPlan

from src.api.roles.coach.domain import DunderResponse
from src.database.account.models import Notification
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship


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

    if context["other"].is_coach:
        message = "An incoming coach request was rescinded."
        details = f"Request {request.id} was rescinded from potential client."
    elif context["other"].is_client:
        message = f"Your request to hire coach {context['other'].account.name} was rejected."
        details = f"Request {request.id} was rejected by coach."

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
    Deletes a client-coach relationship. Both client and coach can delete the relationshio
    """

    relationship = db.get(ClientCoachRelationship, relationship_id)

    if relationship is None:
        raise HTTPException(404, detail="Relationship not found")

    # notify both parties about termination
    if context["other"].account and context["other"].account.id is not None:
        db.add(Notification(
            account_id=context["other"].account.id,
            fav_category="relationship_termination",
            message=f"Your contract with {context['other'].account.name} was terminated.",
            details=f"Relationship {relationship.id} was ended.",
        ))
    if context["user"].account and context["user"].account.id is not None:
        db.add(Notification(
            account_id=context["user"].account.id,
            fav_category="relationship_termination",
            message=f"You ended the contract with {context['other'].account.name}.",
            details=f"Relationship {relationship.id} was ended.",
        ))
    
    relationship.is_active = False
    db.add(relationship)

    # cancel any subscription tied to this client-coach relationship
    req = db.get(ClientCoachRequest, relationship.request_id)
    if req is not None:
        plan = db.exec(select(PricingPlan).where(PricingPlan.coach_id == req.coach_id)).first()
        if plan:
            sub = db.exec(select(Subscription).where(Subscription.client_id == req.client_id, Subscription.pricing_plan_id == plan.id)).first()
            if sub:
                sub.status = SubscriptionStatus.CANCELED
                sub.canceled_at = date.today()
                db.add(sub)
                # deactivate active billing cycles
                cycles = db.exec(select(BillingCycle).where(BillingCycle.subscription_id == sub.id, BillingCycle.active == True)).all()
                for c in cycles:
                    c.active = False
                    db.add(c)

    db.commit()

    return DunderResponse()

