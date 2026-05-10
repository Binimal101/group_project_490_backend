from datetime import datetime, timedelta, timezone

from sqlmodel import select

from src.database.client.models import ClientWorkoutPlan
from src.database.telemetry.models import CompletedWorkout
from src.database.workouts_and_activities.models import WorkoutActivity, WorkoutPlan, WorkoutPlanActivity


def _future_block(days: int = 7, hours: int = 2):
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=days)
    end = start + timedelta(hours=hours)
    return start, end


def _create_plan(test_client, headers, seed_workout_activity, name="Test Plan") -> int:
    resp = test_client.post(
        "/roles/shared/fitness/plan",
        json={
            "strata_name": name,
            "activities": [
                {
                    "workout_activity_id": seed_workout_activity,
                    "planned_reps": 12,
                    "planned_sets": 3,
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["workout_plan_id"]


def _assign_plan(test_client, headers, plan_id: int, start: datetime, end: datetime):
    return test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_id,
            "blocks": [
                {
                    "start_dt": start.isoformat(),
                    "end_dt": end.isoformat(),
                }
            ],
        },
        headers=headers,
    )


def _log_workout(test_client, headers, *, cwp_id: int, workout_plan_activity_id: int, when: datetime):
    resp = test_client.post(
        "/roles/client/fitness/log_workout_activity",
        json={
            "cwp_id": cwp_id,
            "workout_plan_activity_id": workout_plan_activity_id,
            "local_date": when.date().isoformat(),
            "completed_reps": 10,
            "completed_sets": 3,
            "estimated_calories": 123.4,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _mine_only_plans(test_client, headers):
    resp = test_client.get(
        "/roles/shared/fitness/query/workout_plan?mine_only=true",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _public_activities(test_client, headers, workout_id: int):
    resp = test_client.get(
        f"/roles/shared/fitness/query/activity?workout_id={workout_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _telemetry_workouts(test_client, headers):
    resp = test_client.get("/roles/client/telemetry/query/workouts", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_renamed_plan_hidden_but_telemetry_kept(test_client, client_auth_header, seed_workout_activity, seed_availability, db_session):
    plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, name="Original Plan")
    plan_data = _mine_only_plans(test_client, client_auth_header)
    original_activity_id = plan_data[0]["activities"][0]["id"]

    start, end = _future_block()
    seed_availability(client_auth_header, start_dt=start, end_dt=end)
    assign_resp = _assign_plan(test_client, client_auth_header, plan_id, start, end)
    assert assign_resp.status_code == 200, assign_resp.text

    cwp = db_session.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.workout_plan_id == plan_id)).first()
    assert cwp is not None
    _log_workout(test_client, client_auth_header, cwp_id=cwp.id, workout_plan_activity_id=original_activity_id, when=start)

    rename_resp = test_client.patch(
        f"/roles/shared/fitness/plan/{plan_id}",
        json={"strata_name": "Renamed Plan"},
        headers=client_auth_header,
    )
    assert rename_resp.status_code == 200, rename_resp.text
    new_plan_id = rename_resp.json()["id"]

    visible_plans = _mine_only_plans(test_client, client_auth_header)
    visible_ids = [plan["id"] for plan in visible_plans]
    assert plan_id not in visible_ids
    assert new_plan_id in visible_ids

    old_plan = db_session.get(WorkoutPlan, plan_id)
    assert old_plan is not None
    assert old_plan.is_hidden is True
    assert db_session.get(ClientWorkoutPlan, cwp.id).workout_plan_id == plan_id

    workouts = _telemetry_workouts(test_client, client_auth_header)
    assert any(item["workout_plan_activity_id"] == original_activity_id for item in workouts)


def test_add_activity_forks_plan_and_keeps_old_log_visible(test_client, client_auth_header, seed_workout_activity, seed_availability, db_session):
    plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, name="Add Activity")
    plan_data = _mine_only_plans(test_client, client_auth_header)
    original_activity_id = plan_data[0]["activities"][0]["id"]

    start, end = _future_block(days=8)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)
    _assign_plan(test_client, client_auth_header, plan_id, start, end)
    cwp = db_session.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.workout_plan_id == plan_id)).first()
    assert cwp is not None
    _log_workout(test_client, client_auth_header, cwp_id=cwp.id, workout_plan_activity_id=original_activity_id, when=start)

    add_resp = test_client.post(
        f"/roles/shared/fitness/plan/{plan_id}/activity",
        json={
            "workout_activity_id": seed_workout_activity,
            "planned_reps": 8,
            "planned_sets": 4,
        },
        headers=client_auth_header,
    )
    assert add_resp.status_code == 200, add_resp.text
    new_plan_id = add_resp.json()["id"]

    visible_plans = _mine_only_plans(test_client, client_auth_header)
    visible_ids = [plan["id"] for plan in visible_plans]
    assert plan_id not in visible_ids
    assert new_plan_id in visible_ids

    old_plan = db_session.get(WorkoutPlan, plan_id)
    assert old_plan is not None and old_plan.is_hidden is True
    new_plan = db_session.get(WorkoutPlan, new_plan_id)
    assert new_plan is not None and new_plan.is_hidden is False

    new_plan_entry = next(plan for plan in visible_plans if plan["id"] == new_plan_id)
    assert len(new_plan_entry["activities"]) == 2
    assert original_activity_id not in [activity["id"] for activity in new_plan_entry["activities"]]

    workouts = _telemetry_workouts(test_client, client_auth_header)
    assert any(item["workout_plan_activity_id"] == original_activity_id for item in workouts)


