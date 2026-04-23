from src.api.roles.client.fitness import APIRouter, PaginationParams, Session, _get_or_create_telemetry, datetime, select
from src.database.telemetry.models import ClientTelemetry, CompletedMealActivity, HealthMetrics, StepCount, CompletedSurvey, DailyMoodSurvey, CompletedWorkout
from src.api.roles.client.domain import StepCountUpdateInput, StepCountUpdateOutput, WeightUpdateInput
from src.database.session import get_session
from src.database.account.models import Account
from fastapi import Depends, HTTPException
from src.api.dependencies import get_client_account

today = datetime.utcnow().date()

router = APIRouter(prefix="/roles/client/telemetry", tags=["client", "telemetry"])

@router.put("/update_steps")
def update_steps(step_count: StepCountUpdateInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry = _get_or_create_telemetry(db, acc.client_id)
    
    step_count_entry = db.exec(select(StepCount).where(StepCount.client_telemetry_id == telemetry.id)).first()
    if not step_count_entry:
        step_count_entry = StepCount(step_count=step_count.step_count, client_telemetry_id=telemetry.id)
        db.add(step_count_entry)
    else:
        step_count_entry.step_count = step_count.step_count
    
    db.commit()
    db.refresh(step_count_entry)

    return StepCountUpdateOutput(step_count=step_count_entry.step_count)


@router.get("/query/steps", response_model=list[StepCount])
def query_step_counts(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(StepCount).join(ClientTelemetry, StepCount.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(StepCount.id.desc())
    steps = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return steps

@router.get("/query/weights", response_model=list[HealthMetrics])
def query_weights(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(HealthMetrics).join(ClientTelemetry, HealthMetrics.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(HealthMetrics.id.desc())

    weights = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return weights

@router.put("/update_weight/{health_metrics_id}", response_model=HealthMetrics)
def update_weight(health_metrics_id: int, payload: WeightUpdateInput, db: Session = Depends(get_session), acc: Account = Depends(get_client_account)):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    health_metrics = db.get(HealthMetrics, health_metrics_id)
    if health_metrics is None:
        raise HTTPException(status_code=404, detail="Weight entry not found")

    telemetry = db.get(ClientTelemetry, health_metrics.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this weight entry")

    health_metrics.weight = payload.weight

    db.add(health_metrics)
    db.commit()
    db.refresh(health_metrics)

    return health_metrics

@router.delete("/delete_weight/{health_metrics_id}")
def delete_weight(
    health_metrics_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    health_metrics = db.get(HealthMetrics, health_metrics_id)
    if health_metrics is None:
        raise HTTPException(status_code=404, detail="Weight entry not found")

    telemetry = db.get(ClientTelemetry, health_metrics.client_telemetry_id)
    if telemetry is None or telemetry.client_id != acc.client_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this weight entry")

    db.delete(health_metrics)
    db.commit()

    return {"message": "Weight entry deleted successfully"}


@router.get("/query/moods", response_model=list[CompletedSurvey])
def query_moods(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedSurvey).join(DailyMoodSurvey, DailyMoodSurvey.completed_survey_id == CompletedSurvey.id).join(ClientTelemetry, DailyMoodSurvey.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedSurvey.id.desc())

    moods = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return moods


@router.get("/query/workouts", response_model=list[CompletedWorkout])
def query_workouts(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedWorkout).join(ClientTelemetry, CompletedWorkout.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedWorkout.id.desc())

    workouts = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return workouts

@router.get("/query/meals", response_model=list[CompletedMealActivity])
def query_meals(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    query = select(CompletedMealActivity).join(ClientTelemetry, CompletedMealActivity.client_telemetry_id == ClientTelemetry.id).where(ClientTelemetry.client_id == acc.client_id).order_by(CompletedMealActivity.id.desc())

    meals = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()

    return meals