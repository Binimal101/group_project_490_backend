from datetime import datetime
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator, model_validator
from sqlmodel import Session, select, SQLModel

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_client_account, PaginationParams
from src.database.client.models import ClientWorkoutPlan 
from src.database.telemetry.models import (
    ClientTelemetry, 
    DailyMoodSurvey, 
    DailyWorkoutSurvey,
    DailyBodyMetricsSurvey,
    DailyStepsSurvey,
    DailyMealSurvey,
    CompletedSurvey,
    CompletedWorkout,
    CompletedWorkoutActivity,
    HealthMetrics,
    StepCount,
    CompletedMealActivity,
)

router = APIRouter(prefix="/roles/client/fitness", tags=["client", "fitness"])

class DailySurveySubmitPayload(SQLModel):
    happiness_meter: int
    alertness: int
    healthiness: int
    todays_goals: str
    todays_appreciation: str

    @field_validator("happiness_meter", "alertness", "healthiness")
    @classmethod
    def validate_meter(cls, v):
        if not (1 <= v <= 10):
            raise ValueError("Value must be between 1 and 10")
        return v

class WorkoutSurveySubmitPayload(SQLModel):
    workout_plan_activity_id: Optional[int] = None
    workout_activity_id: Optional[int] = None
    completed_reps: Optional[int] = None
    completed_sets: Optional[int] = None
    completed_duration: Optional[int] = None
    estimated_calories: Optional[int] = None

class BodyMetricsSurveySubmitPayload(SQLModel):
    weight: int
    progress_pic_url: Optional[str] = None

class StepsSurveySubmitPayload(SQLModel):
    step_count: int

class MealSurveySubmitPayload(SQLModel):
    client_prescribed_meal_id: Optional[int] = None
    on_demand_meal_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_meal_choice(self):
        if self.client_prescribed_meal_id is None and self.on_demand_meal_id is None:
            raise ValueError("Either client_prescribed_meal_id or on_demand_meal_id is required")
        return self

class DailySurveyResponse(SQLModel):
    survey_id: int
    telemetry_id: int
    is_seen: bool
    is_started: bool
    is_finished: bool
    completed_survey_id: Optional[int] = None

class DailyWorkoutSurveyResponse(SQLModel):
    survey_id: int
    telemetry_id: int
    is_seen: bool
    is_started: bool
    is_finished: bool
    completed_workout_id: Optional[int] = None

class DailyBodyMetricsSurveyResponse(SQLModel):
    survey_id: int
    telemetry_id: int
    is_seen: bool
    is_started: bool
    is_finished: bool
    completed_health_metrics_id: Optional[int] = None

class DailyStepsSurveyResponse(SQLModel):
    survey_id: int
    telemetry_id: int
    is_seen: bool
    is_started: bool
    is_finished: bool
    step_count_id: Optional[int] = None

class DailyMealSurveyResponse(SQLModel):
    survey_id: int
    telemetry_id: int
    is_seen: bool
    is_started: bool
    is_finished: bool
    completed_meal_activity_id: Optional[int] = None


def _get_or_create_telemetry(db: Session, client_id: int) -> ClientTelemetry:
    today = datetime.utcnow().date()
    telemetry = db.exec(
        select(ClientTelemetry).where(
            ClientTelemetry.client_id == client_id,
            ClientTelemetry.date == today
        )
    ).first()

    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_id, date=today)
        db.add(telemetry)
        db.commit()
        db.refresh(telemetry)

    return telemetry


def _get_or_create_daily_survey(db: Session, client_id: int, survey_model):
    telemetry = _get_or_create_telemetry(db, client_id)
    survey = db.exec(
        select(survey_model).where(
            survey_model.client_telemetry_id == telemetry.id
        )
    ).first()

    if survey is None:
        survey = survey_model(is_seen=True, is_started=False, is_finished=False, client_telemetry_id=telemetry.id)
        db.add(survey)
        db.commit()
        db.refresh(survey)

    return telemetry, survey


def _create_survey_response(survey, telemetry, completed_key: str, response_model):
    response_data = {
        "survey_id": survey.id,
        "telemetry_id": telemetry.id,
        "is_seen": survey.is_seen,
        "is_started": survey.is_started,
        "is_finished": survey.is_finished,
        completed_key: getattr(survey, completed_key)
    }
    return response_model(**response_data)


def get_or_create_daily_survey(db: Session, client_id: int) -> Tuple[ClientTelemetry, DailyMoodSurvey]:
    return _get_or_create_daily_survey(db, client_id, DailyMoodSurvey)

