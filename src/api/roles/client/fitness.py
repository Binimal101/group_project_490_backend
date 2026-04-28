from datetime import datetime
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator, model_validator
from sqlmodel import Session, select, SQLModel
from sqlalchemy.exc import IntegrityError

from src.database.session import get_session
from src.database.workouts_and_activities.models import WorkoutPlanActivity
from src.database.account.models import Account
from src.api.dependencies import get_client_account, PaginationParams
from src.database.client.models import ClientWorkoutPlan 
from src.database.meal.models import ClientPrescribedMeal
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

    @field_validator("completed_reps", "completed_sets", "completed_duration", "estimated_calories")
    @classmethod
    def validate_non_negative_metrics(cls, v):
        if v is not None and v < 0:
            raise ValueError("Workout values cannot be negative")
        return v

    @model_validator(mode="after")
    def validate_workout_submission(self):
        if self.workout_plan_activity_id is None and self.workout_activity_id is None:
            raise ValueError("Either workout_plan_activity_id or workout_activity_id is required")

        has_progress_data = any(
            value is not None
            for value in [
                self.completed_reps,
                self.completed_sets,
                self.completed_duration,
                self.estimated_calories,
            ]
        )

        if not has_progress_data:
            raise ValueError("At least one of completed_reps, completed_sets, completed_duration, or estimated_calories is required")

        return self

class BodyMetricsSurveySubmitPayload(SQLModel):
    weight: int
    progress_pic_url: Optional[str] = None

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Weight must be greater than 0")
        return v

class StepsSurveySubmitPayload(SQLModel):
    step_count: int

    @field_validator("step_count")
    @classmethod
    def validate_step_count(cls, v: int) -> int:
        if v < 0 or v > 100000:
            raise ValueError("Step count must be between 0 and 100000")
        return v

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

def _validate_workout_plan_activity_belongs_to_client(db: Session, client_id: int, workout_plan_activity_id: int):
    workout_plan = db.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.client_id == client_id)).all()

    allowed_plan_ids = [plan.id for plan in workout_plan]

    if not allowed_plan_ids:
        raise HTTPException(status_code=403, detail="No workout plans found for this client")

    workout_plan_activity = db.exec(
        select(WorkoutPlanActivity).where(
            WorkoutPlanActivity.id == workout_plan_activity_id,
            WorkoutPlanActivity.workout_plan_id.in_(allowed_plan_ids)
        )
    ).first()

    if workout_plan_activity is None:
        raise HTTPException(
            status_code=403,
            detail="Workout plan activity does not belong to this client"
        )

    return workout_plan_activity

def _validate_client_prescribed_meal_belongs_to_client(db: Session, client_id: int, client_prescribed_meal_id: int):
    prescribed_meal = db.exec(
        select(ClientPrescribedMeal).where(
            ClientPrescribedMeal.id == client_prescribed_meal_id,
            ClientPrescribedMeal.client_id == client_id
        )
    ).first()

    if prescribed_meal is None:
        raise HTTPException(status_code=403,detail="Prescribed meal does not belong to this client")

    return prescribed_meal

def _get_or_create_telemetry(db: Session, client_id: int) -> ClientTelemetry:
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    telemetry = db.exec(
        select(ClientTelemetry).where(
            ClientTelemetry.client_id == client_id,
            ClientTelemetry.date == today
        )
    ).first()

    if telemetry is not None:
        return telemetry

    telemetry = ClientTelemetry(client_id=client_id, date=today)
    db.add(telemetry)

    try:
        db.commit()
        db.refresh(telemetry)
        return telemetry
    except IntegrityError:
        db.rollback()
        telemetry = db.exec(
            select(ClientTelemetry).where(
                ClientTelemetry.client_id == client_id,
                ClientTelemetry.date == today
            )
        ).first()

        if telemetry is None:
            raise

        return telemetry


def _get_or_create_daily_survey(db: Session, client_id: int, survey_model):
    telemetry = _get_or_create_telemetry(db, client_id)
    survey = db.exec(
        select(survey_model).where(
            survey_model.client_telemetry_id == telemetry.id
        )
    ).first()

    if survey is not None:
        return telemetry, survey

    survey = survey_model(
        is_seen=True,
        is_started=False,
        is_finished=False,
        client_telemetry_id=telemetry.id
    )
    db.add(survey)

    try:
        db.commit()
        db.refresh(survey)
        return telemetry, survey
    except IntegrityError:
        db.rollback()
        survey = db.exec(
            select(survey_model).where(
                survey_model.client_telemetry_id == telemetry.id
            )
        ).first()

        if survey is None:
            raise

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
    db.flush()

    survey.is_finished = True
    survey.completed_survey_id = completed_survey.id
    db.add(survey)

    db.commit()
    db.refresh(completed_survey)
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

    if payload.workout_plan_activity_id is not None:
        _validate_workout_plan_activity_belongs_to_client(db, acc.client_id, payload.workout_plan_activity_id)

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
    db.flush()

    survey.is_finished = True
    survey.completed_workout_id = completed_workout.id
    db.add(survey)

    db.commit()
    db.refresh(completed_workout_details)
    db.refresh(completed_workout)
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
    db.flush()
    
    survey.is_finished = True
    survey.completed_health_metrics_id = health_metrics.id
    db.add(survey)
    db.commit()
    db.refresh(health_metrics)
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
    db.flush()

    survey.is_finished = True
    survey.step_count_id = step_count.id
    db.add(survey)
    db.commit()
    db.refresh(step_count)
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
    
    if payload.client_prescribed_meal_id is not None:
        _validate_client_prescribed_meal_belongs_to_client(
            db,
            acc.client_id,
            payload.client_prescribed_meal_id
        )

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
    db.flush()

    survey.is_finished = True
    survey.completed_meal_activity_id = completed_meal.id
    db.add(survey)
    db.commit()
    db.refresh(completed_meal)
    db.refresh(survey)

    return _create_survey_response(survey, telemetry, "completed_meal_activity_id", DailyMealSurveyResponse)