def test_remove_activity_forks_plan_and_preserves_history(test_client, client_auth_header, seed_workout_activity, seed_availability, db_session):
    plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, name="Remove Activity")
    plan_data = _mine_only_plans(test_client, client_auth_header)
    original_activity_id = plan_data[0]["activities"][0]["id"]

    start, end = _future_block(days=9)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)
    _assign_plan(test_client, client_auth_header, plan_id, start, end)
    cwp = db_session.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.workout_plan_id == plan_id)).first()
    assert cwp is not None
    _log_workout(test_client, client_auth_header, cwp_id=cwp.id, workout_plan_activity_id=original_activity_id, when=start)

    remove_resp = test_client.delete(
        f"/roles/shared/fitness/plan/{plan_id}/activity/{original_activity_id}",
        headers=client_auth_header,
    )
    assert remove_resp.status_code == 200, remove_resp.text
    new_plan_id = remove_resp.json()["id"]

    visible_plans = _mine_only_plans(test_client, client_auth_header)
    visible_ids = [plan["id"] for plan in visible_plans]
    assert plan_id not in visible_ids
    assert new_plan_id in visible_ids

    new_plan_entry = next(plan for plan in visible_plans if plan["id"] == new_plan_id)
    assert new_plan_entry["activities"] == []

    old_plan_activity = db_session.exec(select(WorkoutPlanActivity).where(WorkoutPlanActivity.id == original_activity_id)).first()
    assert old_plan_activity is not None
    assert old_plan_activity.is_hidden is True

    workouts = _telemetry_workouts(test_client, client_auth_header)
    assert any(item["workout_plan_activity_id"] == original_activity_id for item in workouts)


def test_admin_activity_fork_hides_old_activity_but_keeps_telemetry(test_client, client_auth_header, admin_auth_header, seed_workout_activity, seed_workout, seed_availability, db_session):
    # Create a client-owned plan and log a workout against the activity that will be forked.
    plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, name="Activity Fork")
    plan_data = _mine_only_plans(test_client, client_auth_header)
    old_activity_id = plan_data[0]["activities"][0]["workout_activity_id"]

    start, end = _future_block(days=10)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)
    _assign_plan(test_client, client_auth_header, plan_id, start, end)
    cwp = db_session.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.workout_plan_id == plan_id)).first()
    assert cwp is not None
    original_plan_activity_id = plan_data[0]["activities"][0]["id"]
    completed_workout_id = _log_workout(
        test_client,
        client_auth_header,
        cwp_id=cwp.id,
        workout_plan_activity_id=original_plan_activity_id,
        when=start,
    )

    update_resp = test_client.patch(
        f"/roles/admin/fitness/activities/{old_activity_id}",
        json={"intensity_value": 999},
        headers=admin_auth_header,
    )
    assert update_resp.status_code == 200, update_resp.text
    new_activity_id = update_resp.json()["id"]

    public_activities = _public_activities(test_client, client_auth_header, seed_workout)
    public_ids = [activity["id"] for activity in public_activities]
    assert old_activity_id not in public_ids
    assert new_activity_id in public_ids

    admin_visible = test_client.get(
        f"/roles/admin/fitness/activities?workout_id={seed_workout}&include_hidden=true",
        headers=admin_auth_header,
    )
    assert admin_visible.status_code == 200, admin_visible.text
    admin_ids = [activity["id"] for activity in admin_visible.json()]
    assert old_activity_id in admin_ids
    assert new_activity_id in admin_ids

    old_activity = db_session.get(WorkoutActivity, old_activity_id)
    assert old_activity is not None and old_activity.is_hidden is True

    workouts = _telemetry_workouts(test_client, client_auth_header)
    assert any(item["workout_plan_activity_id"] == original_plan_activity_id for item in workouts)
    assert db_session.get(CompletedWorkout, completed_workout_id) is not None