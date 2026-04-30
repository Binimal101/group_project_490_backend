import os

import requests
from datetime import date

from fastapi import APIRouter, HTTPException, Depends, UploadFile, Query
from typing import Optional, List
from sqlmodel import select
from sqlalchemy import func, desc, asc, delete

from src import config
from src.api.dependencies import get_account_from_bearer, get_client_account, PaginationParams

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
)

from src.api.roles.shared.domain import DeleteRequestResponse

from src.database.session import get_session
from src.database.coach.models import Coach, Experience, Certifications, CoachExperience, CoachCertifications
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.account.models import Account, Availability, Notification
from src.database.client.models import Client, ClientAvailability, FitnessGoals
from src.database.telemetry.models import HealthMetrics, ClientTelemetry
from src.database.telemetry.models import ClientTelemetry
from src.database.reports.models import CoachReport, CoachReviews
from src.database.payment.models import PaymentInformation, Invoice, BillingCycle, Subscription, PricingPlan


router = APIRouter(prefix="/roles/client", tags=["client"])

@router.post("/initial_survey", response_model=CreateClientResponse)
def log_initial_survey(client_details: InitialSurveyInput, db = Depends(get_session), acc: Account = Depends(get_account_from_bearer)):
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

    telem = ClientTelemetry(client_id=client.id, date=date.today())
    db.add(telem)
    
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

    # Health metrics: append a new telemetry record and attach the metrics
    if payload.health_metrics:
        telem = ClientTelemetry(client_id=client.id, date=date.today())
        db.add(telem)
        db.flush()
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
def upload_progress_picture(file: UploadFile, acc: Account = Depends(get_client_account)):
    """Upload an image to the `progress_picture` bucket and return the public URL.

    This endpoint intentionally does not modify the database yet.
    """

    SUPABASE_URL = config.SUPABASE_URL or os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = config.SUPABASE_SERVICE_KEY or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(500, detail="Supabase storage is not configured on the server")

    bucket = "progress_picture"
    filename = f"{acc.id}_{file.filename}"
    upload_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{filename}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }

    try:
        resp = requests.put(upload_url, data=file.file, headers=headers)
    except Exception as e:
        raise HTTPException(500, detail=f"Upload failed: {e}")

    if resp.status_code not in (200, 201, 204):
        raise HTTPException(resp.status_code, detail=f"Upload failed: {resp.text}")

    public_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{filename}"
    return {"url": public_url}


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
    
    requests = db.get(ClientCoachRequest).filter(ClientCoachRequest.client_id == acc.client_id).all()

    return MyCoachRequestsResponse(requests = requests)
