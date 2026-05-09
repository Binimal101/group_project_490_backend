"""Tests for workout-plan versioning (VCS) and telemetry-based delete guard.

Rules under test
────────────────
1.  Modifying a plan (rename / add activity / remove activity) creates a new
    plan version and hides the old one.
2.  The new version is returned by the modification endpoint.
3.  Hidden plans do NOT appear in GET /query/workout_plan.
4.  Already-scheduled CWPs still reference the old (now hidden) plan — they
    are unaffected by the versioning operation.
5.  DELETE /plan/{id} is blocked (409) when any completed_workout row
    references one of the plan's activities.
6.  DELETE /plan/{id} succeeds (and hard-deletes) when no telemetry exists.
7.  Chained modifications produce a new version each time.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from src.database.workouts_and_activities.models import WorkoutPlan, WorkoutPlanActivity
from src.database.client.models import ClientWorkoutPlan
from src.database.telemetry.models import (
    ClientTelemetry,
    CompletedWorkout,
    CompletedWorkoutActivity,
)
from tests.payload_tools.fitness import build_create_plan_payload


# ── helpers ──────────────────────────────────────────────────────────────────

def _future_block(days: int = 7, hours: int = 2):
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=days)
    end = start + timedelta(hours=hours)
    return {"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": False}


def _create_plan(test_client, headers, seed_workout_activity, name="Test Plan") -> int:
    resp = test_client.post(
        "/roles/shared/fitness/plan",
        json=build_create_plan_payload(workout_activity_id=seed_workout_activity, strata_name=name),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["workout_plan_id"]


def _seed_telemetry_for_plan(db_session: Session, plan_id: int, client_id: int) -> None:
    """Insert a CompletedWorkout row that references the first activity of plan_id."""
    pa = db_session.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
    ).first()
    assert pa is not None, "Plan has no activities — cannot seed telemetry"

    telemetry = ClientTelemetry(
        client_id=client_id,
        date=datetime.now(timezone.utc).date(),
        type="workout",
    )
    db_session.add(telemetry)
    db_session.flush()

    cwa = CompletedWorkoutActivity(
        completed_reps=10,
        completed_sets=3,
    )
    db_session.add(cwa)
    db_session.flush()

    cw = CompletedWorkout(
        workout_plan_activity_id=pa.id,
        workout_activity_id=pa.workout_activity_id,
        completed_workout_details_id=cwa.id,
        client_telemetry_id=telemetry.id,
    )
    db_session.add(cw)
    db_session.commit()


# ── tests ────────────────────────────────────────────────────────────────────

class TestVCSRename:
    def test_rename_creates_new_version(self, test_client, client_auth_header, seed_workout_activity, db_session):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, "Original Name")

        resp = test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "Renamed Plan"},
            headers=client_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        new_id = data["id"]
        assert new_id != plan_id, "Rename must produce a new plan id"
        assert data["strata_name"] == "Renamed Plan"
        assert data["is_hidden"] is False

    def test_rename_hides_old_version(self, test_client, client_auth_header, seed_workout_activity, db_session):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "New Name"},
            headers=client_auth_header,
        )

        old = db_session.get(WorkoutPlan, plan_id)
        assert old is not None
        assert old.is_hidden is True

    def test_old_version_absent_from_query(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, "Will Be Hidden")

        test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "New Name"},
            headers=client_auth_header,
        )

        resp = test_client.get(
            "/roles/shared/fitness/query/workout_plan?mine_only=true",
            headers=client_auth_header,
        )
        assert resp.status_code == 200, resp.text
        ids = [p["id"] for p in resp.json()]
        assert plan_id not in ids, "Hidden (old) plan must not appear in query results"

    def test_new_version_appears_in_query(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        rename_resp = test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "New Name"},
            headers=client_auth_header,
        )
        new_id = rename_resp.json()["id"]

        resp = test_client.get(
            "/roles/shared/fitness/query/workout_plan?mine_only=true",
            headers=client_auth_header,
        )
        ids = [p["id"] for p in resp.json()]
        assert new_id in ids


class TestVCSAddActivity:
    def test_add_activity_creates_new_version(self, test_client, client_auth_header, seed_workout_activity, db_session):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        resp = test_client.post(
            f"/roles/shared/fitness/plan/{plan_id}/activity",
            json={"workout_activity_id": seed_workout_activity, "planned_reps": 8, "planned_sets": 4},
            headers=client_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["id"] != plan_id
        old = db_session.get(WorkoutPlan, plan_id)
        assert old.is_hidden is True

    def test_add_activity_new_version_has_all_activities(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        resp = test_client.post(
            f"/roles/shared/fitness/plan/{plan_id}/activity",
            json={"workout_activity_id": seed_workout_activity, "planned_reps": 8, "planned_sets": 4},
            headers=client_auth_header,
        )
        data = resp.json()
        assert len(data["activities"]) == 2, "New version should have original + newly added activity"


class TestVCSRemoveActivity:
    def test_remove_activity_creates_new_version(self, test_client, client_auth_header, seed_workout_activity, db_session):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)
        plan_data = test_client.get(
            "/roles/shared/fitness/query/workout_plan?mine_only=true",
            headers=client_auth_header,
        ).json()
        activity_id = next(p for p in plan_data if p["id"] == plan_id)["activities"][0]["id"]

        resp = test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}/activity/{activity_id}",
            headers=client_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["id"] != plan_id
        old = db_session.get(WorkoutPlan, plan_id)
        assert old.is_hidden is True

    def test_remove_activity_excluded_from_new_version(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)
        plan_data = test_client.get(
            "/roles/shared/fitness/query/workout_plan?mine_only=true",
            headers=client_auth_header,
        ).json()
        old_activity = next(p for p in plan_data if p["id"] == plan_id)["activities"][0]

        resp = test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}/activity/{old_activity['id']}",
            headers=client_auth_header,
        )
        data = resp.json()
        new_activity_ids = [a["id"] for a in data["activities"]]
        assert old_activity["id"] not in new_activity_ids, "Removed activity must not appear in new version"


class TestVCSChain:
    def test_chained_modifications_produce_new_version_each_time(
        self, test_client, client_auth_header, seed_workout_activity, db_session
    ):
        v1_id = _create_plan(test_client, client_auth_header, seed_workout_activity, "v1")

        v2_data = test_client.patch(
            f"/roles/shared/fitness/plan/{v1_id}",
            json={"strata_name": "v2"},
            headers=client_auth_header,
        ).json()
        v2_id = v2_data["id"]
        assert v2_id != v1_id

        v3_data = test_client.patch(
            f"/roles/shared/fitness/plan/{v2_id}",
            json={"strata_name": "v3"},
            headers=client_auth_header,
        ).json()
        v3_id = v3_data["id"]
        assert v3_id != v2_id
        assert v3_id != v1_id

        assert db_session.get(WorkoutPlan, v1_id).is_hidden is True
        assert db_session.get(WorkoutPlan, v2_id).is_hidden is True
        assert db_session.get(WorkoutPlan, v3_id).is_hidden is False

    def test_hidden_plan_cannot_be_modified(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        # Hide it via rename (produces a new version)
        test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "new name"},
            headers=client_auth_header,
        )

        # Attempt to rename the now-hidden original — should 404
        resp = test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "another name"},
            headers=client_auth_header,
        )
        assert resp.status_code == 404


class TestScheduledCWPUnaffected:
    def test_existing_cwp_still_references_old_plan_after_versioning(
        self, test_client, client_auth_header, seed_workout_activity, seed_availability, db_session
    ):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        # Schedule it against client availability
        block = _future_block()
        seed_availability(client_auth_header, start_dt=datetime.fromisoformat(block["start_dt"]),
                          end_dt=datetime.fromisoformat(block["end_dt"]))
        test_client.post(
            "/roles/client/assign_plan",
            json={"workout_plan_id": plan_id, "blocks": [block]},
            headers=client_auth_header,
        )

        # Rename the plan → creates new version, hides old
        test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "Updated Name"},
            headers=client_auth_header,
        )

        # The CWP must still reference the original plan
        cwp = db_session.exec(
            select(ClientWorkoutPlan).where(ClientWorkoutPlan.workout_plan_id == plan_id)
        ).first()
        assert cwp is not None, "CWP should still exist and reference the old plan"
        assert cwp.workout_plan_id == plan_id


class TestDeleteGuard:
    def test_delete_plan_without_telemetry_succeeds(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        resp = test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}",
            headers=client_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] == plan_id

    def test_delete_plan_with_telemetry_returns_409(
        self, test_client, client_auth_header, seed_workout_activity, db_session
    ):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        # Fetch the client_id from the account's client relationship
        me = test_client.get("/me", headers=client_auth_header).json()
        client_id = me["client_id"]

        _seed_telemetry_for_plan(db_session, plan_id, client_id)

        resp = test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}",
            headers=client_auth_header,
        )
        assert resp.status_code == 409, resp.text

    def test_delete_plan_with_telemetry_plan_still_exists(
        self, test_client, client_auth_header, seed_workout_activity, db_session
    ):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        me = test_client.get("/me", headers=client_auth_header).json()
        _seed_telemetry_for_plan(db_session, plan_id, me["client_id"])

        test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}",
            headers=client_auth_header,
        )

        plan = db_session.get(WorkoutPlan, plan_id)
        assert plan is not None, "Plan must not be hard-deleted when telemetry references it"

    def test_delete_non_owned_plan_returns_403(
        self, test_client, client_auth_header, create_client, seed_workout_activity
    ):
        # Another client creates a plan
        other_header, _ = create_client(email_prefix="other_owner")
        plan_id = _create_plan(test_client, other_header, seed_workout_activity)

        # Original client tries to delete it
        resp = test_client.delete(
            f"/roles/shared/fitness/plan/{plan_id}",
            headers=client_auth_header,
        )
        assert resp.status_code == 403


class TestHiddenNotInQuery:
    def test_hidden_plans_excluded_from_query(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity, "Hidden Plan")

        # Rename → hides original
        rename_resp = test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "Visible Name"},
            headers=client_auth_header,
        )
        new_id = rename_resp.json()["id"]

        query_resp = test_client.get(
            "/roles/shared/fitness/query/workout_plan?mine_only=true",
            headers=client_auth_header,
        )
        ids = {p["id"] for p in query_resp.json()}
        assert plan_id not in ids
        assert new_id in ids

    def test_all_plans_query_excludes_hidden(self, test_client, client_auth_header, seed_workout_activity):
        plan_id = _create_plan(test_client, client_auth_header, seed_workout_activity)

        test_client.patch(
            f"/roles/shared/fitness/plan/{plan_id}",
            json={"strata_name": "New"},
            headers=client_auth_header,
        )

        query_resp = test_client.get(
            "/roles/shared/fitness/query/workout_plan",
            headers=client_auth_header,
        )
        ids = {p["id"] for p in query_resp.json()}
        assert plan_id not in ids
