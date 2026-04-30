from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from src.api.dependencies import get_coach_account, get_client_account, get_admin_account

# query helpers
from sqlmodel import select
from sqlalchemy import delete

#models
from src.api.roles.coach.domain import (
    CoachDeniedRequestInput,
    CoachRequestInput,
    CoachAccountResponse,
    DunderResponse,
    UpdateCoachInfoInput,
    WorkoutInput,
    WorkoutActivityInput,
    CoachAvailabilityResponse,
    CreateCoachRequestResponse,
    UpdateCoachInfoResponse,
    CoachRequestDeniedResponse,
    AcceptedClientResponse,
    WorkoutPlanInput,
    RequestListResponse,
    DeniedClientResponse,
    ClientLookupResponse,
    ClientReportResponse,
    ReportsResponse,
    CoachEarningsResponse,
)

from src.database import coach
from src.database.payment.models import PricingPlan, Subscription, BillingCycle, Invoice, PricingInterval
from src.database.workouts_and_activities.models import Workout, WorkoutEquiptment, WorkoutActivity, WorkoutPlan, WorkoutPlanActivity
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.session import get_session
from src.database.account.models import Account, Availability, Notification
from src.database.telemetry.models import HealthMetrics, ClientTelemetry
from src.database.coach.models import Coach, CoachCertifications, CoachExperience, CoachAvailability, Experience, Certifications
from src.database.client.models import Client, FitnessGoals
from src.database.role_management.models import CoachRequest
from src.database.reports.models import ClientReport

from sqlmodel import func

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

    # attatch coach qualifications
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

    pricing_plan = PricingPlan(coach_id=coach.id, payment_interval=coach_details.payment_interval, price_cents=coach_details.price_cents) # type: ignore
    db.add(pricing_plan)
    db.flush()

    db.commit()

    return CreateCoachRequestResponse(coach_request_id=cr.id, coach_id=coach.id) # type: ignore

# Updating coach request , which includes coach availability, experience, and certifications.
@router.patch("/information", response_model=UpdateCoachInfoResponse)
def update_coach_info(new_coach_details: UpdateCoachInfoInput, db = Depends(get_session), coach_acc: Account = Depends(get_coach_account)):
    """
    Updates coach request + coach information, including certifications, experiences, and availability
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

@router.post("/me", response_model=CoachAccountResponse)
def me(db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    coach_account = db.get(Coach, acc.coach_id)

    # if the account is also a client, fetch latest health metrics
    weight = None
    height = None
    if acc.client_id is not None:
        query = select(HealthMetrics).join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(HealthMetrics.id.desc())
        latest_metrics = db.exec(query).first()
        if latest_metrics:
            weight = getattr(latest_metrics, "weight", None)
            height = getattr(latest_metrics, "height", None)

    return CoachAccountResponse(
        base_account=acc,
        coach_account=coach_account,
        last_recorded_weight=weight,
        last_recorded_height=height,
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

@router.get("/client_requests", response_model=RequestListResponse)
def get_client_requests(db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Gets the list of all client requests for a given coach
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    
    # return pending client requests (is_accepted IS NULL)
    requests = db.query(ClientCoachRequest).filter(
        ClientCoachRequest.coach_id == acc.coach_id,
        ClientCoachRequest.is_accepted.is_(None)  # pending
    ).all()

    items = [{"client_id": r.client_id, "request_id": r.id} for r in requests]

    return items


@router.get("/lookup_client/{client_id}", response_model=ClientLookupResponse)
def lookup_client(client_id: int, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Return detailed client information to a coach only if the coach either
    - has an incoming, non-resolved request from the client (pending), or
    - has an active relationship with the client.

    The response includes account info (excluding password), client role info,
    availabilities and fitness goals — but excludes payment information.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    # Check for a pending request from this client to this coach
    pending_req = db.exec(select(ClientCoachRequest).where(
        ClientCoachRequest.client_id == client_id,
        ClientCoachRequest.coach_id == acc.coach_id,
        ClientCoachRequest.is_accepted.is_(None)
    )).first()

    authorized = False
    if pending_req:
        authorized = True
    else:
        # Check for an active relationship
        req_for_rel = db.exec(select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_id,
            ClientCoachRequest.coach_id == acc.coach_id,
        )).first()
        if req_for_rel:
            rel = db.exec(select(ClientCoachRelationship).where(
                ClientCoachRelationship.request_id == req_for_rel.id,
                ClientCoachRelationship.is_active == True
            )).first()
            if rel:
                authorized = True

    if not authorized:
        raise HTTPException(403, detail="Not authorized to view client details")

    # Fetch client/account and public fields
    account = db.exec(select(Account).where(Account.client_id == client_id)).first()
    client = db.get(Client, client_id)

    availabilities = []
    if client and client.client_availability_id:
        availabilities = db.exec(select(Availability).where(Availability.client_availability_id == client.client_availability_id)).all()

    fitness_goals = db.exec(select(FitnessGoals).where(FitnessGoals.client_id == client_id)).all()

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

    return ClientLookupResponse(
        base_account=base_account,
        client_account=client,
        availabilities=availabilities,
        fitness_goals=fitness_goals,
    )


@router.post("/accept_client/{request_id}", response_model=AcceptedClientResponse)
def accept_coach_request(request_id: int, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Accepts a coach request from a client. Can only be used by coach to accept a pending request
    """
    request = db.get(ClientCoachRequest, request_id)

    if request is None:
        raise HTTPException(404, detail="Request not found")
    
    if request.coach_id != acc.coach_id:
        raise HTTPException(403, detail="Not authorized to accept this request")
    
    # update existing request rather than inserting a new row with the same PK
    request.is_accepted = True
    db.add(request)

    # notify the client that their request was accepted
    client_account = db.exec(select(Account).where(Account.client_id == request.client_id)).first()
    if client_account and client_account.id is not None:
        n = Notification(
            account_id=client_account.id,
            fav_category="relationship",
            message="Your request to hire a coach was accepted.",
            details=f"Request {request.id} was accepted and relationship will be created.",
        )
        db.add(n)

    relationship = ClientCoachRelationship(request_id=request.id, created_at=datetime.utcnow(), is_active=True, coach_blocked=False, client_blocked=False)
    db.add(relationship)
    db.flush()

    pricing_plan = db.query(PricingPlan).filter(PricingPlan.coach_id == request.coach_id).first()

    subscription = Subscription(client_id=request.client_id, pricing_plan_id=pricing_plan.id)
    db.add(subscription)
    db.flush()

    # create initial billing cycle for the subscription
    start = date.today()
    if pricing_plan.payment_interval == PricingInterval.MONTHLY:
        end = start + timedelta(days=30)
    else:
        end = start + timedelta(days=365)

    billing_cycle = BillingCycle(active=True, entry_date=start, end_date=end, subscription_id=subscription.id, pricing_plan_id=pricing_plan.id)
    db.add(billing_cycle)
    db.flush()

    # create initial invoice for the billing cycle
    amount = float(pricing_plan.price_cents) / 100.0
    invoice = Invoice(billing_cycle_id=billing_cycle.id, client_id=request.client_id, amount=amount, outstanding_balance=amount)
    db.add(invoice)

    # notify both client and coach about the new invoice/payment issued
    client_account = db.exec(select(Account).where(Account.client_id == request.client_id)).first()
    coach_account = db.exec(select(Account).where(Account.coach_id == request.coach_id)).first()
    if client_account and client_account.id is not None:
        db.add(Notification(account_id=client_account.id, fav_category="payment", message=f"A new invoice of ${amount:.2f} was issued.", details=f"Invoice {invoice.id} for billing cycle {billing_cycle.id}."))
    if coach_account and coach_account.id is not None:
        db.add(Notification(account_id=coach_account.id, fav_category="payment", message=f"Your client was invoiced ${amount:.2f}.", details=f"Invoice {invoice.id} for client {request.client_id}."))

    db.commit()
    
    if relationship.id is None:
        raise HTTPException(500, detail="Something went wrong when accepting the request")

    return AcceptedClientResponse(relationship_id=relationship.id)

