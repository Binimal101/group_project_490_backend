from fastapi import APIRouter, HTTPException, Depends
from src.api.dependencies import client_coach_request_context, client_coach_relationship_context

from src.database.session import get_session

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
        message = f"Your request to hire coach {context['other'].id} was rejected."
        details = f"Request {request.id} was rejected by coach."

    n = Notification(
        account_id=context["other"].id,
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

    notification = Notification(
        account_id=context["other"].id,
        fav_category="relationship",
        message="Your client-coach relationship was terminated.",
        details=f"Relationship {relationship.id} was ended.",
    )
    db.add(notification)
    
    relationship.is_active = False
    db.add(relationship)

    db.commit()

    return DunderResponse()

