"""
Tests for availability validation during workout plan scheduling.

Coverage:
  - full_availability          : single window covers the full block → 200
  - merging_contiguous         : two rows with ≤1-min gap merge into one → 200
  - gap_too_large              : two rows with 2-min gap do NOT merge    → 409
  - no_availability            : no rows at all                          → 409
  - partial_no_busy            : coverage ends before block end          → 409
  - full_avail_with_busy       : full coverage but busy slot overlaps    → 409 (conflicts)
  - partial_avail_with_busy    : partial coverage AND busy slot          → 409 (not-covered)
  - minute_precision           : sub-hour window inside wider avail      → 200
  - coach_prescribe_full_avail : coach prescribes into client avail      → 200
  - coach_prescribe_no_avail   : coach prescribes without client avail   → 409
"""

from datetime import datetime, timedelta, timezone

import pytest
from src.database.account.models import BusySlot
from src.database.coach_client_relationship.models import (
    ClientCoachRelationship,
    ClientCoachRequest,
)
from tests.payload_tools.fitness import build_create_plan_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future(days: int = 21, hour: int = 10) -> datetime:
    base = datetime.now(timezone.utc).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return base + timedelta(days=days)


def _make_plan(test_client, auth_header, seed_workout_activity):
    payload = build_create_plan_payload(workout_activity_id=seed_workout_activity)
    resp = test_client.post("/roles/shared/fitness/plan", json=payload, headers=auth_header)
    assert resp.status_code == 200, f"plan creation failed: {resp.text}"
    return resp.json()["workout_plan_id"]


def _client_account_id(test_client, auth_header) -> int:
    resp = test_client.post("/roles/client/me", headers=auth_header)
    assert resp.status_code == 200
    return resp.json()["base_account"]["id"]


def _assign(test_client, auth_header, plan_id, start, end):
    return test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat()}],
        },
        headers=auth_header,
    )


def _setup_coach_client(test_client, create_client, coach_auth_header, db_session, email_prefix):
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    client_header, client_id = create_client(email_prefix=email_prefix)
    req = ClientCoachRequest(client_id=client_id, coach_id=coach_id, is_accepted=True)
    db_session.add(req)
    db_session.flush()
    db_session.add(
        ClientCoachRelationship(
            request_id=req.id,
            created_at=datetime.now(timezone.utc),
            is_active=True,
        )
    )
    db_session.commit()
    return client_header, client_id


# ---------------------------------------------------------------------------
# Client self-assign tests
# ---------------------------------------------------------------------------

