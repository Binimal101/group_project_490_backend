import os
from datetime import date, timedelta

from sqlmodel import select

from src.database.payment.models import BillingCycle, Invoice, Subscription, SubscriptionStatus
from src.database.coach_client_relationship.models import ClientCoachRelationship, ClientCoachRequest
from src.database.account.models import Notification


def test_overdue_payment_cancels_relationship(test_client, create_client, coach_auth_header, db_session):
    """
    When refresh_payments runs and the most recent billing cycle has already
    expired (end_date < today) with an unpaid balance, it should:
    - Cancel the subscription
    - Terminate the coach-client relationship
    - Notify both the client and coach
    - NOT create a new billing cycle
    """
    os.environ["CRON_SECRET"] = "test-cron-secret"

    # 1. Create client and form a relationship
    client_header, client_id = create_client(email_prefix="overdue_client")
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_account_id = coach_me.json()["coach_account"]["id"]

    req_resp = test_client.post(f"/roles/client/request_coach/{coach_account_id}", headers=client_header)
    assert req_resp.status_code == 200
    request_id = req_resp.json()["request_id"]

    acc_resp = test_client.post(f"/roles/coach/accept_client/{request_id}", headers=coach_auth_header)
    assert acc_resp.status_code == 200
    relationship_id = acc_resp.json()["relationship_id"]

    # 2. Backdate the billing cycle so it appears expired
    relationship = db_session.get(ClientCoachRelationship, relationship_id)
    assert relationship is not None
    assert relationship.is_active is True

    request_row = db_session.get(ClientCoachRequest, relationship.request_id)
    sub = db_session.exec(
        select(Subscription).where(Subscription.client_id == request_row.client_id)
    ).first()
    assert sub is not None

    cycle = db_session.exec(
        select(BillingCycle).where(BillingCycle.subscription_id == sub.id)
        .order_by(BillingCycle.entry_date.desc())
    ).first()
    assert cycle is not None

    # Push end_date into the past so the cycle is treated as expired
    cycle.end_date = date.today() - timedelta(days=1)
    db_session.add(cycle)
    db_session.commit()

    # Confirm there is still an outstanding balance before running the job
    invoices_before = db_session.exec(
        select(Invoice).where(Invoice.billing_cycle_id == cycle.id, Invoice.outstanding_balance > 0)
    ).all()
    assert len(invoices_before) > 0, "Expected at least one unpaid invoice before running the job"

    # 3. Run refresh_payments
    refresh_resp = test_client.post("/refresh_payments", json={"cron_secret": "test-cron-secret"})
    assert refresh_resp.status_code == 200

    # 4. Subscription should be cancelled
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.CANCELED
    assert sub.canceled_at == date.today()

    # 5. Relationship should be inactive
    db_session.refresh(relationship)
    assert relationship.is_active is False

    # 6. No new billing cycle should have been created for this subscription
    all_cycles = db_session.exec(
        select(BillingCycle).where(BillingCycle.subscription_id == sub.id)
    ).all()
    assert len(all_cycles) == 1, "A new billing cycle should not be created after overdue cancellation"

    # 7. Outstanding invoices should be zeroed out
    invoices_after = db_session.exec(
        select(Invoice).where(Invoice.billing_cycle_id == cycle.id, Invoice.outstanding_balance > 0)
    ).all()
    assert len(invoices_after) == 0

    # 8. Both client and coach should have received overdue notifications
    from src.database.account.models import Account
    client_acc = db_session.exec(select(Account).where(Account.client_id == request_row.client_id)).first()
    coach_acc = db_session.exec(select(Account).where(Account.coach_id == request_row.coach_id)).first()

    client_notifs = db_session.exec(
        select(Notification).where(
            Notification.account_id == client_acc.id,
            Notification.fav_category == "payment_overdue",
        )
    ).all()
    assert len(client_notifs) == 1
    assert "overdue" in client_notifs[0].message.lower()

    coach_notifs = db_session.exec(
        select(Notification).where(
            Notification.account_id == coach_acc.id,
            Notification.fav_category == "payment_overdue",
        )
    ).all()
    assert len(coach_notifs) == 1
    assert "missed a payment" in coach_notifs[0].message.lower()
