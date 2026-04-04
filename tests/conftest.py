import os
import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
import datetime as dt
from dotenv import load_dotenv

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

import concurrent.futures
from sqlalchemy import text

@pytest.fixture(scope="session")
def engine():
    _engine = create_engine(
        testing_db_url, # type: ignore
        echo=False,
    )
    SQLModel.metadata.create_all(_engine)
    
    # Wipe the database ONCE at the start of the entire test session,
    # rather than before every single test. This is possible because
    # test payloads generate unique users every time.
    def wipe_table(table):
        with _engine.begin() as conn:
            conn.execute(text(f'TRUNCATE "{table.name}" CASCADE;'))
            
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(wipe_table, SQLModel.metadata.sorted_tables)
        
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
def coach_auth_header(test_client, client_auth_header):
    """Promotes a Client to a Coach by posting a coach creation request."""
    coach_req_payload = build_coach_request_payload()

    test_client.post(
        "/roles/coach/request_coach_creation",
        json=coach_req_payload,
        headers=client_auth_header,
    )
    return client_auth_header

