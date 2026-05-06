from decimal import Decimal
import pytest
from datetime import datetime, timedelta
from src.database.workouts_and_activities.models import Equiptment, WorkoutType
from src.database.client.models import ClientWorkoutPlan
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from tests.payload_tools.fitness import (
    build_create_workout_payload,
    build_create_activity_payload,
    build_create_plan_payload
)

def test_coach_can_create_workout(test_client, coach_auth_header, seed_equipment):
    # 2. Test create workout (using pre-seeded equipment)
    payload = build_create_workout_payload(
        workout_type=WorkoutType.REPETITION_BASED.value,
        equipment=[
            {
                "equiptment_id": seed_equipment.id,
                "is_required": True,
                "is_recommended": True
            }
        ]
    )
    response = test_client.post("/roles/coach/fitness/workout", json=payload, headers=coach_auth_header)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "workout_id" in data
    workout_id = data["workout_id"]

    # 3. Create an activity under that workout
    activity_payload = build_create_activity_payload(workout_id=workout_id)
    act_response = test_client.post("/roles/coach/fitness/activity", json=activity_payload, headers=coach_auth_header)
    assert act_response.status_code == 200, act_response.text
    act_data = act_response.json()
    assert "workout_activity_id" in act_data
    workout_activity_id = act_data["workout_activity_id"]

    # 4. Query activities for the workout (Shared route tested with coach_auth_header)
    query_act_response = test_client.get(f"/roles/shared/fitness/query/activity?workout_id={workout_id}", headers=coach_auth_header)
    assert query_act_response.status_code == 200, query_act_response.text
    activities = query_act_response.json()
    assert len(activities) > 0
    assert activities[0]["id"] == workout_activity_id

def test_client_can_create_workout_plan(test_client, client_auth_header, seed_workout_activity):
    # 5. Create a workout plan (Shared route, appropriately simulated using client_auth_header over a seeded activity)
    plan_payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    plan_response = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=client_auth_header)
    assert plan_response.status_code == 200, plan_response.text
    plan_data = plan_response.json()
    assert "workout_plan_id" in plan_data


def test_client_query_workout(test_client, coach_auth_header, client_auth_header, seed_equipment):
    # Setup: Coach creates some workouts first
    workouts_to_create = [
        build_create_workout_payload(name="Morning Run", description="Quick run", instructions="Run fast", workout_type="duration", equipment=[]),
        build_create_workout_payload(name="Heavy Lifts", description="Pushing iron", instructions="Lift heavy", workout_type="rep", equipment=[{"equiptment_id": seed_equipment.id, "is_required": True, "is_recommended": True}])
    ]
    for w in workouts_to_create:
        resp = test_client.post("/roles/coach/fitness/workout", json=w, headers=coach_auth_header)
        assert resp.status_code == 200, resp.text

    # Client queries by text (in name)
    search_resp_1 = test_client.get("/roles/shared/fitness/query/workout?text=Morning", headers=client_auth_header)
    assert search_resp_1.status_code == 200, search_resp_1.text
    res_1 = search_resp_1.json()
    assert len(res_1) >= 1
    assert any(x["name"] == "Morning Run" for x in res_1)

    # Client queries by text (in description)
    search_resp_2 = test_client.get("/roles/shared/fitness/query/workout?text=iron", headers=client_auth_header)
    assert search_resp_2.status_code == 200, search_resp_2.text
    res_2 = search_resp_2.json()
    assert len(res_2) >= 1
    assert any(x["name"] == "Heavy Lifts" for x in res_2)

    # Client queries by type
    search_resp_3 = test_client.get("/roles/shared/fitness/query/workout?workout_type=rep", headers=client_auth_header)
    assert search_resp_3.status_code == 200, search_resp_3.text
    res_3 = search_resp_3.json()
    assert len(res_3) >= 1
    assert all(x["workout_type"] == "rep" for x in res_3)

    # Client queries by equiptment
    search_resp_4 = test_client.get(f"/roles/shared/fitness/query/workout?equiptment_id={seed_equipment.id}", headers=client_auth_header)
    assert search_resp_4.status_code == 200, search_resp_4.text
    res_4 = search_resp_4.json()
    assert len(res_4) >= 1
    assert any(x["name"] == "Heavy Lifts" for x in res_4)
    

