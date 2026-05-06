from fastapi import APIRouter, HTTPException, Depends, UploadFile, Query
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
)

from src.api.roles.shared.domain import DeleteRequestResponse

from src.database.session import get_session
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.account.models import Account, Availability, Notification
from src.database.client.models import Client, ClientAvailability, FitnessGoals, ClientWorkoutPlan
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
)
from src.database.workouts_and_activities.models import WorkoutPlan
from src.api.roles.client.fitness import (
    TELEMETRY_PROGRESS_PICTURE,
    TELEMETRY_WEIGHT,
    create_telemetry_event,
    _get_or_create_daily_telemetry_for_type,
)
from src.database.reports.models import CoachReport, CoachReviews
from src.database.payment.models import PaymentInformation, Invoice, BillingCycle, Subscription, PricingPlan


router = APIRouter(prefix="/roles/client", tags=["client"])

@router.post("/initial_survey", response_model=CreateClientResponse)
def log_initial_survey(client_details: InitialSurveyInput, db = Depends(get_session), acc: Account = Depends(get_active_account)):
    """
    Creates a client, modifies user account to show client_id=xxx
    Attaches pmt info and fitness goal from initial survey
    Errors when a user has a client_id
    """

    if acc.client_id is not None:
        raise HTTPException(409, detail="Client profile already exists for this account")

    db.add(client_details.payment_information)
    for availability in client_details.availabilities:
        db.add(availability)
    
    db.flush()

    client_availability = ClientAvailability()
    db.add(client_availability)
    db.flush()

    for a in client_details.availabilities:
        a.client_availability_id = client_availability.id

    client = Client(
        payment_information_id=client_details.payment_information.id,
        client_availability_id=client_availability.id,
    )

    db.add(client)
    db.flush()

    if client.id is None:
        raise HTTPException(500, detail="Something went wrong when adding new client")

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
    Availabilities: will override current availabilities (delete old records, create new ones)
    Fitness goals will override current reading
    Health metrics appends new record as client_telemetry
    Payment information is overridden

    """
    client = db.get(Client, acc.client_id)

    # Availabilities: delete existing and replace with new ones
    if payload.availabilities:
        ca_id = client.client_availability_id
        if ca_id is None:
            ca = ClientAvailability()
            db.add(ca)
            db.flush()
            client.client_availability_id = ca.id
            ca_id = ca.id
        else:
            db.exec(delete(Availability).where(Availability.client_availability_id == ca_id))

        for a in payload.availabilities:
            a.client_availability_id = ca_id
            db.add(a)

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

@router.post("/assign_plan", response_model=AssignWorkoutPlanResponse)
def assign_workout_plan(payload: AssignWorkoutPlanInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Assigns a workout plan to the authenticated client.
    """
    if acc.client_id is None:
        raise HTTPException(404, detail="Client profile not found")

    plan = db.get(WorkoutPlan, payload.workout_plan_id)
    if plan is None:
        raise HTTPException(404, detail="Workout plan not found")

    client_workout_plan = ClientWorkoutPlan(
        client_id=acc.client_id,
        workout_plan_id=payload.workout_plan_id,
        start_time=payload.start_dt,
        end_time=payload.end_dt
    )
    db.add(client_workout_plan)
    db.commit()
    db.refresh(client_workout_plan)

    if client_workout_plan.id is None:
        raise HTTPException(500, detail="Something went wrong while assigning the workout plan")

    return AssignWorkoutPlanResponse(client_workout_plan_id=client_workout_plan.id)



