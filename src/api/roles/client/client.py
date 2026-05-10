from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, UploadFile, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlmodel import Session, select
from sqlalchemy import func, desc, asc, delete


from src.api.dependencies import get_active_account, get_client_account, PaginationParams
from src.api.storage import upload_public_file_to_supabase

#models
from src.api.roles.client.domain import (
    InitialSurveyInput,
    ClientAccountResponse,
    CreateClientResponse,
    DunderResponse,
    UpdateClientInfoInput,
    ClientCoachRequestResponse,
    HirableCoachItem,
    CoachReportResponse,
    ReportsResponse,
    CoachReviewResponse,
    ReviewsResponse,
    MyCoachResponse,
    MyCoachRequestsResponse,
    ClientInvoicesListResponse,
    ClientInvoiceResponse,
    ClientBillingCyclesListResponse,
    ClientBillingCycleResponse,
    AssignWorkoutPlanInput,
    AssignWorkoutPlanResponse,
    CheckSchedulableInput,
    PayInvoiceInput,
    PayInvoiceResponse,
    AvailabilityResponse,
    BusySlotResponse,
)
from src.api.roles.coach.domain import CoachAvailabilityResponse

from src.api.roles.shared.domain import DeleteRequestResponse

from src.database.session import get_session
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.account.models import Account, Availability, Notification
from src.database.client.models import Client, FitnessGoals, ClientWorkoutPlan
from src.database.telemetry.models import (
    HealthMetrics,
    ClientTelemetry,
    StepCount,
    DailyMoodSurvey,
    DailyWorkoutSurvey,
    DailyBodyMetricsSurvey,
    DailyStepsSurvey,
    DailyMealSurvey,
    CompletedMealActivity,
    CompletedWorkout,
    DailyProgressPicture,
)
from src.database.workouts_and_activities.models import WorkoutPlan
from src.api.roles.client.fitness import (
    TELEMETRY_PROGRESS_PICTURE,
    TELEMETRY_WEIGHT,
    create_telemetry_event,
    _get_or_create_daily_telemetry_for_type,
)
from src.api.roles.client.telemetry import compute_calories_today as _compute_calories_today
from src.database.reports.models import CoachReport, CoachReviews
from src.database.payment.models import PaymentInformation, Invoice, BillingCycle, Subscription, PricingPlan
from src.api.roles.services import (
    _fmt_block,
    create_availability_row,
    create_busy_for_plan,
    create_manual_busy_slot,
    delete_availability_row,
    delete_busy_slot_row,
    list_availability_for_account,
    list_busy_slots_for_account,
    notify_coaches_of_client_action,
    update_availability_row,
    validate_schedulable,
)


router = APIRouter(prefix="/roles/client", tags=["client"])


class AvailabilityWindowInput(BaseModel):
    start_dt: datetime
    end_dt: datetime
    repeats_weekly: bool = False
    recurrence_end_dt: Optional[datetime] = None


class BusySlotInput(BaseModel):
    start_dt: datetime
    end_dt: datetime
    note: Optional[str] = None

@router.post("/initial_survey", response_model=CreateClientResponse)
def log_initial_survey(client_details: InitialSurveyInput, db = Depends(get_session), acc: Account = Depends(get_active_account)):
    """
    Creates a client, modifies user account to show client_id=xxx
    Attaches pmt info and fitness goal from initial survey
    Errors when a user has a client_id
    """

    if acc.client_id is not None:
        raise HTTPException(409, detail="Client profile already exists for this account")

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")

    db.add(client_details.payment_information)
    db.flush()

    client = Client(
        payment_information_id=client_details.payment_information.id,
        daily_step_goal=client_details.daily_step_goal or 10000,
        daily_calorie_goal=client_details.daily_calorie_goal or 2000,
    )

    db.add(client)
    db.flush()

    if client.id is None:
        raise HTTPException(500, detail="Something went wrong when adding new client")

    if client_details.age is not None:
        acc.age = client_details.age
    if client_details.gender is not None:
        acc.gender = client_details.gender
    if client_details.bio is not None:
        acc.bio = client_details.bio
    if client_details.pfp_url is not None:
        acc.pfp_url = client_details.pfp_url

    for a in client_details.availabilities:
        a.account_id = acc.id
        db.add(a)

    telem = create_telemetry_event(db, client.id, TELEMETRY_WEIGHT, commit=False)

    client_details.fitness_goals.client_id = client.id  # type: ignore
    db.add(client_details.fitness_goals)

    acc.client_id = client.id

    db.flush()

    if telem.id is None:
        raise HTTPException(500, detail="Something went wrong while creating the telemetry record")

    client_details.initial_health_metric.client_telemetry_id = telem.id

    db.add(client_details.initial_health_metric)

    db.commit()

    return CreateClientResponse(client_id=client.id) # type: ignore



