from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from src.api.dependencies import get_coach_account, get_client_account, get_admin_account, PaginationParams

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
    PrescribeWorkoutPlanInput,
    PrescribeWorkoutPlanResponse,
    WorkoutActivityItem,
    ClientPlanItem,
)

from src.database import coach
from src.database.payment.models import PricingPlan, Subscription, BillingCycle, Invoice, PricingInterval
from src.database.workouts_and_activities.models import Workout, WorkoutEquiptment, WorkoutActivity, WorkoutPlan, WorkoutPlanActivity
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.session import get_session
from src.database.account.models import Account, Availability, Notification
from src.database.telemetry.models import (
    HealthMetrics,
    ClientTelemetry,
    StepCount,
    CompletedSurvey,
    DailyMoodSurvey,
    DailyWorkoutSurvey,
    DailyBodyMetricsSurvey,
    DailyStepsSurvey,
    DailyMealSurvey,
    CompletedMealActivity,
    CompletedWorkout,
    DailyProgressPicture,
)
from src.database.coach.models import Coach, CoachCertifications, CoachExperience, Experience, Certifications
from src.database.client.models import Client, FitnessGoals, ClientWorkoutPlan
from src.database.role_management.models import CoachRequest
from src.database.reports.models import ClientReport
from src.api.roles.services import (
    create_availability_row,
    create_busy_for_plan,
    create_manual_busy_slot,
    delete_availability_row,
    delete_busy_slot_row,
    list_availability_for_account,
    list_busy_slots_for_account,
    list_scheduled_plans_for_client_in_range,
    remove_busy_for_plan,
    update_availability_row,
    validate_schedulable,
)
from src.api.roles.client.domain import AvailabilityResponse, BusySlotResponse

from sqlmodel import func

router = APIRouter(prefix="/roles/coach", tags=["coach"])


class AvailabilityWindowInput(BaseModel):
    start_dt: datetime
    end_dt: datetime
    repeats_weekly: bool = False
    recurrence_end_dt: Optional[datetime] = None


class BusySlotInput(BaseModel):
    start_dt: datetime
    end_dt: datetime
    note: Optional[str] = None

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

    # attatch coach qualifications
    if coach_details.certifications is not None:
        for c in coach_details.certifications:
            db.add(c)

    if coach_details.experiences is not None:
        for e in coach_details.experiences:
            db.add(e)

    db.flush() # runs in db, now coach, c, and e have ids

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    for a in coach_details.availabilities:
        a.account_id = acc.id
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
    if coach is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    # Availability is managed exclusively through /availability CRUD endpoints

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

    if new_coach_details.specialties is not None:
        coach.specialties = ",".join(new_coach_details.specialties)

    if new_coach_details.pricing_plan is not None:
        pp = new_coach_details.pricing_plan
        # Close existing open plans
        existing_plans = db.exec(
            select(PricingPlan).where(PricingPlan.coach_id == coach.id, PricingPlan.open_to_entry == True)
        ).all()
        for ep in existing_plans:
            ep.open_to_entry = False
            db.add(ep)
        # Create new pricing plan
        new_plan = PricingPlan(
            coach_id=coach.id,  # type: ignore
            payment_interval=pp.payment_interval,
            price_cents=pp.price_cents,
            open_to_entry=True,
        )
        db.add(new_plan)

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

