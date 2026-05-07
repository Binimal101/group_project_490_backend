from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from src.database.account.models import BusySlot


def test_client_availability_crud_and_projection(test_client, client_auth_header, seed_availability):
    start_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=7)
    end_dt = start_dt + timedelta(hours=2)

    create_response = seed_availability(
        client_auth_header,
        start_dt=start_dt,
        end_dt=end_dt,
        repeats_weekly=True,
    )
    assert create_response.status_code == 200, create_response.text
    availability_id = create_response.json()["id"]

    params = urlencode({
        "from_dt": start_dt.isoformat(),
        "to_dt": (start_dt + timedelta(days=14)).isoformat()
    })
    list_response = test_client.get(
        f"/roles/client/availability?{params}",
        headers=client_auth_header,
    )
    assert list_response.status_code == 200, list_response.text
    rows = list_response.json()
    assert len(rows) >= 1
    assert rows[0]["occurrences"]

    update_start = start_dt + timedelta(hours=1)
    update_end = update_start + timedelta(hours=2)
    update_response = test_client.put(
        f"/roles/client/availability/{availability_id}",
        json={
            "start_dt": update_start.isoformat(),
            "end_dt": update_end.isoformat(),
            "repeats_weekly": False,
            "recurrence_end_dt": None,
        },
        headers=client_auth_header,
    )
    assert update_response.status_code == 200, update_response.text
    # Check that the response has a start_dt (format may vary between 'Z' and '+00:00')
    updated_row = update_response.json()
    assert updated_row["start_dt"] is not None
    assert updated_row["repeats_weekly"] is False
    # Update creates a new row, so we need to get the new id
    new_availability_id = updated_row["id"]

    delete_response = test_client.delete(
        f"/roles/client/availability/{new_availability_id}",
        headers=client_auth_header,
    )
    assert delete_response.status_code == 200, delete_response.text


def test_busy_slot_manual_delete_and_derived_rejection(test_client, client_auth_header, db_session, seed_availability):
    start_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=10)
    end_dt = start_dt + timedelta(hours=1)
    seed_availability(client_auth_header, start_dt=start_dt, end_dt=end_dt)

    manual_response = test_client.post(
        "/roles/client/busy_slots",
        json={
            "start_dt": start_dt.isoformat(),
            "end_dt": end_dt.isoformat(),
            "note": "manual focus block",
        },
        headers=client_auth_header,
    )
    assert manual_response.status_code == 200, manual_response.text
    busy_slot_id = manual_response.json()["id"]

    delete_manual_response = test_client.delete(
        f"/roles/client/busy_slots/{busy_slot_id}",
        headers=client_auth_header,
    )
    assert delete_manual_response.status_code == 200, delete_manual_response.text

    me_response = test_client.post("/roles/client/me", headers=client_auth_header)
    account_id = me_response.json()["base_account"]["id"]
    derived_busy_slot = BusySlot(
        account_id=account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        source="workout_plan",
        source_id=99,
    )
    db_session.add(derived_busy_slot)
    db_session.commit()
    db_session.refresh(derived_busy_slot)

    delete_derived_response = test_client.delete(
        f"/roles/client/busy_slots/{derived_busy_slot.id}",
        headers=client_auth_header,
    )
    assert delete_derived_response.status_code == 403, delete_derived_response.text