@router.get("/query/plans")
def query_client_workout_plans(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    query = select(ClientWorkoutPlan).where(ClientWorkoutPlan.client_id == acc.client_id)
    plans = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return plans

@router.get("/daily-survey/today", response_model=DailySurveyResponse)
def get_today_daily_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")
    
    telemetry, survey = get_or_create_daily_survey(db, acc.client_id)
    return DailySurveyResponse(
        survey_id=survey.id,
        telemetry_id=telemetry.id,
        is_seen=survey.is_seen,
        is_started=survey.is_started,
        is_finished=survey.is_finished,
        completed_survey_id=survey.completed_survey_id
    )

@router.post("/daily-survey/start", response_model=DailySurveyResponse)
def start_daily_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")
    
    telemetry, survey = get_or_create_daily_survey(db, acc.client_id)

    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    if not survey.is_started:
        survey.is_started = True
        survey.is_seen = True
        db.add(survey)
        db.commit()
        db.refresh(survey)

    return DailySurveyResponse(
        survey_id=survey.id,
        telemetry_id=telemetry.id,
        is_seen=survey.is_seen,
        is_started=survey.is_started,
        is_finished=survey.is_finished,
        completed_survey_id=survey.completed_survey_id
    )

@router.post("/daily-survey/submit", response_model=DailySurveyResponse)
def submit_daily_survey(
    payload: DailySurveySubmitPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")
    
    telemetry, survey = get_or_create_daily_survey(db, acc.client_id)

    if not survey.is_started:
        raise HTTPException(status_code=400, detail="Survey has not been started yet")
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    completed_survey = CompletedSurvey(
        happiness_meter=payload.happiness_meter,
        alertness=payload.alertness,
        healthiness=payload.healthiness,
        todays_goals=payload.todays_goals,
        todays_appreciation=payload.todays_appreciation
    )
    db.add(completed_survey)
    db.commit()
    db.refresh(completed_survey)

    survey.is_finished = True
    survey.completed_survey_id = completed_survey.id
    
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return DailySurveyResponse(
        survey_id=survey.id,
        telemetry_id=telemetry.id,
        is_seen=survey.is_seen,
        is_started=survey.is_started,
        is_finished=survey.is_finished,
        completed_survey_id=survey.completed_survey_id
    )

@router.get("/daily-survey/workout/today", response_model=DailyWorkoutSurveyResponse)
def get_today_workout_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyWorkoutSurvey)
    return _create_survey_response(survey, telemetry, "completed_workout_id", DailyWorkoutSurveyResponse)


@router.post("/daily-survey/workout/start", response_model=DailyWorkoutSurveyResponse)
def start_daily_workout_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyWorkoutSurvey)
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")
    
    if not survey.is_started:
        survey.is_started = True
        survey.is_seen = True
        db.add(survey)
        db.commit()
        db.refresh(survey)

    return _create_survey_response(
        survey,
        telemetry,
        "completed_workout_id",
        DailyWorkoutSurveyResponse
    )


@router.post("/daily-survey/workout/submit", response_model=DailyWorkoutSurveyResponse)
def submit_daily_workout_survey(
    payload: WorkoutSurveySubmitPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyWorkoutSurvey)
    if not survey.is_started:
        raise HTTPException(status_code=400, detail="Survey has not been started yet")
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    completed_workout_details = CompletedWorkoutActivity(
        completed_reps=payload.completed_reps,
        completed_sets=payload.completed_sets,
        completed_duration=payload.completed_duration,
        estimated_calories=payload.estimated_calories,
    )
    db.add(completed_workout_details)
    db.flush()

    completed_workout = CompletedWorkout(
        workout_plan_activity_id=payload.workout_plan_activity_id,
        workout_activity_id=payload.workout_activity_id,
        completed_workout_details_id=completed_workout_details.id,
        client_telemetry_id=telemetry.id,
    )
    db.add(completed_workout)
    db.commit()
    db.refresh(completed_workout)

    survey.is_finished = True
    survey.completed_workout_id = completed_workout.id
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return _create_survey_response(survey, telemetry, "completed_workout_id", DailyWorkoutSurveyResponse)


@router.get("/daily-survey/body-metrics/today", response_model=DailyBodyMetricsSurveyResponse)
def get_today_body_metrics_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyBodyMetricsSurvey)
    return _create_survey_response(survey, telemetry, "completed_health_metrics_id", DailyBodyMetricsSurveyResponse)


