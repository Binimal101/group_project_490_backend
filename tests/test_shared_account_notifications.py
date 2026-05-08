from sqlmodel import select
from datetime import datetime
import os
from src.api.dependencies import create_jwt_token
from src.database.account.models import Notification, Account
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    ClientCoachRequest,
    ClientCoachRelationship,
)
from src.database.payment.models import (
    BillingCycle,
    PricingInterval,
    PricingPlan,
    Subscription,
    SubscriptionStatus,
)


def create_client_coach_relationship(db_session, with_subscription=False):
    client = db_session.exec(
        select(Account).where(
            Account.client_id.is_not(None),
            Account.is_active == True,
        )
    ).first()

    if client is None:
        client_profile = Client()
        db_session.add(client_profile)
        db_session.commit()
        db_session.refresh(client_profile)

        client = Account(
            name="Notification Test Client",
            email=f"notification_client_{client_profile.id}@example.com",
            hashed_password="test-hash",
            client_id=client_profile.id,
            is_active=True,
        )
        db_session.add(client)
        db_session.commit()
        db_session.refresh(client)

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
    )

    db_session.add(relationship)
    db_session.commit()

    if with_subscription:
        pricing_plan = PricingPlan(
            coach_id=coach.coach_id,
            payment_interval=PricingInterval.MONTHLY,
            price_cents=3000,
        )
        db_session.add(pricing_plan)
        db_session.commit()
        db_session.refresh(pricing_plan)

        subscription = Subscription(
            client_id=client.client_id,
            pricing_plan_id=pricing_plan.id,
        )
        db_session.add(subscription)
        db_session.commit()
        db_session.refresh(subscription)

        billing_cycle = BillingCycle(
            active=True,
            entry_date=datetime.utcnow().date(),
            end_date=datetime.utcnow().date(),
            subscription_id=subscription.id,
            pricing_plan_id=pricing_plan.id,
        )
        db_session.add(billing_cycle)
        db_session.commit()

    return client, coach, request, relationship


def test_account_deactivate_sends_notification(
    test_client,
    db_session,
    client_auth_header,
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
        ("deactivated" in (n.message or "").lower())
        or ("deactivated" in (n.details or "").lower())
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


def test_account_deactivate_cancels_future_payments_for_relationship(
    test_client,
    db_session,
    client_auth_header,
):
    client, coach, request, relationship = create_client_coach_relationship(
        db_session,
        with_subscription=True,
    )

    client_auth_header = {
        "Authorization": f"Bearer {create_jwt_token(client)}"
    }

    resp = test_client.post(
        "/roles/shared/account/deactivate",
        headers=client_auth_header,
    )

    assert resp.status_code == 200, resp.text

    subscriptions = db_session.exec(
        select(Subscription)
        .join(PricingPlan, Subscription.pricing_plan_id == PricingPlan.id)
        .where(
            Subscription.client_id == client.client_id,
            PricingPlan.coach_id == coach.coach_id,
        )
    ).all()
    active_cycles = db_session.exec(
        select(BillingCycle)
        .join(Subscription, BillingCycle.subscription_id == Subscription.id)
        .join(PricingPlan, Subscription.pricing_plan_id == PricingPlan.id)
        .where(
            Subscription.client_id == client.client_id,
            PricingPlan.coach_id == coach.coach_id,
            BillingCycle.active == True,
        )
    ).all()

    assert subscriptions
    assert all(subscription.status == SubscriptionStatus.CANCELED for subscription in subscriptions)
    assert all(subscription.canceled_at is not None for subscription in subscriptions)
    assert active_cycles == []


def test_refresh_payments_skips_canceled_subscription(
    test_client,
    db_session,
    client_auth_header,
):
    client, coach, request, relationship = create_client_coach_relationship(
        db_session,
        with_subscription=True,
    )

    subscriptions = db_session.exec(
        select(Subscription)
        .join(PricingPlan, Subscription.pricing_plan_id == PricingPlan.id)
        .where(
            Subscription.client_id == client.client_id,
            PricingPlan.coach_id == coach.coach_id,
        )
    ).all()
    assert len(subscriptions) == 1

    subscription = subscriptions[0]
    subscription.status = SubscriptionStatus.CANCELED
    db_session.add(subscription)
    db_session.commit()

    cycles_before = db_session.exec(
        select(BillingCycle).where(BillingCycle.subscription_id == subscription.id)
    ).all()

    os.environ["CRON_SECRET"] = "test-cron-secret"
    resp = test_client.post(
        "/refresh_payments",
        json={"cron_secret": "test-cron-secret"},
    )

    cycles_after = db_session.exec(
        select(BillingCycle).where(BillingCycle.subscription_id == subscription.id)
    ).all()

    assert resp.status_code == 200, resp.text
    assert len(cycles_after) == len(cycles_before)


def test_account_deactivate_coach_notifies_client(
    test_client,
    db_session,
    client_auth_header,
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
        ("deactivated" in (n.message or "").lower())
        or ("deactivated" in (n.details or "").lower())
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