def test_query_supported_equiptment(test_client, client_auth_header, coach_auth_header, seed_equipment):
    # Test client queries supported equipment
    client_eq_resp = test_client.get("/roles/shared/fitness/query/supported_equiptment", headers=client_auth_header)
    assert client_eq_resp.status_code == 200, client_eq_resp.text
    client_eq_data = client_eq_resp.json()
    assert len(client_eq_data) >= 1
    assert any(eq["id"] == seed_equipment.id for eq in client_eq_data)

    # Test coach queries supported equipment
    coach_eq_resp = test_client.get("/roles/shared/fitness/query/supported_equiptment", headers=coach_auth_header)
    assert coach_eq_resp.status_code == 200, coach_eq_resp.text
    coach_eq_data = coach_eq_resp.json()
    assert len(coach_eq_data) >= 1
    assert any(eq["id"] == seed_equipment.id for eq in coach_eq_data)


def test_errors_on_invalid_data(test_client, coach_auth_header):
    # Invalid workout type
    payload = build_create_workout_payload(workout_type="not_a_valid_type")
    resp = test_client.post("/roles/coach/fitness/workout", json=payload, headers=coach_auth_header)
    assert resp.status_code == 422 or resp.status_code == 400

    # Missing equipment ID
    payload = build_create_workout_payload(workout_type="rep", equipment=[{"equiptment_id": 99999, "is_required": True, "is_recommended": True}])
    resp2 = test_client.post("/roles/coach/fitness/workout", json=payload, headers=coach_auth_header)
    assert resp2.status_code == 404

    # Activity tied to missing workout
    act_payload = build_create_activity_payload(workout_id=99999)
    resp3 = test_client.post("/roles/coach/fitness/activity", json=act_payload, headers=coach_auth_header)
    assert resp3.status_code == 404

    # Plan tied to missing activity
    plan_payload = build_create_plan_payload(workout_activity_id=99999)
    resp4 = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert resp4.status_code == 404
    
    # Workout Plan Validation Failure: Both duration and sets/reps provided
    plan_payload = build_create_plan_payload(workout_activity_id=1) 
    plan_payload["activities"][0]["planned_duration"] = 60
    plan_payload["activities"][0]["planned_reps"] = 10
    plan_payload["activities"][0]["planned_sets"] = 3
    resp5 = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert resp5.status_code == 422
    
    # Workout Plan Validation Failure: Neither duration nor sets/reps provided
    plan_payload = build_create_plan_payload(workout_activity_id=1) 
    plan_payload["activities"][0]["planned_duration"] = None
    plan_payload["activities"][0]["planned_reps"] = None
    plan_payload["activities"][0]["planned_sets"] = None
    resp6 = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert resp6.status_code == 422
    
    # Workout Plan Validation Failure: Both duration and sets/reps provided
    plan_payload = build_create_plan_payload(workout_activity_id=1) 
    plan_payload["activities"][0]["planned_duration"] = 60
    plan_payload["activities"][0]["planned_reps"] = 10
    plan_payload["activities"][0]["planned_sets"] = 3
    resp5 = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert resp5.status_code == 422
    
    # Workout Plan Validation Failure: Neither duration nor sets/reps provided
    plan_payload = build_create_plan_payload(workout_activity_id=1) 
    plan_payload["activities"][0]["planned_duration"] = None
    plan_payload["activities"][0]["planned_reps"] = None
    plan_payload["activities"][0]["planned_sets"] = None
    resp6 = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert resp6.status_code == 422

def test_coach_can_create_workout_and_upsert_equiptment(test_client, coach_auth_header):
    payload = build_create_workout_payload(equipment=[{"name": "Kettlebell", "description": "15 lbs", "is_required": True, "is_recommended": True}])
    response = test_client.post("/roles/coach/fitness/workout", json=payload, headers=coach_auth_header)
    assert response.status_code == 200