@router.post("/daily-survey/body-metrics/start", response_model=DailyBodyMetricsSurveyResponse)
def start_daily_body_metrics_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyBodyMetricsSurvey)

    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")
    
    if not survey.is_started:
        survey.is_started = True
        survey.is_seen = True
        db.add(survey)
        db.commit()
        db.refresh(survey)  

    return _create_survey_response(survey, telemetry, "completed_health_metrics_id", DailyBodyMetricsSurveyResponse)

@router.post("/daily-survey/body-metrics/submit", response_model=DailyBodyMetricsSurveyResponse)
def submit_daily_body_metrics_survey(
    payload: BodyMetricsSurveySubmitPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyBodyMetricsSurvey)
    if not survey.is_started:
        raise HTTPException(status_code=400, detail="Survey has not been started yet")
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    health_metrics = HealthMetrics(
        weight=payload.weight,
        progress_pic_url=payload.progress_pic_url,
        client_telemetry_id=telemetry.id,
    )
    db.add(health_metrics)
    db.commit()
    db.refresh(health_metrics)

    survey.is_finished = True
    survey.completed_health_metrics_id = health_metrics.id
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return _create_survey_response(survey, telemetry, "completed_health_metrics_id", DailyBodyMetricsSurveyResponse)


@router.get("/daily-survey/steps/today", response_model=DailyStepsSurveyResponse)
def get_today_steps_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyStepsSurvey)
    return _create_survey_response(survey, telemetry, "step_count_id", DailyStepsSurveyResponse)


@router.post("/daily-survey/steps/start", response_model=DailyStepsSurveyResponse)
def start_daily_steps_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyStepsSurvey)

    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")
    
    if not survey.is_started:
        survey.is_started = True
        survey.is_seen = True
        db.add(survey)
        db.commit()
        db.refresh(survey)

    return _create_survey_response(survey, telemetry, "step_count_id", DailyStepsSurveyResponse)


@router.post("/daily-survey/steps/submit", response_model=DailyStepsSurveyResponse)
def submit_daily_steps_survey(
    payload: StepsSurveySubmitPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyStepsSurvey)
    if not survey.is_started:
        raise HTTPException(status_code=400, detail="Survey has not been started yet")
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    step_count = StepCount(
        step_count=payload.step_count,
        client_telemetry_id=telemetry.id,
    )
    db.add(step_count)
    db.commit()
    db.refresh(step_count)

    survey.is_finished = True
    survey.step_count_id = step_count.id
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return _create_survey_response(survey, telemetry, "step_count_id", DailyStepsSurveyResponse)


@router.get("/daily-survey/meal/today", response_model=DailyMealSurveyResponse)
def get_today_meal_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyMealSurvey)
    return _create_survey_response(survey, telemetry, "completed_meal_activity_id", DailyMealSurveyResponse)


@router.post("/daily-survey/meal/start", response_model=DailyMealSurveyResponse)
def start_daily_meal_survey(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyMealSurvey)
    
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")
    
    if not survey.is_started:
        survey.is_started = True
        survey.is_seen = True
        db.add(survey)
        db.commit()
        db.refresh(survey)

    return _create_survey_response(survey, telemetry, "completed_meal_activity_id", DailyMealSurveyResponse)


@router.post("/daily-survey/meal/submit", response_model=DailyMealSurveyResponse)
def submit_daily_meal_survey(
    payload: MealSurveySubmitPayload,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_client_account)
):
    if acc.client_id is None:
        raise HTTPException(status_code=404, detail="Client profile not found")

    telemetry, survey = _get_or_create_daily_survey(db, acc.client_id, DailyMealSurvey)
    if not survey.is_started:
        raise HTTPException(status_code=400, detail="Survey has not been started yet")
    if survey.is_finished:
        raise HTTPException(status_code=400, detail="Survey has already been submitted")

    completed_meal = CompletedMealActivity(
        client_prescribed_meal_id=payload.client_prescribed_meal_id,
        on_demand_meal_id=payload.on_demand_meal_id,
        client_telemetry_id=telemetry.id,
    )
    db.add(completed_meal)
    db.commit()
    db.refresh(completed_meal)

    survey.is_finished = True
    survey.completed_meal_activity_id = completed_meal.id
    db.add(survey)
    db.commit()
    db.refresh(survey)

    return _create_survey_response(survey, telemetry, "completed_meal_activity_id", DailyMealSurveyResponse)