@router.post("/prescribe_plan", response_model=PrescribeWorkoutPlanResponse)
def prescribe_workout_plan(payload: PrescribeWorkoutPlanInput, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Coach prescribes a workout plan to one of their active clients across one or more time blocks.
    Each block becomes its own ClientWorkoutPlan row and a matching BusySlot row.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")

    plan = db.get(WorkoutPlan, payload.workout_plan_id)
    if plan is None:
        raise HTTPException(404, detail="Workout plan not found")

    client = db.get(Client, payload.client_id)
    if client is None:
        raise HTTPException(404, detail="Client not found")

    client_account = db.exec(select(Account).where(Account.client_id == payload.client_id)).first()
    if client_account is None or client_account.id is None:
        raise HTTPException(404, detail="Client account not found")

    request = db.exec(select(ClientCoachRequest).where(
        ClientCoachRequest.client_id == payload.client_id,
        ClientCoachRequest.coach_id == acc.coach_id,
        ClientCoachRequest.is_accepted == True
    )).first()
    if request is None or request.id is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")

    relationship = db.exec(select(ClientCoachRelationship).where(
        ClientCoachRelationship.request_id == request.id,
        ClientCoachRelationship.is_active == True,
    )).first()
    if relationship is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")

    from src.api.roles.shared.blocks import is_blocked_between
    if acc.id is not None and is_blocked_between(db, acc.id, client_account.id):
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")

    # Transfer ownership of the plan to the client (they paid for it)
    if plan.created_by_account_id != client_account.id:
        plan.created_by_account_id = client_account.id
        db.add(plan)

    created_ids = []
    for b in payload.blocks:
        validate_schedulable(db, client_account.id, b.start_dt, b.end_dt)
        cwp = ClientWorkoutPlan(
            client_id=payload.client_id,
            workout_plan_id=payload.workout_plan_id,
            start_time=b.start_dt,
            end_time=b.end_dt,
            repeats_weekly=b.repeats_weekly,
            recurrence_end_dt=b.recurrence_end_dt,
        )
        db.add(cwp)
        db.flush()
        if cwp.id is None:
            raise HTTPException(500, detail="Something went wrong while prescribing the workout plan")
        create_busy_for_plan(db, client_account.id, cwp.id, b.start_dt, b.end_dt)
        created_ids.append(cwp.id)

    if client_account.id is not None:
        db.add(Notification(
            account_id=client_account.id,
            fav_category="workout_plan",
            message=f"{acc.name} prescribed a new workout plan.",
            details=f"A new workout plan has been scheduled across {len(payload.blocks)} session(s). Check your schedule for details.",
        ))

    db.commit()
    return PrescribeWorkoutPlanResponse(client_workout_plan_ids=created_ids)


def _require_active_relationship(db, coach_id: int, client_id: int):
    request = db.exec(select(ClientCoachRequest).where(
        ClientCoachRequest.client_id == client_id,
        ClientCoachRequest.coach_id == coach_id,
        ClientCoachRequest.is_accepted == True
    )).first()
    if request is None or request.id is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")
    relationship = db.exec(select(ClientCoachRelationship).where(
        ClientCoachRelationship.request_id == request.id,
        ClientCoachRelationship.is_active == True,
    )).first()
    if relationship is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")
    return relationship


class CheckSchedulableForClientInput(BaseModel):
    client_id: int
    start_dt: datetime
    end_dt: datetime


@router.post("/check_schedulable_for_client")
def check_schedulable_for_client(
    payload: CheckSchedulableForClientInput,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """Dry-run availability + busy-slot check for a client. Returns 200 or 409."""
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _require_active_relationship(db, acc.coach_id, payload.client_id)
    client_account = db.exec(select(Account).where(Account.client_id == payload.client_id)).first()
    if client_account is None or client_account.id is None:
        raise HTTPException(404, detail="Client account not found")
    validate_schedulable(db, client_account.id, payload.start_dt, payload.end_dt)
    return {"ok": True}


@router.get("/client/{client_id}/availability")
def coach_view_client_availability(
    client_id: int,
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _require_active_relationship(db, acc.coach_id, client_id)

    client_account = db.exec(select(Account).where(Account.client_id == client_id)).first()
    if client_account is None or client_account.id is None:
        raise HTTPException(404, detail="Client account not found")

    return list_availability_for_account(db, client_account.id, from_dt, to_dt)


@router.get("/client/{client_id}/busy_slots")
def coach_view_client_busy_slots(
    client_id: int,
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _require_active_relationship(db, acc.coach_id, client_id)

    client_account = db.exec(select(Account).where(Account.client_id == client_id)).first()
    if client_account is None or client_account.id is None:
        raise HTTPException(404, detail="Client account not found")

    return list_busy_slots_for_account(db, client_account.id, from_dt, to_dt)


@router.get("/client/{client_id}/client_workout_plans")
def coach_view_client_plans(
    client_id: int,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _require_active_relationship(db, acc.coach_id, client_id)

    from datetime import timezone
    now = datetime.now(timezone.utc)
    range_start = from_dt if from_dt is not None else now
    range_end = to_dt if to_dt is not None else now + timedelta(weeks=8)
    return list_scheduled_plans_for_client_in_range(db, client_id, range_start, range_end)


@router.delete("/client_workout_plan/{plan_id}")
def delete_prescribed_plan(plan_id: int, db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """Coach deletes a prescribed plan they have authority over (active relationship)."""
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    cwp = db.get(ClientWorkoutPlan, plan_id)
    if cwp is None:
        raise HTTPException(404, detail="Scheduled plan not found")

    request = db.exec(select(ClientCoachRequest).where(
        ClientCoachRequest.client_id == cwp.client_id,
        ClientCoachRequest.coach_id == acc.coach_id,
        ClientCoachRequest.is_accepted == True
    )).first()
    if request is None or request.id is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")
    relationship = db.exec(select(ClientCoachRelationship).where(
        ClientCoachRelationship.request_id == request.id,
        ClientCoachRelationship.is_active == True,
    )).first()
    if relationship is None:
        raise HTTPException(403, detail="Coach does not have an active relationship with this client")

    remove_busy_for_plan(db, cwp.id)
    db.delete(cwp)
    db.commit()
    return {"details": "deleted"}


@router.get("/coach_availability/{coach_id}")
def get_coach_availability(
    coach_id: int,
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """
    Gets a coach's availability windows over the requested range.
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Please log in to view coach availability")

    coach = db.get(Coach, coach_id)
    if coach is None:
        raise HTTPException(404, detail="Coach not found")

    if coach.verified == False:
        raise HTTPException(404, detail="Coach is not verified yet, availability is not viewable")

    coach_account = db.exec(select(Account).where(Account.coach_id == coach.id)).first()
    if coach_account is None or coach_account.id is None:
        raise HTTPException(404, detail="Coach account not found")

    return list_availability_for_account(db, coach_account.id, from_dt, to_dt)


@router.get("/availability")
def list_self_availability(
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    return list_availability_for_account(db, acc.id, from_dt, to_dt)


@router.post("/availability", response_model=AvailabilityResponse)
def create_self_availability(
    payload: AvailabilityWindowInput,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    row = create_availability_row(
        db,
        acc.id,
        start_dt=payload.start_dt,
        end_dt=payload.end_dt,
        repeats_weekly=payload.repeats_weekly,
        recurrence_end_dt=payload.recurrence_end_dt,
    )
    db.commit()
    return row


@router.put("/availability/{availability_id}", response_model=AvailabilityResponse)
def update_self_availability(
    availability_id: int,
    payload: AvailabilityWindowInput,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    row = update_availability_row(
        db,
        acc.id,
        availability_id,
        start_dt=payload.start_dt,
        end_dt=payload.end_dt,
        repeats_weekly=payload.repeats_weekly,
        recurrence_end_dt=payload.recurrence_end_dt,
    )
    db.commit()
    return row


@router.delete("/availability/{availability_id}")
def delete_self_availability(
    availability_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    delete_availability_row(db, acc.id, availability_id)
    db.commit()
    return {"details": "deleted"}


@router.get("/busy_slots")
def list_self_busy_slots(
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    return list_busy_slots_for_account(db, acc.id, from_dt, to_dt)


@router.post("/busy_slots", response_model=BusySlotResponse)
def create_self_busy_slot(
    payload: BusySlotInput,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    busy_slot = create_manual_busy_slot(db, acc.id, payload.start_dt, payload.end_dt, payload.note)
    db.commit()
    return busy_slot


@router.delete("/busy_slots/{busy_slot_id}")
def delete_self_busy_slot(
    busy_slot_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    delete_busy_slot_row(db, acc.id, busy_slot_id)
    db.commit()
    return {"details": "deleted"}

@router.get("/client_requests", response_model=RequestListResponse)
def get_client_requests(db = Depends(get_session), acc: Account = Depends(get_coach_account)):
    """
    Gets the list of all pending client requests for a given coach.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    # Get pending client requests (is_accepted IS NULL)
    requests = db.query(ClientCoachRequest).filter(
        ClientCoachRequest.coach_id == acc.coach_id,
        ClientCoachRequest.is_accepted.is_(None)  # pending
    ).all()

    items = []
    for r in requests:
        account = db.exec(select(Account).where(Account.client_id == r.client_id)).first()
        fitness_goals = list(db.exec(select(FitnessGoals).where(FitnessGoals.client_id == r.client_id)).all())
        base_account = None
        if account:
            base_account = {"id": account.id, "name": account.name, "email": account.email, "is_active": account.is_active, "gcp_user_id": account.gcp_user_id, "gender": account.gender, "bio": account.bio, "age": account.age, "pfp_url": account.pfp_url, "client_id": account.client_id, "coach_id": account.coach_id, "admin_id": account.admin_id, "created_at": account.created_at}
        items.append({"client_id": r.client_id, "request_id": r.id, "base_account": base_account, "fitness_goals": fitness_goals})

    return items


@router.get("/clients")
def get_my_accepted_clients(
    text: Optional[str] = None,
    skip: int = 0,
    limit: int = 24,
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Returns the coach's accepted clients enriched with account info and primary fitness goal.
    Supports search by name (case-insensitive substring) and pagination.
    Each item: {
      relationship_id, client_id, request_id,
      name, email, age, gender, pfp_url, goal
    }
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")

    # Single SQL pass — join requests → relationship → client → account
    stmt = (
        select(
            ClientCoachRequest.id.label("request_id"),  # type: ignore
            ClientCoachRelationship.id.label("relationship_id"),  # type: ignore
            ClientCoachRequest.client_id.label("client_id"),
            Account.id.label("account_id"),
            Account.name.label("name"),
            Account.email.label("email"),
            Account.age.label("age"),
            Account.gender.label("gender"),
            Account.pfp_url.label("pfp_url"),
        )
        .join(ClientCoachRelationship, ClientCoachRelationship.request_id == ClientCoachRequest.id)
        .join(Account, Account.client_id == ClientCoachRequest.client_id)
        .where(
            ClientCoachRequest.coach_id == acc.coach_id,
            ClientCoachRequest.is_accepted == True,
            ClientCoachRelationship.is_active == True,
        )
    )
    if text:
        stmt = stmt.where(func.lower(Account.name).like(f"%{text.lower()}%"))

    stmt = stmt.order_by(Account.name).offset(skip).limit(limit)
    rows = db.exec(stmt).all()

    items = []
    for r in rows:
        goal_row = db.exec(
            select(FitnessGoals).where(FitnessGoals.client_id == r.client_id).order_by(FitnessGoals.id.desc())
        ).first()
        items.append({
            "relationship_id": r.relationship_id,
            "client_id": r.client_id,
            "request_id": r.request_id,
            "account_id": r.account_id,
            "name": r.name,
            "email": r.email,
            "age": r.age,
            "gender": r.gender,
            "pfp_url": r.pfp_url,
            "goal": goal_row.goal_enum if goal_row and getattr(goal_row, "goal_enum", None) else None,
        })

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
    if account and account.id is not None:
        availabilities = db.exec(select(Availability).where(Availability.account_id == account.id)).all()

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
            message=f"Your request to hire {acc.name} was accepted.",
            details="Your coaching relationship is now active. Expect a billing invoice shortly.",
        )
        db.add(n)

    relationship = ClientCoachRelationship(request_id=request.id, created_at=datetime.utcnow(), is_active=True)
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
        db.add(Notification(account_id=client_account.id, fav_category="payment", message=f"A new invoice of ${amount:.2f} was issued.", details=f"This covers your coaching plan from {billing_cycle.entry_date} to {billing_cycle.end_date}."))
    if coach_account and coach_account.id is not None:
        db.add(Notification(account_id=coach_account.id, fav_category="payment", message=f"{client_account.name} was invoiced ${amount:.2f}.", details=f"This covers the coaching plan from {billing_cycle.entry_date} to {billing_cycle.end_date}."))

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
            message=f"Your request to hire {acc.name} was not accepted.",
            details="You may submit a new request to another coach.",
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

@router.get("/my_clients")
def get_my_clients(
    pagination: PaginationParams = Depends(PaginationParams),
    db = Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Returns all active clients for the logged-in coach.
    Includes Client, Account without password, and telemetry objects.
    """

    if acc.coach_id is None:
        raise HTTPException(403, detail="Coach profile required")

    relationships = db.exec(
        select(ClientCoachRequest, ClientCoachRelationship)
        .join(ClientCoachRelationship, ClientCoachRelationship.request_id == ClientCoachRequest.id)
        .where(
            ClientCoachRequest.coach_id == acc.coach_id,
            ClientCoachRequest.is_accepted.is_(True),
            ClientCoachRelationship.is_active.is_(True),
        )
        .order_by(ClientCoachRequest.last_updated.desc(), ClientCoachRequest.id.desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()

    client_ids = [request.client_id for request, relationship in relationships]
    if not client_ids:
        return []

    client_rows = db.exec(select(Client).where(Client.id.in_(client_ids))).all()
    clients_by_id = {client.id: client for client in client_rows}

    account_rows = db.exec(select(Account).where(Account.client_id.in_(client_ids))).all()
    accounts_by_client_id = {account.client_id: account for account in account_rows}

    telemetry_records = db.exec(
        select(ClientTelemetry)
        .where(ClientTelemetry.client_id.in_(client_ids))
        .order_by(ClientTelemetry.date.desc())
    ).all()

    telemetry_by_client_id: dict[int, list[ClientTelemetry]] = {}
    telemetry_ids: list[int] = []
    for telemetry_record in telemetry_records:
        telemetry_by_client_id.setdefault(telemetry_record.client_id, []).append(telemetry_record)
        if telemetry_record.id is not None:
            telemetry_ids.append(telemetry_record.id)

    def group_by_telemetry_id(rows):
        grouped = {}
        for row in rows:
            grouped.setdefault(row.client_telemetry_id, []).append(row)
        return grouped

    if telemetry_ids:
        health_metrics_by_telemetry = group_by_telemetry_id(
            db.exec(select(HealthMetrics).where(HealthMetrics.client_telemetry_id.in_(telemetry_ids))).all()
        )
        step_counts_by_telemetry = group_by_telemetry_id(
            db.exec(select(StepCount).where(StepCount.client_telemetry_id.in_(telemetry_ids))).all()
        )
        mood_surveys_by_telemetry = group_by_telemetry_id(
            db.exec(select(DailyMoodSurvey).where(DailyMoodSurvey.client_telemetry_id.in_(telemetry_ids))).all()
        )
        workout_surveys_by_telemetry = group_by_telemetry_id(
            db.exec(select(DailyWorkoutSurvey).where(DailyWorkoutSurvey.client_telemetry_id.in_(telemetry_ids))).all()
        )
        body_metrics_surveys_by_telemetry = group_by_telemetry_id(
            db.exec(select(DailyBodyMetricsSurvey).where(DailyBodyMetricsSurvey.client_telemetry_id.in_(telemetry_ids))).all()
        )
        steps_surveys_by_telemetry = group_by_telemetry_id(
            db.exec(select(DailyStepsSurvey).where(DailyStepsSurvey.client_telemetry_id.in_(telemetry_ids))).all()
        )
        meal_surveys_by_telemetry = group_by_telemetry_id(
            db.exec(select(DailyMealSurvey).where(DailyMealSurvey.client_telemetry_id.in_(telemetry_ids))).all()
        )
        completed_meals_by_telemetry = group_by_telemetry_id(
            db.exec(select(CompletedMealActivity).where(CompletedMealActivity.client_telemetry_id.in_(telemetry_ids))).all()
        )
        completed_workouts_by_telemetry = group_by_telemetry_id(
            db.exec(select(CompletedWorkout).where(CompletedWorkout.client_telemetry_id.in_(telemetry_ids))).all()
        )
    else:
        health_metrics_by_telemetry = {}
        step_counts_by_telemetry = {}
        mood_surveys_by_telemetry = {}
        workout_surveys_by_telemetry = {}
        body_metrics_surveys_by_telemetry = {}
        steps_surveys_by_telemetry = {}
        meal_surveys_by_telemetry = {}
        completed_meals_by_telemetry = {}
        completed_workouts_by_telemetry = {}

    clients = []
    for request, relationship in relationships:
        account = accounts_by_client_id.get(request.client_id)
        safe_account = None
        if account:
            safe_account = {
                "id": account.id,
                "name": account.name,
                "email": account.email,
                "is_active": account.is_active,
                "gender": account.gender,
                "bio": account.bio,
                "age": account.age,
                "pfp_url": account.pfp_url,
                "client_id": account.client_id,
                "coach_id": account.coach_id,
                "admin_id": account.admin_id,
                "created_at": account.created_at,
            }

        telemetry = []
        for telemetry_record in telemetry_by_client_id.get(request.client_id, []):
            telemetry_id = telemetry_record.id
            telemetry.append({
                "client_telemetry": telemetry_record,
                "health_metrics": health_metrics_by_telemetry.get(telemetry_id, []),
                "step_counts": step_counts_by_telemetry.get(telemetry_id, []),
                "mood_surveys": mood_surveys_by_telemetry.get(telemetry_id, []),
                "workout_surveys": workout_surveys_by_telemetry.get(telemetry_id, []),
                "body_metrics_surveys": body_metrics_surveys_by_telemetry.get(telemetry_id, []),
                "steps_surveys": steps_surveys_by_telemetry.get(telemetry_id, []),
                "meal_surveys": meal_surveys_by_telemetry.get(telemetry_id, []),
                "completed_meals": completed_meals_by_telemetry.get(telemetry_id, []),
                "completed_workouts": completed_workouts_by_telemetry.get(telemetry_id, []),
            })

        clients.append({
            "relationship_id": relationship.id,
            "request_id": request.id,
            "client": clients_by_id.get(request.client_id),
            "account": safe_account,
            "telemetry": telemetry,
        })

    return clients

# ─── Coach-view client telemetry & schedule ──────────────────────────────────

def _authorize_coach_for_client(db, coach_id: int, client_id: int) -> None:
    """Raise 403 unless the coach has a pending request or active relationship with the client."""
    pending = db.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_id,
            ClientCoachRequest.coach_id == coach_id,
            ClientCoachRequest.is_accepted.is_(None),
        )
    ).first()
    if pending:
        return

    accepted = db.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_id,
            ClientCoachRequest.coach_id == coach_id,
        )
    ).first()
    if accepted:
        rel = db.exec(
            select(ClientCoachRelationship).where(
                ClientCoachRelationship.request_id == accepted.id,
                ClientCoachRelationship.is_active == True,
            )
        ).first()
        if rel:
            return

    raise HTTPException(403, detail="Not authorized to view this client's data")


@router.get(
    "/client_telemetry/{client_id}/weights",
    response_model=list[HealthMetrics],
    tags=["coach", "client-telemetry"],
)
def get_client_weight_history(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated body-weight history for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(HealthMetrics)
        .join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(HealthMetrics.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_telemetry/{client_id}/moods",
    response_model=list[CompletedSurvey],
    tags=["coach", "client-telemetry"],
)
def get_client_mood_history(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated mood / wellbeing survey history for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(CompletedSurvey)
        .join(DailyMoodSurvey, DailyMoodSurvey.completed_survey_id == CompletedSurvey.id)
        .join(ClientTelemetry, DailyMoodSurvey.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(CompletedSurvey.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_telemetry/{client_id}/steps",
    response_model=list[StepCount],
    tags=["coach", "client-telemetry"],
)
def get_client_step_history(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated step-count history for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(StepCount)
        .join(ClientTelemetry, StepCount.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(StepCount.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_telemetry/{client_id}/workouts",
    response_model=list[CompletedWorkout],
    tags=["coach", "client-telemetry"],
)
def get_client_workout_history(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated completed-workout history for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(CompletedWorkout)
        .join(ClientTelemetry, CompletedWorkout.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(CompletedWorkout.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_progress_pictures/{client_id}",
    response_model=list[DailyProgressPicture],
    tags=["coach", "client-telemetry"],
)
def get_client_progress_pictures(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated progress pictures for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(DailyProgressPicture)
        .join(ClientTelemetry, DailyProgressPicture.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(DailyProgressPicture.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_meals/{client_id}",
    response_model=list[CompletedMealActivity],
    tags=["coach", "client-telemetry"],
)
def get_client_meal_history(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return paginated logged-meal history for a specific client.

    The coach must hold a pending request or an active relationship with the
    client. Results are ordered newest first.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    query = (
        select(CompletedMealActivity)
        .join(ClientTelemetry, CompletedMealActivity.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == client_id)
        .order_by(CompletedMealActivity.id.desc())
    )
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get(
    "/client_availability/{client_id}",
    response_model=list[Availability],
    tags=["coach", "client-telemetry"],
)
def get_client_availability(
    client_id: int,
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return the availability slots for a specific client.

    The coach must hold a pending request or an active relationship with the
    client.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    client_account = db.exec(select(Account).where(Account.client_id == client_id)).first()
    if client_account is None or client_account.id is None:
        raise HTTPException(404, detail="Client not found")

    return db.exec(
        select(Availability).where(Availability.account_id == client_account.id)
    ).all()


@router.get(
    "/client_plans/{client_id}",
    response_model=list[ClientPlanItem],
    tags=["coach", "client-telemetry"],
)
def get_client_workout_plans(
    client_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db=Depends(get_session),
    acc: Account = Depends(get_coach_account),
):
    """
    Return the workout plans prescribed to a client, with enriched activity details
    (plan name, sets, reps, intensity) drawn from the linked workout activities.

    The coach must hold a pending request or an active relationship with the
    client. Results are paginated at the plan level.
    """
    if acc.coach_id is None:
        raise HTTPException(404, detail="No coach profile found for this account")
    _authorize_coach_for_client(db, acc.coach_id, client_id)

    client_plans = db.exec(
        select(ClientWorkoutPlan)
        .where(ClientWorkoutPlan.client_id == client_id)
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()

    result: list[ClientPlanItem] = []
    for cwp in client_plans:
        plan = db.get(WorkoutPlan, cwp.workout_plan_id)
        if plan is None:
            continue

        plan_activities = db.exec(
            select(WorkoutPlanActivity).where(
                WorkoutPlanActivity.workout_plan_id == plan.id
            )
        ).all()

        activities: list[WorkoutActivityItem] = []
        for wpa in plan_activities:
            wa = db.get(WorkoutActivity, wpa.workout_activity_id)
            if wa is None:
                continue
            workout = db.get(Workout, wa.workout_id)
            if workout is None:
                continue
            activities.append(
                WorkoutActivityItem(
                    id=wpa.id,
                    name=workout.name,
                    suggested_sets=wpa.planned_sets,
                    suggested_reps=wpa.planned_reps,
                    intensity_value=wa.intensity_value,
                    intensity_measure=wa.intensity_measure,
                )
            )

        result.append(ClientPlanItem(strata_name=plan.strata_name, activities=activities))

    return result