@router.patch("/information", response_model=DunderResponse)
def update_client_information(payload: UpdateClientInfoInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Fitness goals will override current reading
    Health metrics appends new record as client_telemetry
    Payment information is overridden

    Availability is managed exclusively through /availability CRUD endpoints.
    """
    client = db.get(Client, acc.client_id)

    # Fitness goals: replace existing goals for the client
    if payload.fitness_goals:
        db.exec(delete(FitnessGoals).where(FitnessGoals.client_id == client.id))
        payload.fitness_goals.client_id = client.id
        db.add(payload.fitness_goals)

    # Payment information: replace stored payment info
    if payload.payment_information:
        db.add(payload.payment_information)
        db.flush()
        client.payment_information_id = payload.payment_information.id

    # Health metrics: one editable body metric row per local day.
    if payload.health_metrics:
        telem = _get_or_create_daily_telemetry_for_type(db, client.id, TELEMETRY_WEIGHT)
        existing_metrics = db.exec(
            select(HealthMetrics).where(HealthMetrics.client_telemetry_id == telem.id)
        ).first()
        if existing_metrics is not None:
            existing_metrics.weight = payload.health_metrics.weight
            db.add(existing_metrics)
            db.commit()
            return DunderResponse()

        payload.health_metrics.client_telemetry_id = telem.id
        db.add(payload.health_metrics)

    db.commit()

    return DunderResponse()

@router.post("/me", response_model=ClientAccountResponse)
def me(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    client_account = db.get(Client, acc.client_id)

    # fetch latest health metrics (weight, height if present)
    latest_metrics = None
    if acc.client_id is not None:
        query = select(HealthMetrics).join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(HealthMetrics.id.desc())
        latest_metrics = db.exec(query).first()

    weight = None
    height = None
    if latest_metrics:
        weight = getattr(latest_metrics, "weight", None)
        height = getattr(latest_metrics, "height", None)

    return ClientAccountResponse(
        base_account=acc,
        client_account=client_account,
        last_recorded_weight=weight,
        last_recorded_height=height,
    )


@router.get("/dashboard_bundle")
def client_dashboard_bundle(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """One-shot payload for `client_dash.jsx`.

    Replaces nine sequential / parallel calls (me, client/me, calories_today,
    query/steps, query/workouts, query/weights, my_coach, my_coach_requests,
    review/<coach>) with a single round trip. Server-side composition lets us
    reuse the same `acc` row + a single batched Account lookup for the
    coach side, instead of the frontend chaining `my_coach` → `review/<id>`.
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Client profile not found")

    today_date = datetime.utcnow().date()
    client_row = db.get(Client, acc.client_id)

    # ── Latest health metrics (weight + height) ───────────────────────────
    latest_metrics = db.exec(
        select(HealthMetrics)
        .join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
        .order_by(HealthMetrics.id.desc())  # type: ignore
    ).first()
    last_weight = getattr(latest_metrics, "weight", None) if latest_metrics else None
    last_height = getattr(latest_metrics, "height", None) if latest_metrics else None

    # ── Latest step count ─────────────────────────────────────────────────
    latest_step = db.exec(
        select(StepCount)
        .join(ClientTelemetry, StepCount.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
        .order_by(StepCount.id.desc())  # type: ignore
    ).first()

    # ── Today's completed workouts (count only — full list stays on the
    #    paginated /query/workouts endpoint for history views) ────────────
    todays_telemetry_ids = [
        t.id for t in db.exec(
            select(ClientTelemetry)
            .where(ClientTelemetry.client_id == acc.client_id)
            .where(func.date(ClientTelemetry.date) == today_date)
        ).all()
        if t.id is not None
    ]
    todays_workout_count = 0
    if todays_telemetry_ids:
        todays_workout_count = len(db.exec(
            select(CompletedWorkout).where(
                CompletedWorkout.client_telemetry_id.in_(todays_telemetry_ids)  # type: ignore
            )
        ).all())

    # ── Active coach + reviews of that coach (single Account batch) ────────
    coach_payload: Optional[dict] = None
    coach_reviews: list = []
    coach_row_pair = db.exec(
        select(ClientCoachRequest, ClientCoachRelationship)
        .join(
            ClientCoachRelationship,
            ClientCoachRelationship.request_id == ClientCoachRequest.id,
        )
        .where(
            ClientCoachRequest.client_id == acc.client_id,
            ClientCoachRequest.is_accepted.is_(True),
        )
        .order_by(ClientCoachRequest.last_updated.desc(), ClientCoachRequest.id.desc())
    ).first()

    if coach_row_pair is not None:
        coach_request, relationship = coach_row_pair
        coach = db.get(Coach, coach_request.coach_id)
        if coach is not None:
            coach_account = db.exec(
                select(Account).where(Account.coach_id == coach.id)
            ).first()
            from src.api.roles.shared.blocks import is_blocked_between
            blocked = (
                coach_account is not None and coach_account.id is not None and acc.id is not None
                and is_blocked_between(db, acc.id, coach_account.id)
            )
            if not blocked:
                review_rows = db.exec(
                    select(CoachReviews).where(CoachReviews.coach_id == coach.id)
                ).all()
                avg_rating = (
                    sum(float(r.rating or 0) for r in review_rows) / len(review_rows)
                    if review_rows else 0.0
                )
                coach_reviews = list(review_rows)
                coach_payload = {
                    "coach_id": coach.id,
                    "id": coach.id,
                    "verified": coach.verified,
                    "specialties": coach.specialties,
                    "coach_availability": coach.coach_availability,
                    "name": coach_account.name if coach_account else f"Coach #{coach.id}",
                    "email": coach_account.email if coach_account else None,
                    "account_id": coach_account.id if coach_account else None,
                    "specialty": coach.specialties or "Active coach",
                    "relationship_id": relationship.id,
                    # Inline rating so the frontend stops chaining a separate
                    # /review/<coachId> request after my_coach resolves.
                    "avg_rating": round(avg_rating, 2),
                    "review_count": len(review_rows),
                }

    # ── Pending / approved coach requests ─────────────────────────────────
    coach_request_rows = db.exec(
        select(ClientCoachRequest)
        .where(ClientCoachRequest.client_id == acc.client_id)
        .order_by(ClientCoachRequest.id.desc())  # type: ignore
    ).all()
    request_coach_ids = {r.coach_id for r in coach_request_rows}
    coach_accounts_by_coach_id: dict[int, Account] = {}
    if request_coach_ids:
        for a in db.exec(
            select(Account).where(Account.coach_id.in_(request_coach_ids))  # type: ignore
        ).all():
            if a.coach_id is not None:
                coach_accounts_by_coach_id[a.coach_id] = a

    coach_requests_payload = []
    for r in coach_request_rows:
        coach_acc = coach_accounts_by_coach_id.get(r.coach_id)
        coach_requests_payload.append({
            "id": r.id,
            "request_id": r.id,
            "client_id": r.client_id,
            "coach_id": r.coach_id,
            "is_accepted": r.is_accepted,
            "created_at": r.created_at,
            "coach_name": coach_acc.name if coach_acc else f"Coach #{r.coach_id}",
            "coach_pfp_url": coach_acc.pfp_url if coach_acc else None,
            "coach_account_id": coach_acc.id if coach_acc else None,
        })

    return {
        "profile": {
            "base_account": acc,
            "client_account": client_row,
            "last_recorded_weight": last_weight,
            "last_recorded_height": last_height,
        },
        "telemetry_today": {
            # Mirrors the existing /telemetry/calories_today shape so the
            # dashboard's calories card can be wired without reshaping data.
            # Aggregation is delegated to the shared helper to avoid drift.
            **_compute_calories_today(db, acc.client_id, today_date),
            "latest_step_count": latest_step.step_count if latest_step else None,
            "latest_weight": last_weight,
            "todays_workout_count": todays_workout_count,
        },
        "coach": coach_payload,
        "coach_reviews": coach_reviews,
        "coach_requests": coach_requests_payload,
    }


@router.get("/coach_availability/{coach_id}", response_model=CoachAvailabilityResponse)
def get_coach_availability_for_client(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Proxy endpoint for clients to fetch a coach's availability using the client router prefix.
    Mirrors the logic in the coach router so client-side calls to `/roles/client/coach_availability/{coach_id}` work.
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Please log in to view coach availability")

    coach = db.get(Coach, coach_id)
    if coach is None:
        raise HTTPException(404, detail="Coach not found")

    coach_account = db.exec(
        select(Account).where(
            Account.coach_id == coach_id,
            Account.is_active == True,
        )
    ).first()

    if coach_account is None or coach.verified == False:
        raise HTTPException(404, detail="Coach is not verified yet, availability is not viewable")

    availabilities = db.exec(select(Availability).where(Availability.account_id == coach_account.id)).all()

    return CoachAvailabilityResponse(coach_availabilities=availabilities)

@router.post("/assign_plan", response_model=AssignWorkoutPlanResponse)
def assign_workout_plan(payload: AssignWorkoutPlanInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Assigns a workout plan to the authenticated client across one or more time blocks.
    Each block becomes its own ClientWorkoutPlan row sharing the same workout_plan_id.
    Validates every block against the account's date-based availability and any busy slots.
    Blocks may be marked repeats_weekly=True (with an optional recurrence_end_dt).
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Client profile not found")

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")

    plan = db.get(WorkoutPlan, payload.workout_plan_id)
    if plan is None:
        raise HTTPException(404, detail="Workout plan not found")

    created_ids = []
    for b in payload.blocks:
        validate_schedulable(db, acc.id, b.start_dt, b.end_dt)
        cwp = ClientWorkoutPlan(
            client_id=acc.client_id,
            workout_plan_id=payload.workout_plan_id,
            start_time=b.start_dt,
            end_time=b.end_dt,
            repeats_weekly=b.repeats_weekly,
            recurrence_end_dt=b.recurrence_end_dt,
        )
        db.add(cwp)
        db.flush()
        if cwp.id is None:
            raise HTTPException(500, detail="Something went wrong while assigning the workout plan")
        create_busy_for_plan(db, acc.id, cwp.id, b.start_dt, b.end_dt)
        created_ids.append(cwp.id)

    n = len(payload.blocks)
    first = payload.blocks[0]
    notify_coaches_of_client_action(
        db,
        acc.client_id,
        message=f"{acc.name} scheduled '{plan.strata_name}'",
        details=f"{n} session(s) · first block: {_fmt_block(first.start_dt, first.end_dt)}",
    )

    db.commit()
    return AssignWorkoutPlanResponse(client_workout_plan_ids=created_ids)


@router.post("/check_schedulable")
def check_schedulable(
    payload: CheckSchedulableInput,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Dry-run availability + busy-slot check. Returns 200 if the window is schedulable, 409 otherwise."""
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    validate_schedulable(db, acc.id, payload.start_dt, payload.end_dt)
    return {"ok": True}


@router.get("/availability")
def list_client_availability(
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    return list_availability_for_account(db, acc.id, from_dt, to_dt)


@router.post("/availability", response_model=AvailabilityResponse)
def create_client_availability(
    payload: AvailabilityWindowInput,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
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
def update_client_availability(
    availability_id: int,
    payload: AvailabilityWindowInput,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
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
def delete_client_availability(
    availability_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    delete_availability_row(db, acc.id, availability_id)
    db.commit()
    return {"details": "deleted"}


@router.get("/busy_slots")
def list_client_busy_slots(
    from_dt: datetime,
    to_dt: datetime,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    return list_busy_slots_for_account(db, acc.id, from_dt, to_dt)


@router.post("/busy_slots", response_model=BusySlotResponse)
def create_client_busy_slot(
    payload: BusySlotInput,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    busy_slot = create_manual_busy_slot(db, acc.id, payload.start_dt, payload.end_dt, payload.note)
    db.commit()
    return busy_slot


@router.delete("/busy_slots/{busy_slot_id}")
def delete_client_busy_slot(
    busy_slot_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    delete_busy_slot_row(db, acc.id, busy_slot_id)
    db.commit()
    return {"details": "deleted"}


@router.post("/request_coach/{coach_id}", response_model=ClientCoachRequestResponse)
def create_coach_request(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Creates a coach request from a client to a coach. Errors if a pending request already exists
    """
    client = db.get(Client, acc.client_id)
    coach = db.get(Coach, coach_id)

    if coach is None:
        raise HTTPException(404, detail="Coach not found")

    coach_account = db.exec(
        select(Account).where(
            Account.coach_id == coach.id,
            Account.is_active == True,
        )
    ).first()

    if coach_account is None or not coach.verified:
        raise HTTPException(404, detail="Coach not available")

    if coach_account.id == acc.id:
        raise HTTPException(400, detail="You cannot hire yourself as a coach")

    from src.api.roles.shared.blocks import is_blocked_between
    if acc.id is not None and coach_account.id is not None and is_blocked_between(db, acc.id, coach_account.id):
        raise HTTPException(403, detail="Cannot create a coach request with a blocked account")

    existing_request = db.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client.id,
            ClientCoachRequest.coach_id == coach.id,
            ClientCoachRequest.is_accepted == None,
        )
    ).first()

    if existing_request:
        raise HTTPException(409, detail="A pending request to this coach already exists")

    request = ClientCoachRequest(client_id=client.id, coach_id=coach.id, is_accepted=None)
    db.add(request)

    # actually commit
    db.commit()
    db.refresh(request)

    # notify the coach's account that a new request was created
    if coach_account and coach_account.id is not None:
        n = Notification(
            account_id=coach_account.id,
            fav_category="relationship_request_creation",
            message=f"{acc.name} has requested to hire you.",
            details="Review this request to accept or decline.",
        )
        db.add(n)
        db.commit()

    if request.id is None:
        raise HTTPException(500, detail="Something went wrong while creating the coach request")
    
    return ClientCoachRequestResponse(request_id=request.id)


@router.delete("/rescind_request/{request_id}", response_model=DeleteRequestResponse)
def rescind_request(request_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Allows a client to rescind (delete) their pending coach request.
    Notifies the target coach's account that the request was rescinded.
    """
    request = db.get(ClientCoachRequest, request_id)

    if request is None:
        raise HTTPException(404, detail="Request not found")

    if request.client_id != acc.client_id:
        raise HTTPException(403, detail="Not authorized to rescind this request")

    if request.is_accepted is not None:
        raise HTTPException(
            409,
            detail="Cannot rescind a resolved request; use terminate_relationship instead."
        )

    coach_account = db.exec(select(Account).where(Account.coach_id == request.coach_id)).first()

    if coach_account and coach_account.id is not None:
        message = f"{acc.name} has withdrawn their coaching request."
        details = "No further action is needed."
        n = Notification(
            account_id=coach_account.id,
            fav_category="relationship_request_deletion",
            message=message, # type: ignore
            details=details, # type: ignore
        )
        db.add(n)

    db.delete(request)
    db.commit()

    return DeleteRequestResponse()

@router.get("/invoices", response_model=ClientInvoicesListResponse)
def get_client_invoices(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Get all invoices for the current client.
    """
    invoices_list = []
    
    invoices = db.exec(
        select(Invoice, BillingCycle, PricingPlan, Account)
        .join(BillingCycle, Invoice.billing_cycle_id == BillingCycle.id)
        .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
        .join(Account, PricingPlan.coach_id == Account.coach_id)
        .where(Invoice.client_id == acc.client_id)
        .order_by(Invoice.id.desc())
    ).all()

    for inv, cycle, plan, coach_acc in invoices:
        invoices_list.append(ClientInvoiceResponse(
            invoice_id=inv.id,
            amount=inv.amount,
            outstanding_balance=inv.outstanding_balance,
            coach_name=coach_acc.name,
            entry_date=cycle.entry_date,
            end_date=cycle.end_date
        ))

    return ClientInvoicesListResponse(invoices=invoices_list)

@router.get("/current_billing_cycles", response_model=ClientBillingCyclesListResponse)
def get_current_billing_cycles(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Get current billing cycles for the active subscriptions of the current client.
    """
    cycles_list = []
    
    cycles = db.exec(
        select(BillingCycle, PricingPlan, Account)
        .join(Subscription, BillingCycle.subscription_id == Subscription.id)
        .join(PricingPlan, BillingCycle.pricing_plan_id == PricingPlan.id)
        .join(Account, PricingPlan.coach_id == Account.coach_id)
        .where(
            Subscription.client_id == acc.client_id,
            Subscription.status == "active",
            BillingCycle.active == True
        )
        .order_by(BillingCycle.id.desc())
    ).all()

    for cycle, plan, coach_acc in cycles:
        cycles_list.append(ClientBillingCycleResponse(
            coach_name=coach_acc.name,
            entry_date=cycle.entry_date,
            end_date=cycle.end_date,
            active=cycle.active
        ))

    return ClientBillingCyclesListResponse(cycles=cycles_list)

@router.post("/upload_progress_picture")
def upload_progress_picture(
    file: UploadFile,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Upload a progress picture and persist one record per day (upsert).

    Uploads the file to Supabase, then finds or creates today's
    ClientTelemetry row and upserts a DailyProgressPicture record so that
    only one progress picture exists per client per day.  Re-uploading on the
    same day replaces the previous URL.
    """
    public_url = upload_public_file_to_supabase(file, "progress_picture", str(acc.id))

    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry = _get_or_create_daily_telemetry_for_type(
        db,
        acc.client_id,
        TELEMETRY_PROGRESS_PICTURE,
    )

    pic = db.exec(
        select(DailyProgressPicture).where(
            DailyProgressPicture.client_telemetry_id == telemetry.id
        )
    ).first()

    if pic is None:
        pic = DailyProgressPicture(client_telemetry_id=telemetry.id, url=public_url)
        db.add(pic)
    else:
        pic.url = public_url

    db.commit()
    db.refresh(pic)

    return {
        "id": pic.id,
        "client_telemetry_id": telemetry.id,
        "url": pic.url,
        "date": str(telemetry.date),
    }


@router.get("/progress_pictures")
def get_progress_pictures(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """Return all progress pictures for the current client, newest first."""
    rows = db.exec(
        select(DailyProgressPicture, ClientTelemetry)
        .join(ClientTelemetry, DailyProgressPicture.client_telemetry_id == ClientTelemetry.id)
        .where(ClientTelemetry.client_id == acc.client_id)
        .order_by(DailyProgressPicture.id.desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()

    pictures = []
    for pic, telem in rows:
        pictures.append({
            "id": pic.id,
            "client_telemetry_id": telem.id,
            "url": pic.url,
            "date": str(telem.date),
        })

    return pictures


@router.get("/query/hirable_coaches", response_model=List[HirableCoachItem])
def query_hirable_coaches(
    name: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    age_start: Optional[int] = Query(None),
    age_end: Optional[int] = Query(None),
    gender: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("avg_rating"),
    order: Optional[str] = Query("desc"),
    pagination: PaginationParams = Depends(PaginationParams),
    db = Depends(get_session),
    acc: Account = Depends(get_client_account),
):
    """
    Query verified/active coaches by optional filters (name, specialty, age range, gender).
    Sort by `avg_rating` or `rating_count` with `order` asc/desc.
    Returns a list of coaches with `avg_rating` and `rating_count` included.
    """

    # base filters: coach must be verified and account active
    stmt = select(
        Coach.id.label("coach_id"), # type: ignore
        Account.id.label("account_id"), # type: ignore
        Account.name.label("name"),
        Account.email.label("email"),
        Account.age.label("age"),
        Account.gender.label("gender"),
        Coach.specialties.label("specialties"),
        func.count(CoachReviews.id).label("rating_count"),
        func.avg(CoachReviews.rating).label("avg_rating"),
    ).join(Account, Account.coach_id == Coach.id).outerjoin(CoachReviews, CoachReviews.coach_id == Coach.id)

    # filters
    where_clauses = [Account.is_active == True, Coach.verified == True]

    # Hide the caller's own coach role (if they're both client and coach).
    if acc.id is not None:
        where_clauses.append(Account.id != acc.id)

    # Hide accounts the caller has blocked or that have blocked the caller.
    from src.database.account.models import AccountBlock
    if acc.id is not None:
        blocker_ids = [
            row.blocker_id for row in db.exec(
                select(AccountBlock).where(AccountBlock.blockee_id == acc.id)
            ).all()
        ]
        blockee_ids = [
            row.blockee_id for row in db.exec(
                select(AccountBlock).where(AccountBlock.blocker_id == acc.id)
            ).all()
        ]
        excluded_account_ids = set(blocker_ids + blockee_ids)
        if excluded_account_ids:
            where_clauses.append(Account.id.notin_(excluded_account_ids))

    if name:
        where_clauses.append(func.lower(Account.name).like(f"%{name.lower()}%"))

    if specialty:
        # specialties stored as comma-separated string in DB; partial match
        where_clauses.append(func.lower(Coach.specialties).like(f"%{specialty.lower()}%"))

    if age_start is not None:
        where_clauses.append(Account.age >= age_start)
    if age_end is not None:
        where_clauses.append(Account.age <= age_end)
    if gender:
        where_clauses.append(func.lower(Account.gender) == gender.lower())

    stmt = stmt.where(*where_clauses)

    # group and ordering
    stmt = stmt.group_by(Coach.id, Account.id, Account.name, Account.email, Account.age, Account.gender, Coach.specialties)  # Account.id already grouped — included in select

    if sort_by == "rating_count":
        order_expr = desc(func.count(CoachReviews.id)) if order == "desc" else asc(func.count(CoachReviews.id))
        stmt = stmt.order_by(order_expr)
    else:
        # default sort by avg_rating
        order_expr = desc(func.avg(CoachReviews.rating)) if order == "desc" else asc(func.avg(CoachReviews.rating))
        stmt = stmt.order_by(order_expr)

    stmt = stmt.offset(pagination.skip).limit(pagination.limit)

    rows = db.exec(stmt).all()

    # Batch-load every per-coach detail in 3 queries instead of 3 × N. With
    # the default page size of 24 coaches that drops 72 round-trips to 3.
    coach_ids = [r.coach_id for r in rows]
    exps_by_coach: dict[int, list] = {}
    certs_by_coach: dict[int, list] = {}
    pricing_by_coach: dict[int, PricingPlan] = {}
    if coach_ids:
        for coach_id, exp in db.exec(
            select(CoachExperience.coach_id, Experience)  # type: ignore
            .join(Experience, Experience.id == CoachExperience.experience_id)
            .where(CoachExperience.coach_id.in_(coach_ids))  # type: ignore
        ).all():
            exps_by_coach.setdefault(coach_id, []).append(exp)

        for coach_id, cert in db.exec(
            select(CoachCertifications.coach_id, Certifications)  # type: ignore
            .join(Certifications, Certifications.id == CoachCertifications.certification_id)
            .where(CoachCertifications.coach_id.in_(coach_ids))  # type: ignore
        ).all():
            certs_by_coach.setdefault(coach_id, []).append(cert)

        # First pricing plan per coach (matches prior `.first()` semantics).
        for p in db.exec(
            select(PricingPlan).where(PricingPlan.coach_id.in_(coach_ids))  # type: ignore
        ).all():
            pricing_by_coach.setdefault(p.coach_id, p)

    result = []
    for r in rows:
        pricing = pricing_by_coach.get(r.coach_id)
        result.append(
            {
                "coach_id": r.coach_id,
                "account_id": r.account_id,
                "name": r.name,
                "email": r.email,
                "age": r.age,
                "gender": r.gender,
                "specialties": r.specialties,
                "avg_rating": float(r.avg_rating) if r.avg_rating is not None else None,
                "rating_count": int(r.rating_count) if r.rating_count is not None else 0,
                "experiences": exps_by_coach.get(r.coach_id, []),
                "certifications": certs_by_coach.get(r.coach_id, []),
                "payment_interval": pricing.payment_interval.value if pricing else None,
                "price_cents": pricing.price_cents if pricing else None,
            }
        )

    return result


@router.post(
    "/coach_report/{coach_id}",
    response_model=CoachReportResponse,
    deprecated=True,
)
def coach_report(coach_id: int, report_summary: str, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    DEPRECATED — use POST /roles/shared/account/report/{account_id} instead,
    which writes to the unified `account_report` table. This route is kept
    for any clients still pinned to the old contract; it'll be removed in a
    later cleanup once all UI surfaces hit the new endpoint.
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.client_id is None:
        raise HTTPException(403, detail="You are not authorized to use this feature")
    
    report = CoachReport(client_id=acc.client_id, coach_id=coach_id, report_summary=report_summary)

    db.add(report)
    db.flush()
    db.commit()

    if report.id is None:
        raise HTTPException(500, detail="Something went wrong while creating the report")
    
    return CoachReportResponse(report_id=report.id)


@router.get("/reports/{coach_id}", response_model=ReportsResponse)
def get_reports(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Get all the reports from a specific client
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.client_id is None:
        raise HTTPException(403, detail="You are not authorized to view this content")
    
    reports = db.query(CoachReport).filter(CoachReport.coach_id == coach_id).all()

    return ReportsResponse(reports=reports)


@router.post("/coach_review/{coach_id}", response_model=CoachReviewResponse)
def coach_review(coach_id: int, rating: float, review_text: str, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Create a new coach review
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.client_id is None:
        raise HTTPException(403, detail="You are not authorized to use this feature")

    has_relationship = db.exec(
        select(ClientCoachRelationship)
        .join(ClientCoachRequest, ClientCoachRelationship.request_id == ClientCoachRequest.id)
        .where(
            ClientCoachRequest.client_id == acc.client_id,
            ClientCoachRequest.coach_id == coach_id,
        )
    ).first()

    if has_relationship is None:
        raise HTTPException(403, detail="You can only review coaches you have or had a relationship with")

    review = CoachReviews(client_id=acc.client_id, coach_id=coach_id, rating=rating, review_text=review_text)

    db.add(review)
    db.flush()
    db.commit()

    if review.id is None:
        raise HTTPException(500, detail="Something went wrong while creating the review")
    
    return CoachReviewResponse(review_id=review.id)


@router.get("/review/{coach_id}", response_model=ReviewsResponse)
def get_review(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Get all the reports from a specific client
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    if acc.client_id is None:
        raise HTTPException(403, detail="You are not authorized to view this content")

    coach_account = db.exec(
        select(Account).where(
            Account.coach_id == coach_id,
            Account.is_active == True,
        )
    ).first()

    if coach_account is None:
        return ReviewsResponse(reviews=[])

    reviews = db.exec(
        select(CoachReviews).where(CoachReviews.coach_id == coach_id)
    ).all()

    return ReviewsResponse(reviews=reviews)

@router.get("/my_coach")
def get_my_coach(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Returns the coach of a specific client with account information
    """

    if acc is None:
        raise HTTPException(404, detail="Account not found")

    # Active relationship = a ClientCoachRelationship row exists.
    coach_row = db.exec(
        select(ClientCoachRequest, ClientCoachRelationship)
        .join(
            ClientCoachRelationship,
            ClientCoachRelationship.request_id == ClientCoachRequest.id,
        )
        .where(
            ClientCoachRequest.client_id == acc.client_id,
            ClientCoachRequest.is_accepted.is_(True),
        )
        .order_by(ClientCoachRequest.last_updated.desc(), ClientCoachRequest.id.desc())
    ).first()

    if coach_row is None:
        return {"coach": None}

    coach_request, relationship = coach_row

    coach = db.exec(select(Coach).where(Coach.id == coach_request.coach_id)).first()

    if coach is None:
        raise HTTPException(404, detail="Coach not found")

    coach_account = db.exec(select(Account).where(Account.coach_id == coach.id)).first()

    # Hide the relationship if either side has blocked the other.
    from src.api.roles.shared.blocks import is_blocked_between
    if coach_account is not None and coach_account.id is not None and acc.id is not None:
        if is_blocked_between(db, acc.id, coach_account.id):
            return {"coach": None}

    return {
        "coach_id": coach.id,
        "id": coach.id,
        "verified": coach.verified,
        "specialties": coach.specialties,
        "coach_availability": coach.coach_availability,
        "name": coach_account.name if coach_account else f"Coach #{coach.id}",
        "email": coach_account.email if coach_account else None,
        "account_id": coach_account.id if coach_account else None,
        "specialty": coach.specialties or "Active coach",
        "relationship_id": relationship.id,
    }

@router.get("/my_coach_requests", response_model=MyCoachRequestsResponse)
def get_my_coach_requests(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Returns all coach requests for a specific client, enriched with coach names
    """

    if acc is None:
        raise HTTPException(404, detail="Account not found")

    requests = db.query(ClientCoachRequest).filter(ClientCoachRequest.client_id == acc.client_id).all()

    result = []
    for req in requests:
        coach_account = db.exec(select(Account).where(Account.coach_id == req.coach_id)).first()
        coach_name = coach_account.name if coach_account else f"Coach #{req.coach_id}"
        result.append({
            "id": req.id,
            "coach_id": req.coach_id,
            "coach_name": coach_name,
            "is_accepted": req.is_accepted,
            "created_at": req.created_at,
        })

    return MyCoachRequestsResponse(requests=result)

@router.post("/pay_invoice/{invoice_id}", response_model=PayInvoiceResponse)
def pay_invoice(invoice_id: int, payload: PayInvoiceInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Make a payment towards an invoice.
    Verifies the invoice belongs to the authenticated client,
    that the payment amount is valid (> 0 and <= outstanding balance),
    updates the outstanding balance, and notifies the coach.
    """
    invoice = db.get(Invoice, invoice_id)

    if invoice is None:
        raise HTTPException(404, detail="Invoice not found")

    if invoice.client_id != acc.client_id:
        raise HTTPException(403, detail="This invoice does not belong to you")

    if payload.amount > invoice.outstanding_balance:
        raise HTTPException(400, detail=f"Payment amount exceeds outstanding balance of ${invoice.outstanding_balance:.2f}")

    billing_cycle = db.get(BillingCycle, invoice.billing_cycle_id)
    if billing_cycle is None:
        raise HTTPException(404, detail="Billing cycle not found")

    pricing_plan = db.get(PricingPlan, billing_cycle.pricing_plan_id)
    if pricing_plan is None:
        raise HTTPException(404, detail="Pricing plan not found")

    coach_account = db.exec(
        select(Account).where(Account.coach_id == pricing_plan.coach_id)
    ).first()

    if coach_account is None:
        raise HTTPException(404, detail="Coach account not found")

    invoice.outstanding_balance -= payload.amount
    db.add(invoice)
    db.commit()

    notification = Notification(
        account_id=coach_account.id,
        fav_category="payment_received",
        message=f"Payment received from {acc.name}",
        details=f"{acc.name} paid ${payload.amount:.2f} towards their current balance.",
    )
    db.add(notification)
    db.commit()

    return PayInvoiceResponse(
        invoice_id=invoice_id,
        amount_paid=payload.amount,
        remaining_balance=invoice.outstanding_balance,
    )
