from sqlmodel import select
from datetime import datetime
from src.api.dependencies import create_jwt_token
from src.database.account.models import Notification, Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    ClientCoachRequest,
    ClientCoachRelationship,
)


def create_client_coach_relationship(db_session):
    client = db_session.exec(
        select(Account).where(
            Account.client_id.is_not(None),
            Account.is_active == True,
        )
    ).first()

    assert client is not None

    coach = db_session.exec(
        select(Account).where(
            Account.coach_id.is_not(None),
            Account.is_active == True,
            Account.id != client.id,
        )
    ).first()

    if coach is None:
        coach_profile = Coach(verified=True)
        db_session.add(coach_profile)
        db_session.commit()
        db_session.refresh(coach_profile)

        coach = Account(
            name="Notification Test Coach",
            email=f"notification_coach_{coach_profile.id}@example.com",
            hashed_password="test-hash",
            coach_id=coach_profile.id,
            is_active=True,
        )
        db_session.add(coach)
        db_session.commit()
        db_session.refresh(coach)

    assert coach is not None

    request = ClientCoachRequest(
        client_id=client.client_id,
        coach_id=coach.coach_id,
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

    return client, coach, request, relationship


def test_account_deactivate_sends_notification(
    test_client,
    db_session,
    client_auth_header,
    coach_auth_header,
):
    client, coach, request, relationship = create_client_coach_relationship(db_session)

    client_auth_header = {
        "Authorization": f"Bearer {create_jwt_token(client)}"
    }

    resp = test_client.post(
        "/roles/shared/account/deactivate",
        headers=client_auth_header,
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db_session.expire_all()

    notifications = list(
        db_session.exec(
            select(Notification).where(Notification.account_id == coach.id)
        )
    )

    remaining_relationship = db_session.get(ClientCoachRelationship, relationship.id)
    remaining_request = db_session.get(ClientCoachRequest, request.id)

    assert notifications, "No notifications found for coach"
    assert any(
        n.details and "deactivated" in n.details.lower()
        for n in notifications
    )
    assert remaining_relationship is None
    assert remaining_request is None

    activate_resp = test_client.post(
        "/roles/shared/account/activate",
        headers=client_auth_header,
    )
    assert activate_resp.status_code == 200, activate_resp.text
    assert db_session.get(ClientCoachRelationship, relationship.id) is None
    assert db_session.get(ClientCoachRequest, request.id) is None


def test_account_deactivate_coach_notifies_client(
    test_client,
    db_session,
    client_auth_header,
    coach_auth_header,
):
    client, coach, request, relationship = create_client_coach_relationship(db_session)

    coach_auth_header = {
        "Authorization": f"Bearer {create_jwt_token(coach)}"
    }

    resp = test_client.post(
        "/roles/shared/account/deactivate",
        headers=coach_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    db_session.expire_all()

    notifications = list(
        db_session.exec(
            select(Notification).where(Notification.account_id == client.id)
        )
    )

    remaining_relationship = db_session.get(ClientCoachRelationship, relationship.id)
    remaining_request = db_session.get(ClientCoachRequest, request.id)

    assert notifications, "No notifications found for client"
    assert any(
        n.details and "deactivated" in n.details.lower()
        for n in notifications
    )
    assert remaining_relationship is None
    assert remaining_request is None

    activate_resp = test_client.post(
        "/roles/shared/account/activate",
        headers=coach_auth_header,
    )
    assert activate_resp.status_code == 200, activate_resp.text
    assert db_session.get(ClientCoachRelationship, relationship.id) is None
    assert db_session.get(ClientCoachRequest, request.id) is None
