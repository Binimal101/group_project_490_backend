from fastapi import APIRouter, HTTPException, Depends
from src.api.roles.coach.domain import CreateCoachRequestResponse
from src.api.dependencies import get_coach_account, get_client_account

#models
from src.api.roles.coach.domain import CoachRequestInput, CoachAccountResponse


from src.database.session import get_session
from src.database.account.models import Account
from src.database.coach.models import Coach, CoachCertifications, CoachExperience, CoachAvailability
from src.database.role_management.models import CoachRequest

router = APIRouter(prefix="/roles/coach", tags=["coach"])

@router.post("/request_coach_creation", response_model=CreateCoachRequestResponse)
def create_coach_request(coach_details: CoachRequestInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Creates a coach_request, and a coach record with verified=False, 
    attaches certifications, experiences, and availability
    modifies user account to show coach_id=xxx
    Errors when a user has a coach_id
    Prospective coach should already be a client and have filled out initial survey, otherwise err
    """

    #client err thrown in DI scope
    if acc.coach_id is not None:
        raise HTTPException(409, detail="Cannot create a request for a coach role when one is open, or the role is given")
    
    coach = Coach()
    
    db.add(coach)
    db.add(coach_availability := CoachAvailability())

    #attatch coach qualifications
    if coach_details.certifications is not None:
        for c in coach_details.certifications:
            db.add(c)
    
    if coach_details.experiences is not None:
        for e in coach_details.experiences:
            db.add(e)
        

    db.flush() # runs in db, now coach, c, and e have ids

    for a in coach_details.availabilities:
        a.coach_availability_id = coach_availability.id
        db.add(a)

    if coach_details.certifications is not None:
        for c in coach_details.certifications:
            db.add(CoachCertifications(coach_id=coach.id, certification_id=c.id)) # type: ignore

    if coach_details.experiences is not None:
        for e in coach_details.experiences:
            db.add(CoachExperience(coach_id=coach.id, experience_id=e.id)) # type: ignore

    cr = CoachRequest(coach_id=coach.id) # type: ignore
    db.add(cr)

    acc.coach_id = coach.id #when ctx manager commits, this propogates to persistent layer

    db.commit()

    return CreateCoachRequestResponse(coach_request_id=cr.id, coach_id=coach.id) # type: ignore

@router.post("/me", response_model=CoachAccountResponse)
def me(db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    return CoachAccountResponse(
        base_account=acc,
        coach_account=db.get(Coach, acc.coach_id)
    )