def test_assign_full_availability(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Single availability row covering the full block → 200."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 200, resp.text


def test_assign_no_availability(
    test_client, client_auth_header, seed_workout_activity
):
    """No availability rows at all → 409 not-covered."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    msg = (detail.get("detail") or "").lower()
    assert "not fully covered" in msg or "availability" in msg


def test_assign_partial_availability_no_busy(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Availability covers only the first half of the requested block → 409."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    # availability ends 30 minutes before the block ends
    seed_availability(client_auth_header, start_dt=start, end_dt=end - timedelta(minutes=30))

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 409, resp.text


def test_assign_full_availability_with_busy_slot(
    test_client, client_auth_header, seed_workout_activity, seed_availability, db_session
):
    """Full availability window + overlapping busy slot → 409 with conflict details."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    account_id = _client_account_id(test_client, client_auth_header)
    busy = BusySlot(
        account_id=account_id,
        start_dt=start + timedelta(minutes=30),
        end_dt=start + timedelta(hours=1),
        source="manual",
        note="test block",
    )
    db_session.add(busy)
    db_session.commit()

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 409, resp.text
    conflicts = resp.json().get("detail", {}).get("conflicts", [])
    assert len(conflicts) >= 1


def test_assign_partial_availability_with_busy_slot(
    test_client, client_auth_header, seed_workout_activity, seed_availability, db_session
):
    """Partial availability coverage AND a busy slot in the gap → 409."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    # Only first hour is available
    seed_availability(client_auth_header, start_dt=start, end_dt=start + timedelta(hours=1))

    account_id = _client_account_id(test_client, client_auth_header)
    busy = BusySlot(
        account_id=account_id,
        start_dt=start + timedelta(minutes=90),
        end_dt=end,
        source="manual",
        note="test block",
    )
    db_session.add(busy)
    db_session.commit()

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 409, resp.text


def test_assign_merged_contiguous_availability(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Two rows with exactly a 1-minute gap merge into a single window → 200."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    mid = start + timedelta(hours=1)

    seed_availability(client_auth_header, start_dt=start, end_dt=mid)
    # Row B starts exactly 1 minute after Row A ends (within the ≤1 min merge threshold)
    seed_availability(client_auth_header, start_dt=mid + timedelta(minutes=1), end_dt=end)

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 200, resp.text


def test_assign_gap_too_large_not_merged(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Two rows with a 2-minute gap do NOT merge — the gap is uncovered → 409."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=2)
    mid = start + timedelta(hours=1)

    seed_availability(client_auth_header, start_dt=start, end_dt=mid)
    # 2-minute gap exceeds the merge threshold
    seed_availability(client_auth_header, start_dt=mid + timedelta(minutes=2), end_dt=end)

    resp = _assign(test_client, client_auth_header, plan_id, start, end)
    assert resp.status_code == 409, resp.text


def test_assign_minute_precision_within_availability(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Block defined to the minute, fully inside a wider availability window → 200."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    avail_start = _future()
    avail_end = avail_start + timedelta(hours=3)
    seed_availability(client_auth_header, start_dt=avail_start, end_dt=avail_end)

    block_start = avail_start + timedelta(minutes=17)
    block_end = avail_start + timedelta(hours=1, minutes=43)

    resp = _assign(test_client, client_auth_header, plan_id, block_start, block_end)
    assert resp.status_code == 200, resp.text


def test_assign_minute_precision_overflows_availability(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Block ends 1 minute past the availability window → 409."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    avail_start = _future()
    avail_end = avail_start + timedelta(hours=2)
    seed_availability(client_auth_header, start_dt=avail_start, end_dt=avail_end)

    block_start = avail_start
    block_end = avail_end + timedelta(minutes=1)

    resp = _assign(test_client, client_auth_header, plan_id, block_start, block_end)
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Coach-prescription tests
# ---------------------------------------------------------------------------

def test_prescribe_full_availability(
    test_client, create_client, coach_auth_header, seed_workout_activity, db_session, seed_availability
):
    """Coach prescribes into a window fully covered by the client's availability → 200."""
    plan_id = _make_plan(test_client, coach_auth_header, seed_workout_activity)
    client_header, client_id = _setup_coach_client(
        test_client, create_client, coach_auth_header, db_session, "prescribe_full"
    )

    start = _future(days=22)
    end = start + timedelta(hours=2)
    seed_availability(client_header, start_dt=start, end_dt=end)

    resp = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": plan_id,
            "client_id": client_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat()}],
        },
        headers=coach_auth_header,
    )
    assert resp.status_code == 200, resp.text


def test_prescribe_no_availability(
    test_client, create_client, coach_auth_header, seed_workout_activity, db_session
):
    """Coach prescribes when the client has no availability → 409."""
    plan_id = _make_plan(test_client, coach_auth_header, seed_workout_activity)
    _, client_id = _setup_coach_client(
        test_client, create_client, coach_auth_header, db_session, "prescribe_no_avail"
    )

    start = _future(days=22)
    end = start + timedelta(hours=2)

    resp = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": plan_id,
            "client_id": client_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat()}],
        },
        headers=coach_auth_header,
    )
    assert resp.status_code == 409, resp.text


def test_prescribe_merged_contiguous_availability(
    test_client, create_client, coach_auth_header, seed_workout_activity, db_session, seed_availability
):
    """Coach prescribes across two contiguous client availability rows (1-min gap) → 200."""
    plan_id = _make_plan(test_client, coach_auth_header, seed_workout_activity)
    client_header, client_id = _setup_coach_client(
        test_client, create_client, coach_auth_header, db_session, "prescribe_merge"
    )

    start = _future(days=22)
    end = start + timedelta(hours=2)
    mid = start + timedelta(hours=1)

    seed_availability(client_header, start_dt=start, end_dt=mid)
    seed_availability(client_header, start_dt=mid + timedelta(minutes=1), end_dt=end)

    resp = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": plan_id,
            "client_id": client_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat()}],
        },
        headers=coach_auth_header,
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Recurring client_workout_plan tests
# ---------------------------------------------------------------------------

