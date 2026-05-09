from datetime import date, datetime, timedelta, timezone

from sqlmodel import select

from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from tests.payload_tools.auth import build_login_payload, build_signup_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload
from tests.payload_tools.constants import TEST_CARD_NUMBER


def _signup_and_promote_client(test_client, prefix):
    payload = build_signup_payload(email_prefix=prefix)
    test_client.post("/auth/signup", json=payload)
    login = test_client.post("/auth/login", json=build_login_payload(payload["email"], payload["password"]))
    header = {"Authorization": f"Bearer {login.json()['access_token']}"}
    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=header)
    me = test_client.get("/me", headers=header).json()
    return header, me


def _promote_to_coach(test_client, header, db_session):
    res = test_client.post("/roles/coach/request_coach_creation", json=build_coach_request_payload(), headers=header)
    coach_id = res.json()["coach_id"]
    coach = db_session.get(Coach, coach_id)
    coach.verified = True
    db_session.add(coach)
    db_session.commit()
    return coach_id


def make_client_profile(test_client, auth_header):
    start = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0, hour=8) + timedelta(days=1)
    end = start + timedelta(hours=2)
    payload = {
        "fitness_goals": {
            "goal_enum": "weight loss"
        },
        "payment_information": {
            "ccnum": TEST_CARD_NUMBER,
            "cv": "123",
            "exp_date": str(date(date.today().year + 5, 12, 31))
        },
        "availabilities": [
            {
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
            }
        ],
        "initial_health_metric": {
            "weight": 180
        }
    }

    response = test_client.post(
        "/roles/client/initial_survey",
        json=payload,
        headers=auth_header
    )

    assert response.status_code == 200


def test_get_my_coach(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/my_coach",
        headers=auth_header
    )

    assert response.status_code == 200
    assert response.json()["coach"] is None


def test_get_coach_profile(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/coach_profile/999999",
        headers=auth_header
    )

    assert response.status_code == 404


def test_get_progress_pictures(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/progress_pictures",
        headers=auth_header
    )

    assert response.status_code == 200


def test_get_my_clients(test_client, coach_auth_header):
    response = test_client.get(
        "/roles/coach/my_clients",
        headers=coach_auth_header
    )

    assert response.status_code == 200


def test_review_requires_relationship(test_client, db_session):
    coach_header, coach_me = _signup_and_promote_client(test_client, "rev_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    client_header, client_me = _signup_and_promote_client(test_client, "rev_client")
    client_acc = db_session.exec(select(Account).where(Account.id == client_me["id"])).first()

    # No relationship — review should be rejected
    resp = test_client.post(
        f"/roles/client/coach_review/{coach_acc.coach_id}?rating=5&review_text=great",
        headers=client_header,
    )
    assert resp.status_code == 403, resp.text

    # Create a relationship directly
    request = ClientCoachRequest(
        client_id=client_acc.client_id,
        coach_id=coach_acc.coach_id,
        is_accepted=True,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)
    rel = ClientCoachRelationship(
        request_id=request.id,
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()

    # Now review should succeed
    resp2 = test_client.post(
        f"/roles/client/coach_review/{coach_acc.coach_id}?rating=5&review_text=great",
        headers=client_header,
    )
    assert resp2.status_code == 200, resp2.text


def test_duplicate_coach_request_blocked(test_client, db_session):
    coach_header, coach_me = _signup_and_promote_client(test_client, "dup_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    client_header, _ = _signup_and_promote_client(test_client, "dup_client")

    # First request should succeed
    r1 = test_client.post(f"/roles/client/request_coach/{coach_acc.coach_id}", headers=client_header)
    assert r1.status_code == 200, r1.text

    # Second request to same coach while first is pending should fail with 409
    r2 = test_client.post(f"/roles/client/request_coach/{coach_acc.coach_id}", headers=client_header)
    assert r2.status_code == 409, r2.text