@router.post("/request_coach/{coach_id}", response_model=ClientCoachRequestResponse)
def create_coach_request(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Creates a coach request from a client to a coach. Errors if a pending request already exists
    """
    client = db.get(Client, acc.client_id)
    coach = db.get(Coach, coach_id)

    if coach is None:
        raise HTTPException(404, detail="Coach not found")
    
    existing_request = db.query(ClientCoachRequest).filter_by(
        client_id=client.id, coach_id=coach.id, is_accepted=None
    ).first()

    if existing_request:
        raise HTTPException(409, detail="A pending request to this coach already exists")

    request = ClientCoachRequest(client_id=client.id, coach_id=coach.id, is_accepted=None)
    db.add(request)

    # actually commit
    db.commit()
    db.refresh(request)

    # notify the coach's account that a new request was created
    coach_account = db.exec(select(Account).where(Account.coach_id == coach.id)).first()
    if coach_account and coach_account.id is not None:
        n = Notification(
            account_id=coach_account.id,
            fav_category="relationship_request_creation",
            message=f"{acc.name} has requested to hire you.",
            details=f"Request {request.id} from client {client.id} to coach {coach.id}.",
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

    coach_account = db.exec(select(Account).where(Account.coach_id == request.coach_id)).first()

    if coach_account and coach_account.id is not None:
        message = "An incoming coach request was rescinded."
        details = f"Request {request.id} was rescinded by the client."
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
    stmt = stmt.group_by(Coach.id, Account.id, Account.name, Account.email, Account.age, Account.gender, Coach.specialties)

    if sort_by == "rating_count":
        order_expr = desc(func.count(CoachReviews.id)) if order == "desc" else asc(func.count(CoachReviews.id))
        stmt = stmt.order_by(order_expr)
    else:
        # default sort by avg_rating
        order_expr = desc(func.avg(CoachReviews.rating)) if order == "desc" else asc(func.avg(CoachReviews.rating))
        stmt = stmt.order_by(order_expr)

    stmt = stmt.offset(pagination.skip).limit(pagination.limit)

    rows = db.exec(stmt).all()

    result = []
    for r in rows:
        # fetch experiences and certifications for this coach
        exps = db.exec(
            select(Experience).join(CoachExperience, CoachExperience.experience_id == Experience.id).where(CoachExperience.coach_id == r.coach_id)
        ).all()
        certs = db.exec(
            select(Certifications).join(CoachCertifications, CoachCertifications.certification_id == Certifications.id).where(CoachCertifications.coach_id == r.coach_id)
        ).all()

        result.append(
            {
                "coach_id": r.coach_id,
                "name": r.name,
                "email": r.email,
                "age": r.age,
                "gender": r.gender,
                "specialties": r.specialties,
                "avg_rating": float(r.avg_rating) if r.avg_rating is not None else None,
                "rating_count": int(r.rating_count) if r.rating_count is not None else 0,
                "experiences": exps,
                "certifications": certs,
            }
        )

    return result


@router.post("/coach_report/{coach_id}", response_model=CoachReportResponse)
def coach_report(coach_id: int, report_summary: str, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Create a new coach report
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
    
    reviews = db.query(CoachReviews).filter(CoachReviews.coach_id == coach_id).all()

    return ReviewsResponse(reviews=reviews)

@router.get("/my_coach", response_model=MyCoachResponse)
def get_my_coach(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Returns the coach of a specific client
    """

    if acc is None:
        raise HTTPException(404, detail="Account not found")
    
    coach_request = db.query(ClientCoachRequest).filter(ClientCoachRequest.client_id == acc.client_id).first()

    if not coach_request.is_accepted:
        raise HTTPException(403, detail="You are not authorized to see this coach until the request is accepted")
    
    relationship = db.query(ClientCoachRelationship).filter(ClientCoachRelationship.request_id == coach_request.id).first()

    if relationship is None:
        raise HTTPException(404, detail="Relationship not Found")
    
    coach = db.query(Coach).filter(Coach.id == coach_request.coach_id).first()

    return MyCoachResponse(coach = coach)

@router.get("/my_coach_requests", response_model=MyCoachRequestsResponse)
def get_my_coach_requests(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Returns all coach requests for a specific client
    """

    if acc is None:
        raise HTTPException(404, detail="Account not found")
    
    requests = db.get(ClientCoachRequest, acc.client_id).all()

    return MyCoachRequestsResponse(requests = requests)

@router.get("/coach_profile/{coach_id}")
def get_coach_profile(coach_id: int, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Allows a client to view a coach's profile given their ID.
    Returns account basics, specialties, certifications, experiences,
    pricing/payment plan, availability, and rating summary.
    """

    coach = db.get(Coach, coach_id)

    if coach is None:
        raise HTTPException(404, detail="Coach not found")

    coach_account = db.exec(
        select(Account).where(Account.coach_id == coach_id)
    ).first()

    if coach_account is None:
        raise HTTPException(404, detail="Coach account not found")

    certifications = db.exec(
        select(Certifications)
        .join(CoachCertifications, CoachCertifications.certification_id == Certifications.id)
        .where(CoachCertifications.coach_id == coach_id)
    ).all()

    experiences = db.exec(
        select(Experience)
        .join(CoachExperience, CoachExperience.experience_id == Experience.id)
        .where(CoachExperience.coach_id == coach_id)
    ).all()

    availability = db.exec(
        select(Availability).where(
            Availability.coach_availability_id == coach.coach_availability
        )
    ).all()

    pricing_plan = db.exec(
        select(PricingPlan).where(PricingPlan.coach_id == coach_id)
    ).first()

    rating_summary = db.exec(
        select(
            func.count(CoachReviews.id).label("rating_count"),
            func.avg(CoachReviews.rating).label("avg_rating"),
        ).where(CoachReviews.coach_id == coach_id)
    ).first()

    return {
        "base_account": {
            "id": coach_account.id,
            "name": coach_account.name,
            "email": coach_account.email,
            "is_active": coach_account.is_active,
            "status": coach_account.status,
            "gender": coach_account.gender,
            "bio": coach_account.bio,
            "age": coach_account.age,
            "pfp_url": coach_account.pfp_url,
            "client_id": coach_account.client_id,
            "coach_id": coach_account.coach_id,
            "admin_id": coach_account.admin_id,
            "created_at": coach_account.created_at,
        },
        "coach_account": coach,
        "specialties": coach.specialties,
        "certifications": certifications,
        "experiences": experiences,
        "pricing_plan": pricing_plan,
        "availability": availability,
        "rating_summary": {
            "rating_count": int(rating_summary.rating_count or 0),
            "avg_rating": float(rating_summary.avg_rating) if rating_summary.avg_rating is not None else None,
        },
    }


@router.get("/progress_pictures")
def get_progress_pictures(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Queries progress picture URLs for the logged-in client.
    Progress pictures are stored in HealthMetrics.progress_pic_url.
    """

    if acc.client_id is None:
        raise HTTPException(403, detail="Client profile required")

    pictures = db.exec(
        select(
            ClientTelemetry.date,
            HealthMetrics.progress_pic_url,
        )
        .join(HealthMetrics, HealthMetrics.client_telemetry_id == ClientTelemetry.id)
        .where(
            ClientTelemetry.client_id == acc.client_id,
            HealthMetrics.progress_pic_url.is_not(None),
        )
        .order_by(ClientTelemetry.date.desc())
    ).all()

    return [
        {
            "date": pic.date,
            "progress_pic_url": pic.progress_pic_url,
        }
        for pic in pictures
    ]


@router.get("/my_coach")
def get_my_coach(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Returns the active coach relationship for the logged-in client.
    """

    if acc.client_id is None:
        raise HTTPException(403, detail="Client profile required")

    result = db.exec(
        select(ClientCoachRequest, ClientCoachRelationship)
        .join(ClientCoachRelationship, ClientCoachRelationship.request_id == ClientCoachRequest.id)
        .where(
            ClientCoachRequest.client_id == acc.client_id,
            ClientCoachRequest.is_accepted == True,
            ClientCoachRelationship.is_active == True,
            ClientCoachRelationship.client_blocked == False,
            ClientCoachRelationship.coach_blocked == False,
        )
    ).first()

    if result is None:
        raise HTTPException(404, detail="No active coach relationship found")

    request, relationship = result

    return {
        "relationship_id": relationship.id,
        "request_id": request.id,
        "client_id": request.client_id,
        "coach_id": request.coach_id,
        "created_at": relationship.created_at,
        "is_active": relationship.is_active,
    }