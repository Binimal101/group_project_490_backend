from datetime import datetime

from sqlmodel import select

from src.api.dependencies import create_jwt_token
from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    ClientCoachRelationship,
    ClientCoachRequest,
)
from tests.payload_tools.coach import (
    build_coach_request_payload,
    build_update_coach_info_payload,
)


def test_client_can_fetch_coach_availability(test_client, client_auth_header, db_session):
    # Create a coach (starts unverified) with availability via the coach creation endpoint
    payload = build_coach_request_payload(weekday="monday")
    resp = test_client.post("/roles/coach/request_coach_creation", json=payload, headers=client_auth_header)
    assert resp.status_code == 200
    coach_id = resp.json().get("coach_id")
    assert coach_id is not None

    coach = db_session.get(Coach, coach_id)
    assert coach is not None
    coach.verified = True
    db_session.add(coach)
    db_session.commit()

    # Fetch availability using the client-prefixed endpoint we added
    avail_resp = test_client.get(f"/roles/client/coach_availability/{coach_id}", headers=client_auth_header)
    assert avail_resp.status_code == 200

    data = avail_resp.json()
    assert "coach_availabilities" in data
    assert isinstance(data["coach_availabilities"], list)
    assert len(data["coach_availabilities"]) == len(payload["availabilities"]) 

    # Verify fields exist and weekday matches the payload (time strings may be serialized with timezone)
    expected = payload["availabilities"][0]
    actual = data["coach_availabilities"][0]
    assert actual.get("weekday") == expected.get("weekday")
    assert "start_time" in actual and isinstance(actual.get("start_time"), str)
    assert "end_time" in actual and isinstance(actual.get("end_time"), str)


def test_client_fetches_updated_coach_availability(
    test_client,
    client_auth_header,
    coach_auth_header,
    db_session,
):
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    update_payload = build_update_coach_info_payload(weekday="thursday")
    update_resp = test_client.patch(
        "/roles/coach/information",
        json=update_payload,
        headers=coach_auth_header,
    )
    assert update_resp.status_code == 200, update_resp.text

    avail_resp = test_client.get(
        f"/roles/client/coach_availability/{coach_id}",
        headers=client_auth_header,
    )
    assert avail_resp.status_code == 200, avail_resp.text
    availabilities = avail_resp.json()["coach_availabilities"]

    assert len(availabilities) == 1
    assert availabilities[0]["weekday"] == "thursday"
    assert availabilities[0]["start_time"].startswith("19:00:00")
    assert availabilities[0]["end_time"].startswith("21:00:00")


def test_coach_fetches_updated_client_availability(
    test_client,
    client_auth_header,
    coach_auth_header,
    db_session,
):
    client_me = test_client.get("/me", headers=client_auth_header)
    assert client_me.status_code == 200
    client_id = client_me.json()["client_id"]

    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    client_update_payload = {
        "availabilities": [
            {
                "weekday": "friday",
                "start_time": "09:00:00",
                "end_time": "11:00:00",
            }
        ]
    }
    update_resp = test_client.patch(
        "/roles/client/information",
        json=client_update_payload,
        headers=client_auth_header,
    )
    assert update_resp.status_code == 200, update_resp.text

    request = ClientCoachRequest(
        client_id=client_id,
        coach_id=coach_id,
        is_accepted=True,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)

    relationship = ClientCoachRelationship(
        request_id=request.id,
        created_at=datetime.utcnow(),
        is_active=True,
        coach_blocked=False,
        client_blocked=False,
    )
    db_session.add(relationship)
    db_session.commit()

    coach_account = db_session.exec(
        select(Account).where(Account.coach_id == coach_id)
    ).first()
    coach_auth_header = {"Authorization": f"Bearer {create_jwt_token(coach_account)}"}

    avail_resp = test_client.get(
        f"/roles/coach/client_availability/{client_id}",
        headers=coach_auth_header,
    )
    assert avail_resp.status_code == 200, avail_resp.text
    availabilities = avail_resp.json()

    assert len(availabilities) == 1
    assert availabilities[0]["weekday"] == "friday"
    assert availabilities[0]["start_time"].startswith("09:00:00")
    assert availabilities[0]["end_time"].startswith("11:00:00")
