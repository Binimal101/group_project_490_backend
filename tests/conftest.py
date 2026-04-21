import os

os.environ["IS_TESTING"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv
from sqlalchemy import MetaData

# Load environment variables
load_dotenv()

# Verify that TESTING_DATABASE_URL is set
testing_db_url = os.getenv("TESTING_DATABASE_URL")
if not testing_db_url:
    raise RuntimeError("TESTING_DATABASE_URL environment variable is not set. Please add it to your .env file.")

# Force the app to use the testing database
os.environ["TESTING_DATABASE_URL"] = testing_db_url

# Ensure config loads with deterministic test settings before importing app modules
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("PASSWORD_SALT", "test-password-salt")
os.environ.setdefault("GCP_CLIENT_ID", "test-gcp-client")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

from src.api.app import app
from src.database.session import get_session as real_get_session

# Import models to register tables with SQLModel metadata
from src.database.account.models import *
from src.database.client.models import *
from src.database.coach.models import *
from src.database.payment.models import *
from src.database.telemetry.models import *
from src.database.role_management.models import *
from src.database.admin.models import *
from src.database.meal.models import *
from src.database.workouts_and_activities.models import *
from src.database.reports.models import *
from src.database.coach_client_relationship.models import *

@pytest.fixture(scope="session")
def engine():
    _engine = create_engine(
        testing_db_url, # type: ignore
        echo=False,
    )

    # Fully reset schema state to match current ORM models.
    # This avoids drift when tables/columns/constraints changed over time.
    reflected = MetaData()
    reflected.reflect(bind=_engine)
    reflected.drop_all(bind=_engine)
    SQLModel.metadata.create_all(_engine)
        
    return _engine

@pytest.fixture(scope="function")
def db_session(engine):
    with Session(engine) as session:
        yield session

@pytest.fixture(scope="function")
def test_client(db_session, engine):
    app.dependency_overrides[real_get_session] = lambda: db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

# Common Setup: Signup/Login as an Auth'd User
from tests.payload_tools.auth import build_signup_payload, build_login_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload

@pytest.fixture(scope="function")
def auth_header(test_client): #bad solution to create new user for each test, but we dont really care
    """Returns the authorization header wrapper acting as a new user."""
    signup_payload = build_signup_payload()
    test_client.post("/auth/signup", json=signup_payload)
    login_response = test_client.post("/auth/login", json=build_login_payload(signup_payload["email"], signup_payload["password"]))
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="function")
def client_auth_header(test_client, auth_header):
    """Promotes the new user to a Client by posting an initial survey, passing headers down to downstream test flows."""
    client_init_payload = build_client_init_payload()

    test_client.post(
        "/roles/client/initial_survey",
        json=client_init_payload,
        headers=auth_header,
    )
    return auth_header

@pytest.fixture(scope="function")
def coach_auth_header(test_client, client_auth_header, db_session):
    """Promotes a Client to a Coach by posting a coach creation request and auto-verifying."""
    coach_req_payload = build_coach_request_payload()

    res = test_client.post(
        "/roles/coach/request_coach_creation",
        json=coach_req_payload,
        headers=client_auth_header,
    )
    
    # Auto-verify the coach
    coach_id = res.json()["coach_id"]
    coach = db_session.get(Coach, coach_id)
    coach.verified = True
    db_session.add(coach)
    db_session.commit()
    
    return client_auth_header

@pytest.fixture(scope="function")
def admin_auth_header(test_client, auth_header, db_session):
    """Promotes a user directly to Admin using database injection mapping."""
    me_resp = test_client.get("/me", headers=auth_header)
    account_id = me_resp.json()["id"]

    admin = Admin()
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    user = db_session.get(Account, account_id)
    user.admin_id = admin.id
    db_session.add(user)
    db_session.commit()

    return auth_header


from tests.payload_tools.fitness import build_create_workout_payload, build_create_activity_payload

@pytest.fixture(scope="function")
def seed_equipment(db_session):
    eq = Equiptment(name="Dumbbells", description="50 lbs dumbbells")
    db_session.add(eq)
    db_session.commit()
    db_session.refresh(eq)
    return eq

@pytest.fixture(scope="function")
def seed_workout(test_client, coach_auth_header):
    workout_payload = build_create_workout_payload()
    workout_resp = test_client.post("/roles/coach/fitness/workout", json=workout_payload, headers=coach_auth_header)
    return workout_resp.json()["workout_id"]

@pytest.fixture(scope="function")
def seed_workout_activity(test_client, coach_auth_header, seed_workout):
    activity_payload = build_create_activity_payload(seed_workout)
    activity_resp = test_client.post("/roles/coach/fitness/activity", json=activity_payload, headers=coach_auth_header)
    return activity_resp.json()["workout_activity_id"]

@pytest.fixture(scope="function")
def seed_multiple_workouts(test_client, coach_auth_header):
    workouts_to_create = [
        build_create_workout_payload(name="Morning Run", description="Quick run", instructions="Run fast", workout_type="duration", equipment=[]),
        build_create_workout_payload(name="Heavy Lifts", description="Pushing iron", instructions="Lift heavy", workout_type="rep", equipment=[])
    ]
    workout_ids = []
    for w in workouts_to_create:
        resp = test_client.post("/roles/coach/fitness/workout", json=w, headers=coach_auth_header)
        workout_ids.append(resp.json()["workout_id"])
    return workout_ids
