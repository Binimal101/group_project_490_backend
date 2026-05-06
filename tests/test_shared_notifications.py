from datetime import datetime

from sqlmodel import select

from tests.payload_tools.auth import build_login_payload, build_signup_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload

from src.database.account.models import Account, Notification
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import Chat, ClientCoachRequest, ClientCoachRelationship


def _create_verified_coach(test_client, db_session, email_prefix="chatcoach"):
    signup_payload = build_signup_payload(email_prefix=email_prefix)
    test_client.post("/auth/signup", json=signup_payload)
    login_response = test_client.post(
        "/auth/login",
        json=build_login_payload(signup_payload["email"], signup_payload["password"]),
    )
    coach_header = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=coach_header)
    request_response = test_client.post(
        "/roles/coach/request_coach_creation",
        json=build_coach_request_payload(),
        headers=coach_header,
    )
    coach_id = request_response.json()["coach_id"]

    coach = db_session.get(Coach, coach_id)
    assert coach is not None
    coach.verified = True
    db_session.add(coach)
    db_session.commit()

    me_response = test_client.get("/me", headers=coach_header)
    assert me_response.status_code == 200
    return coach_header, me_response.json()

def test_notification_flows(test_client, auth_header, db_session):
    """
    Test creating notifications manually, querying them, reading one, and reading all.
    auth_header is a logged in Base Account, which is sufficient.
    """
    # 1. Look up the account directly to manually inject some notifications
    # We can fetch the 'me' endpoint to get the account ID
    resp = test_client.get("/me", headers=auth_header)
    assert resp.status_code == 200
    account_id = resp.json()["id"]

    # 2. Inject some notifications for this account
    notif1 = Notification(
        account_id=account_id,
        message="First Notification",
        details="This is the first one"
    )
    notif2 = Notification(
        account_id=account_id,
        message="Second Notification",
        is_read=False
    )
    db_session.add(notif1)
    db_session.add(notif2)
    db_session.commit()
    db_session.refresh(notif1)
    db_session.refresh(notif2)

    n1_id = notif1.id
    n2_id = notif2.id
    
    # 3. Query all notifications to ensure sorting and formatting
    query_resp = test_client.get("/roles/shared/notifications/query", headers=auth_header)
    assert query_resp.status_code == 200
    
    data = query_resp.json()
    assert len(data) >= 2

    last_two_ids = [n["id"] for n in data][:2]
    assert n1_id in last_two_ids and n2_id in last_two_ids

    # Ensure the query route uses the shared pagination dependency params.
    paged_resp = test_client.get("/roles/shared/notifications/query?skip=0&limit=1", headers=auth_header)
    assert paged_resp.status_code == 200
    assert len(paged_resp.json()) == 1
    
    # Ensure properties exist
    sample_notif = next(n for n in data if n["id"] == n1_id)
    assert "account_id" in sample_notif
    assert "message" in sample_notif
    assert sample_notif["is_read"] is False

    # 4. Mark a single notification as read
    read_resp = test_client.post(f"/roles/shared/notifications/read/{n1_id}", headers=auth_header)
    assert read_resp.status_code == 200
    assert read_resp.json()["is_read"] is True

    # Validate hitting it again works
    db_session.refresh(notif1)
    assert notif1.is_read is True

    # Validate the other is still unread
    db_session.refresh(notif2)
    assert notif2.is_read is False

    # 5. Read all unread notifications
    read_all_resp = test_client.post("/roles/shared/notifications/read_all", headers=auth_header)
    assert read_all_resp.status_code == 200
    
    db_session.refresh(notif2)
    assert notif2.is_read is True

    # 6. Verify querying one more time
    final_query = test_client.get("/roles/shared/notifications/query", headers=auth_header)
    assert final_query.status_code == 200
    created_notifications = [n for n in final_query.json() if n["id"] in {n1_id, n2_id}]
    assert all(n["is_read"] is True for n in created_notifications)


def test_chat_message_creates_recipient_notification(test_client, client_auth_header, db_session):
    coach_header, coach_me = _create_verified_coach(test_client, db_session)

    client_me = test_client.get("/me", headers=client_auth_header).json()
    client_account = db_session.get(Account, client_me["id"])
    coach_account = db_session.get(Account, coach_me["id"])
    assert client_account is not None
    assert coach_account is not None
    assert client_account.client_id is not None
    assert coach_account.coach_id is not None

    client_role = db_session.get(Client, client_account.client_id)
    coach_role = db_session.get(Coach, coach_account.coach_id)
    assert client_role is not None
    assert coach_role is not None

    request = ClientCoachRequest(
        is_accepted=True,
        client_id=client_role.id,
        coach_id=coach_role.id,
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
    db_session.refresh(relationship)

    chat = Chat(client_coach_relationship_id=relationship.id)
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    send_resp = test_client.post(
        f"/roles/shared/chat/messages/{chat.id}?message_text=Hello%20coach",
        headers=client_auth_header,
    )
    assert send_resp.status_code == 200

    query_resp = test_client.get("/roles/shared/notifications/query", headers=coach_header)
    assert query_resp.status_code == 200
    chat_notifications = [n for n in query_resp.json() if n["fav_category"] == "chat_message"]
    assert chat_notifications
    latest = chat_notifications[0]
    assert latest["account_id"] == coach_me["id"]
    assert latest["message"] == f"New message from {client_me['name']}"
    assert latest["details"] == "Hello coach"
    assert latest["is_read"] is False
