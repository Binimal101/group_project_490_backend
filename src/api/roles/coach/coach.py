from datetime import date

from fastapi import APIRouter, HTTPException, Depends
from src.api.roles.coach.domain import CoachAvailabilityResponse, CreateCoachRequestResponse, UpdateCoachInfoResponse, CoachRequestDeniedResponse, AcceptedClientResponse, WorkoutPlanInput
from src.api.dependencies import get_coach_account, get_client_account, get_admin_account

# query helpers
from sqlmodel import select
from sqlalchemy import delete

#models
from src.api.roles.coach.domain import CoachDeniedRequestInput, CoachRequestInput, CoachAccountResponse, DunderResponse, UpdateCoachInfoInput, ClientCoachRequestInput, WorkoutInput, WorkoutActivityInput

from src.database import coach
from src.database.workouts_and_activities.models import Workout, WorkoutEquiptment, WorkoutActivity, WorkoutPlan, WorkoutPlanActivity
from src.database.coach_client_relationship.models import ClientCoachRequest
from src.database.session import get_session
from src.database.account.models import Account, Availability
from src.database.coach.models import Coach, CoachCertifications, CoachExperience, CoachAvailability, Experience, Certifications
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

# Updating coach request , which includes coach availability, experience, and certifications.
@router.patch("/information", response_model=UpdateCoachInfoResponse)
def update_coach_info(new_coach_details: UpdateCoachInfoInput, db = Depends(get_session), coach_acc: Account = Depends(get_coach_account)):
    """
    Updates coach request information, including certifications, experiences, and availability
    Deletes existing certs, exps, and availabilities and replaces with new ones if the user provides them, otherwise leaves them as is
    Errors when user does not have a coach_id
    """
    
    if coach_acc.id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    
    coach = db.get(Coach, coach_acc.coach_id)

    # coach.coach_availability already stores the id; avoid an extra query
    coach_availability_id = coach.coach_availability
    if new_coach_details.availabilities is not None:
        if coach_availability_id is not None:
            db.exec(delete(Availability).where(Availability.coach_availability_id == coach_availability_id))
        for a in new_coach_details.availabilities:
            a.coach_availability_id = coach_availability_id # type: ignore
            db.add(a)

    if new_coach_details.certifications is not None:
        db.exec(delete(CoachCertifications).where(CoachCertifications.coach_id == coach.id))
        for c in new_coach_details.certifications:
            db.add(c)
        db.flush()
        for c in new_coach_details.certifications:
            db.add(CoachCertifications(coach_id=coach.id, certification_id=c.id)) # type: ignore

    if new_coach_details.experiences is not None:
        db.exec(delete(CoachExperience).where(CoachExperience.coach_id == coach.id))
        for e in new_coach_details.experiences:
            db.add(e)
        db.flush()
        for e in new_coach_details.experiences:
            db.add(CoachExperience(coach_id=coach.id, experience_id=e.id)) # type: ignore

    db.flush()
    db.commit()

    return UpdateCoachInfoResponse(coach_id=coach.id) # type: ignore

@router.delete("/coach_request_denied", response_model=CoachRequestDeniedResponse)
def coach_request_denied(coach_request_info :CoachDeniedRequestInput, db = Depends(get_session), acc: Account = Depends(get_admin_account)):
    """
    Deletes coach request, coach record, certs, exps, and avails, and sets user account coach_id to null
    Errors when user does not have a coach_id
    """
    if acc.admin_id is None:
        raise HTTPException(404, detail="You must be an admin to perform this action")
    
    

    db.exec(delete(Coach).where(Coach.id == coach_request_info.coach_id))
    db.exec(delete(CoachRequest).where(CoachRequest.coach_id == coach_request_info.coach_id))
    
    db.commit()

    return CoachRequestDeniedResponse(coach_id=None) # type: ignore

@router.post("/me", response_model=CoachAccountResponse)
def me(db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    return CoachAccountResponse(
        base_account=acc,
        coach_account=db.get(Coach, acc.coach_id)
    )

@router.post("/create_workout", response_model=DunderResponse)
def create_workout(workout_details: WorkoutInput, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Creates a workout and attaches equiptment if provided
    Errors when user does not have a coach_id
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    
    workout = Workout(
        name=workout_details.name,
        description=workout_details.description,
        instructions=workout_details.instructions,
        workout_type=workout_details.workout_type
    )

    db.add(workout)
    db.flush()

    if workout_details.equipment is not None:
        for e in workout_details.equipment:
            db.add(e)
            db.flush()
            db.add(WorkoutEquiptment(workout_id=workout.id, equiptment_id=e.id)) # type: ignore

    db.commit()

    return DunderResponse()


@router.post("/create_workout_activity", response_model=DunderResponse)
def create_workout_activity(activity_details: WorkoutActivityInput, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Creates a workout activity and attaches it to a workout
    Errors when user does not have a coach_id
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    activity = WorkoutActivity(
        workout_id=activity_details.workout_id,
        intensity_measure=activity_details.intensity_measure,
        intensity_value=activity_details.intensity_value,
        estimated_calories_per_unit_frequency=activity_details.estimated_calories_per_unit_frequency
    )

    db.add(activity)
    db.flush()
    db.commit()

    return DunderResponse()

@router.post("/create_workout_plan", response_model=DunderResponse)
def create_workout_plan(plan_details: WorkoutPlanInput, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Creates a workout plan and attaches workout activities if provided
    Errors when user does not have a coach_id
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    plan = WorkoutPlan(
        strata_name=plan_details.strata_name
    )

    db.add(plan)
    db.flush()

    if plan_details.workout_activities is not None:
        for activity in plan_details.workout_activities:
            db.add(activity)
            db.flush()
            db.add(WorkoutPlanActivity(workout_plan_id=plan.id, workout_activity_id=activity.id)) # type: ignore

    db.commit()

    return DunderResponse()

@router.get("/coach_availability/{coach_id}", response_model=CoachAvailabilityResponse)
def get_coach_availability(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Gets coach availability for a given coach
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Please log in to view coach availability")
    
    coach = db.get(Coach, coach_id)
    if coach is None:
        raise HTTPException(404, detail="Coach not found")
    
    if coach.verified == False:
        raise HTTPException(404, detail="Coach is not verified yet, availability is not viewable")
    
    availabilities = db.exec(select(Availability).where(Availability.coach_availability_id == coach.coach_availability)).all()

    return CoachAvailabilityResponse(coach_availabilities=availabilities)


@router.post("/accept_client_request", response_model=AcceptedClientResponse)
def accept_client_request(request_input : ClientCoachRequestInput, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Accepts a client coach request, creates a client coach relationship row
    Errors when client coach request is not found, or if the request is not for a coach_id that matches the current user's coach_id
    """
    
    request = db.exec(select(ClientCoachRequest).where(ClientCoachRequest.id == request_input.id)).first()
    if request is None:
        raise HTTPException(404, detail="Client coach request not found")
    
    if request.coach_id != acc.coach_id:
        raise HTTPException(403, detail="You are not the owner of this coach request")
    
    if request_input.is_accepted:
        request.is_accepted = True
        db.add(ClientCoachRequest(is_accepted = request.is_accepted, client_id = request.client_id, coach_id = request.coach_id)) # type: ignore
        db.flush()

        return AcceptedClientResponse(client_coach_request_id=request.id, client_id=request.client_id, coach_id=request.coach_id) # type: ignore
