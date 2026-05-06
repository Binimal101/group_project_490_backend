from sqlmodel import select
from datetime import datetime
from src.database.account.models import Notification, Account
from src.database.coach_client_relationship.models import (
    ClientCoachRequest,
    ClientCoachRelationship,
)


def create_client_coach_relationship(db_session):
    client = db_session.exec(
        select(Account).where(Account.client_id.is_not(None))
    ).first()

    coach = db_session.exec(
        select(Account).where(Account.coach_id.is_not(None))
    ).first()

    assert client is not None
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

    return client, coach


def test_account_deactivate_sends_notification(
    test_client,
    db_session,
    client_auth_header,
    coach_auth_header,
):
    client, coach = create_client_coach_relationship(db_session)

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

    assert notifications, "No notifications found for coach"
    assert any(
        n.details and "deactivated" in n.details.lower()
        for n in notifications
    )


def test_account_deactivate_coach_notifies_client(
    test_client,
    db_session,
    client_auth_header,
    coach_auth_header,
):
    client, coach = create_client_coach_relationship(db_session)

    resp = test_client.post(
        "/roles/shared/account/deactivate",
        headers=coach_auth_header,
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db_session.expire_all()

    notifications = list(
        db_session.exec(
            select(Notification).where(Notification.account_id == client.id)
        )
    )

    assert notifications, "No notifications found for client"
    assert any(
        n.details and "deactivated" in n.details.lower()
        for n in notifications
    )
    