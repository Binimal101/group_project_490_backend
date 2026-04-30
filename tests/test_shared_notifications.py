from src.database.account.models import Notification

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