@router.post("/deny_client/{request_id}", response_model=DeniedClientResponse)
def deny_client_request(request_id: int, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Denies a client request from a client. Can only be used by coach to deny a pending request
    """
    request = db.get(ClientCoachRequest, request_id)

    if request is None:
        raise HTTPException(404, detail="Request not found")
    
    if request.coach_id != acc.coach_id:
        raise HTTPException(403, detail="Not authorized to deny this request")
    
    # update existing request to mark as denied
    request.is_accepted = False
    db.add(request)

    # notify the client that their request was denied
    client_account = db.exec(select(Account).where(Account.client_id == request.client_id)).first()
    if client_account and client_account.id is not None:
        n = Notification(
            account_id=client_account.id,
            fav_category="relationship_request_denied",
            message=f"Your request to hire coach {acc.name} was rejected.",
            details=f"Request {request.id} was rejected by the coach.",
        )
        db.add(n)

    db.commit()

    if request.id is None:
        raise HTTPException(500, detail="Something went wrong while denying the request")

    return DeniedClientResponse(relationship_id=request.id)

@router.post("/client_review/{client_id}", response_model=ClientReportResponse)
def client_review(client_id: int, report_summary: str, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Creates a review for a specific client
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.coach_id is None:
        raise HTTPException(403, detail="Not authorized to use this feature")
    
    report = ClientReport(coach_id=acc.coach_id, client_id=client_id, report_summary=report_summary)

    db.add(report)
    db.flush()
    db.commit()

    if report.id is None:
        raise HTTPException(500, detail="Something went wrong while creating the report")
    
    return ClientReportResponse(report_id=report.id)


@router.get("/reports/{client_id}", response_model=ReportsResponse)
def get_reports(client_id: int, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Get all the reports from a specific client
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.coach_id is None:
        raise HTTPException(403, detail="You are not authorized to view this content")
    
    reports = db.query(ClientReport).filter(ClientReport.client_id == client_id).all()

    return ReportsResponse(reports=reports)

@router.get("/earnings", response_model=CoachEarningsResponse)
def get_coach_earnings(
    since: Optional[date] = Query(None, description="Calculate earnings since this date"),
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account)
):
    """
    Calculate the total money made by a coach (amount paid on invoices) optionally since a given date
    """
    if acc.coach_id is None:
        raise HTTPException(403, detail="Not authorized")
    
    # an invoice represents earnings. (Amount - outstanding_balance) is the paid amount.
    query = (
        select(func.sum(Invoice.amount - Invoice.outstanding_balance))
        .select_from(Invoice)
        .join(BillingCycle, Invoice.billing_cycle_id == BillingCycle.id)
        .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
        .where(PricingPlan.coach_id == acc.coach_id)
    )

    if since:
        query = query.where(BillingCycle.entry_date >= since)

    result = db.exec(query).first()
    total = float(result) if result is not None else 0.0

    return CoachEarningsResponse(total_earnings=total, since=since)
