from tests.payload_tools.coach import build_coach_request_payload


def test_client_can_fetch_coach_availability(test_client, client_auth_header, db_session):
    # Create a coach (starts unverified) with availability via the coach creation endpoint
    payload = build_coach_request_payload(weekday="monday")
    resp = test_client.post("/roles/coach/request_coach_creation", json=payload, headers=client_auth_header)
    assert resp.status_code == 200
    coach_id = resp.json().get("coach_id")
    assert coach_id is not None

    # Mark coach as verified in the DB so availability can be viewed
    from src.database.coach.models import Coach

    coach = db_session.get(Coach, coach_id)
    assert coach is not None
    coach.verified = True
    db_session.add(coach)
    db_session.commit()

    # Fetch availability using the client-prefixed endpoint we added
    avail_resp = test_client.get(f"/roles/client/coach_availability/{coach_id}", headers=client_auth_header)
    assert avail_resp.status_code == 200

    data = avail_resp.json()
    assert "coach_availabilities" in data
    assert isinstance(data["coach_availabilities"], list)
    assert len(data["coach_availabilities"]) == len(payload["availabilities"]) 

    # Verify fields exist and weekday matches the payload (time strings may be serialized with timezone)
    expected = payload["availabilities"][0]
    actual = data["coach_availabilities"][0]
    assert actual.get("weekday") == expected.get("weekday")
    assert "start_time" in actual and isinstance(actual.get("start_time"), str)
    assert "end_time" in actual and isinstance(actual.get("end_time"), str)