def test_assign_repeats_weekly_creates_cwp(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Client self-assigns a recurring weekly plan — CWP is created with repeats_weekly=True."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1, minutes=30)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": True}],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text
    cwp_ids = resp.json()["client_workout_plan_ids"]
    assert len(cwp_ids) == 1


def test_assign_repeats_weekly_with_recurrence_end(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """Client assigns a recurring weekly plan with an explicit end date — field is stored."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)
    recur_end = start + timedelta(weeks=4)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_id,
            "blocks": [{
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
                "recurrence_end_dt": recur_end.isoformat(),
            }],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text


def test_recurring_cwp_projected_in_query(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """A weekly-recurring CWP appears on multiple weeks when queried with a wide range."""
    plan_id = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    assign_resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": True}],
        },
        headers=client_auth_header,
    )
    assert assign_resp.status_code == 200, assign_resp.text

    query_from = start.isoformat()
    query_to = (start + timedelta(weeks=3)).isoformat()
    resp = test_client.get(
        f"/roles/client/fitness/query/plans?from_dt={query_from}&to_dt={query_to}",
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    matching = [r for r in rows if r["workout_plan_id"] == plan_id]
    assert len(matching) >= 1
    total_occurrences = sum(len(r.get("occurrences", [])) for r in matching)
    assert total_occurrences >= 2, f"Expected >=2 occurrences, got {total_occurrences}"


def test_check_schedulable_endpoint_ok(
    test_client, client_auth_header, seed_availability
):
    """check_schedulable returns 200 when the window is fully available."""
    start = _future()
    end = start + timedelta(hours=1)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)

    resp = test_client.post(
        "/roles/client/check_schedulable",
        json={"start_dt": start.isoformat(), "end_dt": end.isoformat()},
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text


def test_check_schedulable_endpoint_fails(
    test_client, client_auth_header
):
    """check_schedulable returns 409 when no availability exists for the window."""
    start = _future()
    end = start + timedelta(hours=1)

    resp = test_client.post(
        "/roles/client/check_schedulable",
        json={"start_dt": start.isoformat(), "end_dt": end.isoformat()},
        headers=client_auth_header,
    )
    assert resp.status_code == 409, resp.text


def test_prescribe_recurring_plan(
    test_client, create_client, coach_auth_header, seed_workout_activity, db_session, seed_availability
):
    """Coach prescribes a recurring weekly plan to a client → 200."""
    plan_id = _make_plan(test_client, coach_auth_header, seed_workout_activity)
    client_header, client_id = _setup_coach_client(
        test_client, create_client, coach_auth_header, db_session, "prescribe_recurring"
    )

    start = _future(days=23)
    end = start + timedelta(hours=1)
    seed_availability(client_header, start_dt=start, end_dt=end)

    resp = test_client.post(
        "/roles/coach/prescribe_plan",
        json={
            "workout_plan_id": plan_id,
            "client_id": client_id,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": True}],
        },
        headers=coach_auth_header,
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Recurring CWP conflict tests
# ---------------------------------------------------------------------------

def test_recurring_cwp_conflicts_with_same_slot_next_week_static_avail(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """A recurring weekly CWP conflicts when a second plan targets the same slot next week,
    even though only a static BusySlot was created for the first occurrence."""
    plan_a = _make_plan(test_client, client_auth_header, seed_workout_activity)
    plan_b = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)
    # Cover two consecutive same-day slots (this week and next)
    seed_availability(client_auth_header, start_dt=start, end_dt=end)
    seed_availability(client_auth_header, start_dt=start + timedelta(weeks=1), end_dt=end + timedelta(weeks=1))

    # Assign plan A as a recurring weekly plan
    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_a,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": True}],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # Plan B targets the same time slot next week → projected recurring CWP should conflict
    start2 = start + timedelta(weeks=1)
    end2 = end + timedelta(weeks=1)
    resp2 = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_b,
            "blocks": [{"start_dt": start2.isoformat(), "end_dt": end2.isoformat()}],
        },
        headers=client_auth_header,
    )
    assert resp2.status_code == 409, resp2.text
    conflicts = resp2.json().get("detail", {}).get("conflicts", [])
    assert len(conflicts) >= 1


def test_recurring_cwp_conflict_before_recurrence_end_dt(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """A recurring CWP with recurrence_end_dt still blocks slots before the cutoff → 409."""
    plan_a = _make_plan(test_client, client_auth_header, seed_workout_activity)
    plan_b = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)
    recur_end = start + timedelta(weeks=4)

    # Wide availability covering the recurring window
    seed_availability(client_auth_header, start_dt=start, end_dt=start + timedelta(weeks=5))

    # Assign plan A as recurring with explicit end date
    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_a,
            "blocks": [{
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
                "recurrence_end_dt": recur_end.isoformat(),
            }],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # Week 2 (within recurring window) → 409 conflict
    start2 = start + timedelta(weeks=2)
    end2 = end + timedelta(weeks=2)
    resp2 = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_b,
            "blocks": [{"start_dt": start2.isoformat(), "end_dt": end2.isoformat()}],
        },
        headers=client_auth_header,
    )
    assert resp2.status_code == 409, resp2.text


def test_recurring_cwp_no_conflict_after_recurrence_end_dt(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """A recurring CWP with recurrence_end_dt does NOT block slots after the cutoff → 200."""
    plan_a = _make_plan(test_client, client_auth_header, seed_workout_activity)
    plan_b = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)
    # Recurrence ends after 2 weeks
    recur_end = start + timedelta(weeks=2)

    # Wide availability
    seed_availability(client_auth_header, start_dt=start, end_dt=start + timedelta(weeks=5))

    # Assign plan A as recurring, expiring at week 2
    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_a,
            "blocks": [{
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
                "recurrence_end_dt": recur_end.isoformat(),
            }],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # Week 3 (past recurrence_end_dt) → no conflict, should succeed
    start3 = start + timedelta(weeks=3)
    end3 = end + timedelta(weeks=3)
    resp3 = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_b,
            "blocks": [{"start_dt": start3.isoformat(), "end_dt": end3.isoformat()}],
        },
        headers=client_auth_header,
    )
    assert resp3.status_code == 200, resp3.text


def test_recurring_cwp_conflicts_with_repeating_weekly_availability_slot(
    test_client, client_auth_header, seed_workout_activity, seed_availability
):
    """A recurring CWP conflicts with a new plan on the same weekly slot,
    even when the client's availability is itself set to repeat weekly."""
    plan_a = _make_plan(test_client, client_auth_header, seed_workout_activity)
    plan_b = _make_plan(test_client, client_auth_header, seed_workout_activity)
    start = _future()
    end = start + timedelta(hours=1)

    # Repeating weekly availability covers every week indefinitely
    seed_availability(client_auth_header, start_dt=start, end_dt=end, repeats_weekly=True)

    # Assign plan A as recurring weekly
    resp = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_a,
            "blocks": [{"start_dt": start.isoformat(), "end_dt": end.isoformat(), "repeats_weekly": True}],
        },
        headers=client_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # Plan B targets same slot next week — availability covers it, but CWP recurrence conflicts
    start2 = start + timedelta(weeks=1)
    end2 = end + timedelta(weeks=1)
    resp2 = test_client.post(
        "/roles/client/assign_plan",
        json={
            "workout_plan_id": plan_b,
            "blocks": [{"start_dt": start2.isoformat(), "end_dt": end2.isoformat()}],
        },
        headers=client_auth_header,
    )
    assert resp2.status_code == 409, resp2.text
    conflicts = resp2.json().get("detail", {}).get("conflicts", [])
    assert len(conflicts) >= 1
