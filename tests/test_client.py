from datetime import date
from sqlmodel import Session, select
from tests.payload_tools.client import build_client_init_payload
from src.database.telemetry.models import HealthMetrics, StepCount

def test_client_survey_flow(test_client, auth_header):
    """
    Test creating a Client profile on top of an authenticated base User account.
    """
    client_init_payload = build_client_init_payload()

    client_survey_response = test_client.post(
        "/roles/client/initial_survey",
        json=client_init_payload,
        headers=auth_header,
    )
    
    assert client_survey_response.status_code == 200
    client_survey_data = client_survey_response.json()
    assert "client_id" in client_survey_data
    assert isinstance(client_survey_data["client_id"], int)


def test_client_update_steps_creates_and_updates_step_count(test_client, client_auth_header, db_session):
    """
    Test that a client can create and later update step count telemetry.
    """
    create_payload = {"step_count": 12345}

    create_response = test_client.put(
        "/roles/client/telemetry/update_steps",
        json=create_payload,
        headers=client_auth_header,
    )

    assert create_response.status_code == 200
    assert create_response.json() == {"step_count": 12345}

    created_step_count = db_session.exec(select(StepCount)).first()
    assert created_step_count is not None
    assert created_step_count.step_count == 12345

    update_payload = {"step_count": 54321}

    update_response = test_client.put(
        "/roles/client/telemetry/update_steps",
        json=update_payload,
        headers=client_auth_header,
    )

    assert update_response.status_code == 200
    assert update_response.json() == {"step_count": 54321}

    db_session.refresh(created_step_count)
    assert created_step_count.step_count == 54321


def test_client_query_step_counts_returns_latest_steps(test_client, client_auth_header):
    create_payload = {"step_count": 1234}

    create_response = test_client.put(
        "/roles/client/telemetry/update_steps",
        json=create_payload,
        headers=client_auth_header,
    )
    assert create_response.status_code == 200

    query_response = test_client.get(
        "/roles/client/telemetry/query/steps",
        headers=client_auth_header,
    )
    assert query_response.status_code == 200
    query_data = query_response.json()
    assert isinstance(query_data, list)
    assert len(query_data) == 1
    assert query_data[0]["step_count"] == 1234


def test_client_weight_crud_and_query(test_client, client_auth_header):
    weights_response = test_client.get(
        "/roles/client/telemetry/query/weights",
        headers=client_auth_header,
    )
    assert weights_response.status_code == 200
    weights_data = weights_response.json()
    assert isinstance(weights_data, list)
    assert len(weights_data) >= 1

    initial_weight = weights_data[0]
    health_metrics_id = initial_weight["id"]
    assert initial_weight["weight"] == 170

    update_payload = {"weight": 175}
    update_response = test_client.put(
        f"/roles/client/telemetry/update_weight/{health_metrics_id}",
        json=update_payload,
        headers=client_auth_header,
    )
    assert update_response.status_code == 200
    assert update_response.json()["weight"] == 175

    weights_after_update = test_client.get(
        "/roles/client/telemetry/query/weights",
        headers=client_auth_header,
    )
    assert weights_after_update.status_code == 200
    assert weights_after_update.json()[0]["weight"] == 175

    delete_response = test_client.delete(
        f"/roles/client/telemetry/delete_weight/{health_metrics_id}",
        headers=client_auth_header,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Weight entry deleted successfully"

    weights_after_delete = test_client.get(
        "/roles/client/telemetry/query/weights",
        headers=client_auth_header,
    )
    assert weights_after_delete.status_code == 200
    assert weights_after_delete.json() == []


def test_client_query_moods_workouts_and_meals_return_empty_lists(test_client, client_auth_header):
    moods_response = test_client.get(
        "/roles/client/telemetry/query/moods",
        headers=client_auth_header,
    )
    assert moods_response.status_code == 200
    assert moods_response.json() == []

    workouts_response = test_client.get(
        "/roles/client/telemetry/query/workouts",
        headers=client_auth_header,
    )
    assert workouts_response.status_code == 200
    assert workouts_response.json() == []

    meals_response = test_client.get(
        "/roles/client/telemetry/query/meals",
        headers=client_auth_header,
    )
    assert meals_response.status_code == 200
    assert meals_response.json() == []


def test_client_me_endpoint(test_client, client_auth_header):
    """
    Test that a registered client can fetch their client profile details via the /me endpoint.
    """
    client_me_response = test_client.post(
        "/roles/client/me",
        headers=client_auth_header,
    )
    assert client_me_response.status_code == 200
    
    client_me_data = client_me_response.json()
    assert "@example.com" in client_me_data["base_account"]["email"]
    assert isinstance(client_me_data["client_account"]["id"], int)
