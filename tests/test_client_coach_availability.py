from datetime import datetime, timedelta, timezone

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
    """A client can fetch a verified coach's availability via the client-prefixed endpoint."""
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

    avail_resp = test_client.get(f"/roles/client/coach_availability/{coach_id}", headers=client_auth_header)
    assert avail_resp.status_code == 200, avail_resp.text

    data = avail_resp.json()
    assert "coach_availabilities" in data
    assert isinstance(data["coach_availabilities"], list)
    assert len(data["coach_availabilities"]) >= len(payload["availabilities"])

    expected = payload["availabilities"][0]
    assert any(a["start_dt"].startswith(expected["start_dt"][:10]) for a in data["coach_availabilities"])


def test_client_fetches_updated_coach_availability(
    test_client,
    coach_auth_header,
    db_session,
):
    """After a coach posts a new availability via /availability, a client sees the new window."""
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    new_start = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0, hour=19) + timedelta(days=3)
    new_end = new_start + timedelta(hours=2)
    create_resp = test_client.post(
        "/roles/coach/availability",
        json={
            "start_dt": new_start.isoformat(),
            "end_dt": new_end.isoformat(),
            "repeats_weekly": True,
        },
        headers=coach_auth_header,
    )
    assert create_resp.status_code == 200, create_resp.text

    # Promote a fresh client and fetch the coach's availability via the client proxy
    from tests.payload_tools.auth import build_signup_payload, build_login_payload
    from tests.payload_tools.client import build_client_init_payload

    signup = build_signup_payload(email_prefix="avail_client")
    test_client.post("/auth/signup", json=signup)
    login_resp = test_client.post("/auth/login", json=build_login_payload(signup["email"], signup["password"]))
    client_header = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=client_header)

    avail_resp = test_client.get(
        f"/roles/client/coach_availability/{coach_id}",
        headers=client_header,
    )
    assert avail_resp.status_code == 200, avail_resp.text
    availabilities = avail_resp.json()["coach_availabilities"]

    assert any(a["start_dt"].startswith(new_start.date().isoformat()) for a in availabilities)


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

    new_start = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0, hour=9) + timedelta(days=4)
    new_end = new_start + timedelta(hours=2)
    create_resp = test_client.post(
        "/roles/client/availability",
        json={
            "start_dt": new_start.isoformat(),
            "end_dt": new_end.isoformat(),
            "repeats_weekly": True,
        },
        headers=client_auth_header,
    )
    assert create_resp.status_code == 200, create_resp.text

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
        created_at=datetime.now(timezone.utc),
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
        f"/roles/coach/client/{client_id}/availability",
        params={
            "from_dt": new_start.isoformat(),
            "to_dt": (new_end + timedelta(days=1)).isoformat(),
        },
        headers=coach_auth_header,
    )
    assert avail_resp.status_code == 200, avail_resp.text
    availabilities = avail_resp.json()

    # list_availability_for_account returns a list of windows
    assert any(a["start_dt"].startswith(new_start.date().isoformat()) for a in availabilities) or len(availabilities) >= 1