def test_client_query_plans(test_client, client_auth_header, seed_workout_activity, db_session):
    # Create the base workout plan through existing shared routes
    plan_payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    plan_response = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=client_auth_header)
    assert plan_response.status_code == 200
    workout_plan_id = plan_response.json()["workout_plan_id"]

    # Get the client ID from 'me' route
    me_resp = test_client.post("/roles/client/me", headers=client_auth_header)
    assert me_resp.status_code == 200
    client_id = me_resp.json()["base_account"]["client_id"]

    # Insert a ClientWorkoutPlan into DB directly (mocking the action since the route to create mapped ones isn't explicitly defined here)
    cwp = ClientWorkoutPlan(
        client_id=client_id,
        workout_plan_id=workout_plan_id,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(days=1)
    )
    db_session.add(cwp)
    db_session.commit()

    # Query the plans via the new user route
    query_resp = test_client.get("/roles/client/fitness/query/plans", headers=client_auth_header)
    assert query_resp.status_code == 200
    data = query_resp.json()
    assert len(data) >= 1
    
    # Assert data integrity
    assert any(p["workout_plan_id"] == workout_plan_id and p["client_id"] == client_id for p in data)


def test_coach_can_prescribe_workout_plan_to_active_client(test_client, create_client, coach_auth_header, seed_workout_activity, db_session):
    plan_payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    plan_response = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert plan_response.status_code == 200, plan_response.text
    workout_plan_id = plan_response.json()["workout_plan_id"]

    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    client_header, client_id = create_client(email_prefix="plan_prescribe_client")
    request = ClientCoachRequest(client_id=client_id, coach_id=coach_id, is_accepted=True)
    db_session.add(request)
    db_session.flush()
    db_session.add(ClientCoachRelationship(
        request_id=request.id,
        created_at=datetime.utcnow(),
        is_active=True,
        coach_blocked=False,
        client_blocked=False,
    ))
    db_session.commit()

    start_dt = datetime.utcnow()
    end_dt = start_dt + timedelta(days=14)
    prescribe_response = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": workout_plan_id,
            "client_id": client_id,
            "start_dt": start_dt.isoformat(),
            "end_dt": end_dt.isoformat(),
        },
        headers=coach_auth_header,
    )
    assert prescribe_response.status_code == 200, prescribe_response.text
    client_workout_plan_id = prescribe_response.json()["client_workout_plan_id"]

    client_workout_plan = db_session.get(ClientWorkoutPlan, client_workout_plan_id)
    assert client_workout_plan is not None
    assert client_workout_plan.client_id == client_id
    assert client_workout_plan.workout_plan_id == workout_plan_id

    notification_response = test_client.get("/roles/shared/notifications/query", headers=client_header)
    assert notification_response.status_code == 200
    notifications = notification_response.json()
    assert any(n["fav_category"] == "workout_plan" for n in notifications)


def test_coach_cannot_prescribe_workout_plan_to_unrelated_client(test_client, create_client, coach_auth_header, seed_workout_activity):
    plan_payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    plan_response = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=coach_auth_header)
    assert plan_response.status_code == 200, plan_response.text

    _, client_id = create_client(email_prefix="unrelated_plan_client")
    start_dt = datetime.utcnow()
    response = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": plan_response.json()["workout_plan_id"],
            "client_id": client_id,
            "start_dt": start_dt.isoformat(),
            "end_dt": (start_dt + timedelta(days=7)).isoformat(),
        },
        headers=coach_auth_header,
    )
    assert response.status_code == 403


def test_client_can_assign_workout_plan_to_self(test_client, client_auth_header, seed_workout_activity, db_session):
    plan_payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    plan_response = test_client.post("/roles/shared/fitness/plan", json=plan_payload, headers=client_auth_header)
    assert plan_response.status_code == 200, plan_response.text
    workout_plan_id = plan_response.json()["workout_plan_id"]

    me_response = test_client.post("/roles/client/me", headers=client_auth_header)
    assert me_response.status_code == 200
    client_id = me_response.json()["base_account"]["client_id"]

    start_dt = datetime.utcnow()
    assign_response = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": workout_plan_id,
            "start_dt": start_dt.isoformat(),
            "end_dt": (start_dt + timedelta(days=5)).isoformat(),
        },
        headers=client_auth_header,
    )
    assert assign_response.status_code == 200, assign_response.text

    client_workout_plan = db_session.get(ClientWorkoutPlan, assign_response.json()["client_workout_plan_id"])
    assert client_workout_plan is not None
    assert client_workout_plan.client_id == client_id
    assert client_workout_plan.workout_plan_id == workout_plan_id

