from tests.payload_tools.auth import build_signup_payload, build_login_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload
from sqlmodel import select

from src.database.account.models import Account
from src.database.reports.models import CoachReviews
from src.database.coach.models import Coach


def _create_and_verify_coach(test_client, db_session, admin_auth_header, name, email_prefix, age=30, gender="non-binary", specialties=None):
    # Sign up
    signup = build_signup_payload(email_prefix=email_prefix, name=name, age=age, gender=gender)
    test_client.post("/auth/signup", json=signup)
    login = test_client.post("/auth/login", json=build_login_payload(signup["email"], signup["password"]))
    token = login.json()["access_token"]
    header = {"Authorization": f"Bearer {token}"}

    # Become a client
    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=header)

    # Request coach creation
    resp = test_client.post("/roles/coach/request_coach_creation", json=build_coach_request_payload(), headers=header)
    data = resp.json()
    coach_id = data["coach_id"]
    coach_request_id = data["coach_request_id"]

    # Optionally set specialties directly in DB for searchability
    if specialties is not None:
        c = db_session.get(Coach, coach_id)
        c.specialties = specialties
        db_session.add(c)
        db_session.commit()

    # Admin approves request
    test_client.post("/roles/admin/resolve_coach_request", json={"coach_request_id": coach_request_id, "is_approved": True}, headers=admin_auth_header)

    return coach_id, header


def _add_review(db_session, coach_id, client_id, rating):
    review = CoachReviews(rating=rating, review_text="test", coach_id=coach_id, client_id=client_id)
    db_session.add(review)
    db_session.commit()


def test_hirable_coaches_filters_and_sorting(test_client, db_session, admin_auth_header, client_auth_header, create_client):
    # Create coaches with different ratings and specialties
    c1_id, c1_header = _create_and_verify_coach(test_client, db_session, admin_auth_header, "Alice", "coach_alice", age=30, gender="female", specialties="yoga")
    c2_id, c2_header = _create_and_verify_coach(test_client, db_session, admin_auth_header, "Bob", "coach_bob", age=40, gender="male", specialties="strength")
    c3_id, c3_header = _create_and_verify_coach(test_client, db_session, admin_auth_header, "Charlie", "coach_charlie", age=25, gender="non-binary", specialties="yoga")

    # Create reviewer clients and add reviews using the `create_client` fixture
    r1_header, r1_client_id = create_client(email_prefix="rev1")
    _add_review(db_session, c1_id, r1_client_id, 5.0)

    r2_header, r2_client_id = create_client(email_prefix="rev2")
    _add_review(db_session, c1_id, r2_client_id, 4.0)
    _add_review(db_session, c2_id, r2_client_id, 3.0)

    # Query: specialty=yoga sorted by avg_rating desc -> expecting Alice then Charlie (Charlie has no reviews)
    resp = test_client.get("/roles/client/query/hirable_coaches?specialty=yoga&sort_by=avg_rating&order=desc", headers=client_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    # first should be Alice with avg_rating 4.5
    assert any(d["coach_id"] == c1_id and abs(d["avg_rating"] - 4.5) < 0.001 for d in data)

    # Query: sort by rating_count desc
    resp2 = test_client.get("/roles/client/query/hirable_coaches?sort_by=rating_count&order=desc", headers=client_auth_header)
    assert resp2.status_code == 200
    d2 = resp2.json()
    # top item should have the highest count (Alice has 2)
    assert d2[0]["rating_count"] >= 2

    # Query: age range filter
    resp3 = test_client.get("/roles/client/query/hirable_coaches?age_start=26&age_end=35", headers=client_auth_header)
    assert resp3.status_code == 200
    d3 = resp3.json()
    # Alice (age 30) should be present, Bob (40) absent
    assert any(item["coach_id"] == c1_id for item in d3)
    assert all(item["coach_id"] != c2_id for item in d3)


def test_hirable_coaches_privacy_and_empty_reviews(test_client, db_session, admin_auth_header, client_auth_header):
    # Create a coach with no reviews
    c_id, c_header = _create_and_verify_coach(test_client, db_session, admin_auth_header, "Dana", "coach_dana", age=28, gender="female", specialties="strength")

    resp = test_client.get("/roles/client/query/hirable_coaches", headers=client_auth_header)
    assert resp.status_code == 200
    data = resp.json()

    # ensure coach record returned does not contain sensitive fields like hashed_password or payment info
    for item in data:
        assert "hashed_password" not in item
        assert "payment_information" not in item

    # find Dana
    dana_items = [i for i in data if i["coach_id"] == c_id]
    assert len(dana_items) == 1
    dana = dana_items[0]
    assert dana["rating_count"] == 0
    assert dana["avg_rating"] is None


def test_hirable_coaches_pagination_and_unauthorized(test_client, client_auth_header):
    # Ensure endpoint accepts explicit skip/limit pagination params
    resp = test_client.get(
        "/roles/client/query/hirable_coaches?sort_by=avg_rating&order=desc&skip=0&limit=100",
        headers=client_auth_header,
    )
    assert resp.status_code == 200

    # Unauthorized access returns 401 and clear message
    resp2 = test_client.get(
        "/roles/client/query/hirable_coaches?skip=0&limit=10",
        headers={"Authorization": "Bearer invalid.token"},
    )
    assert resp2.status_code == 401
    assert resp2.json().get("detail") is not None


def test_deactivated_coach_is_hidden_and_cannot_be_requested(
    test_client,
    db_session,
    admin_auth_header,
    client_auth_header,
    create_client,
):
    coach_id, coach_header = _create_and_verify_coach(
        test_client,
        db_session,
        admin_auth_header,
        "Hidden Coach",
        "coach_hidden",
        specialties="mobility",
    )
    reviewer_header, reviewer_client_id = create_client(email_prefix="hidden_review")
    _add_review(db_session, coach_id, reviewer_client_id, 5.0)

    deactivate_resp = test_client.post(
        "/roles/shared/account/deactivate",
        headers=coach_header,
    )
    assert deactivate_resp.status_code == 200, deactivate_resp.text

    search_resp = test_client.get(
        "/roles/client/query/hirable_coaches?specialty=mobility",
        headers=client_auth_header,
    )
    assert search_resp.status_code == 200
    assert all(item["coach_id"] != coach_id for item in search_resp.json())

    request_resp = test_client.post(
        f"/roles/client/request_coach/{coach_id}",
        headers=client_auth_header,
    )
    assert request_resp.status_code == 404

    profile_resp = test_client.get(
        f"/roles/client/coach_profile/{coach_id}",
        headers=client_auth_header,
    )
    assert profile_resp.status_code == 404

    reviews_resp = test_client.get(
        f"/roles/client/review/{coach_id}",
        headers=client_auth_header,
    )
    assert reviews_resp.status_code == 200
    assert reviews_resp.json()["reviews"] == []

    activate_resp = test_client.post(
        "/roles/shared/account/activate",
        headers=coach_header,
    )
    assert activate_resp.status_code == 200, activate_resp.text

    reviews_after_reactivate = test_client.get(
        f"/roles/client/review/{coach_id}",
        headers=client_auth_header,
    )
    assert reviews_after_reactivate.status_code == 200
    assert len(reviews_after_reactivate.json()["reviews"]) == 1

    coach_account = db_session.exec(
        select(Account).where(Account.coach_id == coach_id)
    ).first()
    assert coach_account is not None
    assert coach_account.is_active is True
