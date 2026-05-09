from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from src.database.account.models import Availability, BusySlot
from src.database.client.models import ClientWorkoutPlan
from src.database.workouts_and_activities.models import WorkoutPlan, WorkoutPlanActivity, WorkoutActivity, Workout


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    return _ensure_aware(value)


def _overlaps(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


def _merge_intervals(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    ordered = sorted(intervals, key=lambda item: item[0])
    merged: List[Tuple[datetime, datetime]] = []
    for start_dt, end_dt in ordered:
        if not merged:
            merged.append((start_dt, end_dt))
            continue
        prev_start, prev_end = merged[-1]
        # contiguous (≤1 minute gap) or overlapping → merge
        if start_dt - prev_end <= timedelta(minutes=1):
            merged[-1] = (prev_start, max(prev_end, end_dt))
        else:
            merged.append((start_dt, end_dt))
    return merged


def _availability_occurrences_in_range(
    row: Availability,
    range_start: datetime,
    range_end: datetime,
) -> List[Tuple[datetime, datetime]]:
    start_dt = _normalize_datetime(row.start_dt)
    end_dt = _normalize_datetime(row.end_dt)
    cutoff = _normalize_datetime(row.recurrence_end_dt) if row.recurrence_end_dt is not None else None
    projected: List[Tuple[datetime, datetime]] = []

    if not row.repeats_weekly:
        if _overlaps(start_dt, end_dt, range_start, range_end):
            projected.append((max(start_dt, range_start), min(end_dt, range_end)))
        return projected

    while end_dt <= range_start:
        start_dt += timedelta(days=7)
        end_dt += timedelta(days=7)

    while start_dt < range_end:
        if cutoff is not None and start_dt >= cutoff:
            break
        if _overlaps(start_dt, end_dt, range_start, range_end):
            projected.append((max(start_dt, range_start), min(end_dt, range_end)))
        start_dt += timedelta(days=7)
        end_dt += timedelta(days=7)

    return projected


def project_availability(rows: List[Availability], range_start: datetime, range_end: datetime) -> List[Tuple[datetime, datetime]]:
    range_start = _normalize_datetime(range_start)
    range_end = _normalize_datetime(range_end)
    intervals: List[Tuple[datetime, datetime]] = []
    for row in rows:
        intervals.extend(_availability_occurrences_in_range(row, range_start, range_end))
    return _merge_intervals(intervals)


def find_busy_conflicts(db: Session, account_id: int, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
    start_dt = _normalize_datetime(start_dt)
    end_dt = _normalize_datetime(end_dt)
    conflicts: List[Dict[str, Any]] = []
    busy_slots = list(db.exec(select(BusySlot).where(BusySlot.account_id == account_id)).all())

    for busy_slot in busy_slots:
        if busy_slot.start_dt is None or busy_slot.end_dt is None:
            continue
        busy_start = _normalize_datetime(busy_slot.start_dt)
        busy_end = _normalize_datetime(busy_slot.end_dt)
        if not _overlaps(busy_start, busy_end, start_dt, end_dt):
            continue

        source_workout_plan_id = busy_slot.source_id if busy_slot.source == "workout_plan" else None
        source_workout_plan_name = None
        if source_workout_plan_id is not None:
            source_plan = db.get(ClientWorkoutPlan, source_workout_plan_id)
            if source_plan is not None:
                workout_plan = db.get(WorkoutPlan, source_plan.workout_plan_id)
                if workout_plan is not None:
                    source_workout_plan_name = workout_plan.strata_name

        conflicts.append(
            {
                "busy_slot_id": busy_slot.id,
                "source": busy_slot.source,
                "source_id": busy_slot.source_id,
                "source_name": busy_slot.note or busy_slot.source,
                "source_workout_plan_id": source_workout_plan_id,
                "source_workout_plan_name": source_workout_plan_name,
                "start_dt": busy_start.isoformat(),
                "end_dt": busy_end.isoformat(),
            }
        )

    # Project recurring CWPs into the requested window.
    # create_busy_for_plan only creates a BusySlot for the first occurrence;
    # future week occurrences must be derived from the CWP itself.
    for busy_slot in busy_slots:
        if busy_slot.source != "workout_plan" or busy_slot.source_id is None:
            continue
        cwp = db.get(ClientWorkoutPlan, busy_slot.source_id)
        if cwp is None or not cwp.repeats_weekly:
            continue
        workout_plan = db.get(WorkoutPlan, cwp.workout_plan_id)
        plan_name = workout_plan.strata_name if workout_plan else None
        bs_start = _normalize_datetime(busy_slot.start_dt)
        for occ_start, occ_end in _cwp_occurrences_in_range(cwp, start_dt, end_dt):
            # Skip the occurrence already covered by the BusySlot row
            if abs((occ_start - bs_start).total_seconds()) < 60:
                continue
            conflicts.append(
                {
                    "busy_slot_id": None,
                    "source": "workout_plan",
                    "source_id": cwp.id,
                    "source_name": plan_name or "Recurring workout",
                    "source_workout_plan_id": cwp.id,
                    "source_workout_plan_name": plan_name,
                    "start_dt": occ_start.isoformat(),
                    "end_dt": occ_end.isoformat(),
                }
            )

    return conflicts


def is_range_fully_available(db: Session, account_id: int, start_dt: datetime, end_dt: datetime) -> bool:
    rows = list(db.exec(select(Availability).where(Availability.account_id == account_id)).all())
    if not rows:
        return False

    projected = project_availability(rows, start_dt, end_dt)
    if not projected:
        return False

    cursor = _normalize_datetime(start_dt)
    target = _normalize_datetime(end_dt)
    for interval_start, interval_end in projected:
        if interval_start > cursor:
            return False
        if interval_end > cursor:
            cursor = interval_end
        if cursor >= target:
            return True
    return cursor >= target


def _raise_conflict(detail: str, conflicts: List[Dict[str, Any]]) -> None:
    raise HTTPException(
        409,
        detail={
            "detail": detail,
            "conflicts": conflicts,
        },
    )


def validate_schedulable(db: Session, account_id: int, start_dt: datetime, end_dt: datetime) -> None:
    now = datetime.now(timezone.utc)
    start_aware = _ensure_aware(start_dt)

    # Reject if the intended slot is in the past.
    # Same-day is fine (hour discrepancies are acceptable); only reject if the
    # start date is a previous calendar day AND more than 5 hours in the past.
    if start_aware < now:
        hours_ago = (now - start_aware).total_seconds() / 3600
        if hours_ago > 5:
            raise HTTPException(
                status_code=400,
                detail="Cannot schedule a workout plan in the past.",
            )

    if not is_range_fully_available(db, account_id, start_dt, end_dt):
        _raise_conflict(
            "The selected time window is not fully covered by your availability.",
            [],
        )

    conflicts = find_busy_conflicts(db, account_id, start_dt, end_dt)
    if conflicts:
        _raise_conflict(
            f"You have {len(conflicts)} booked workout(s) in this window. Remove them first.",
            conflicts,
        )


def validate_availability_edit_safe(
    db: Session,
    account_id: int,
    removed_ranges: List[Tuple[datetime, datetime]],
) -> None:
    conflicts: List[Dict[str, Any]] = []
    for start_dt, end_dt in removed_ranges:
        conflicts.extend(find_busy_conflicts(db, account_id, start_dt, end_dt))

    if conflicts:
        _raise_conflict(
            f"You have {len(conflicts)} booked workout(s) in this window. Remove them first.",
            conflicts,
        )


def create_busy_for_plan(db: Session, account_id: int, plan_id: int, start_dt: datetime, end_dt: datetime) -> BusySlot:
    busy_slot = BusySlot(
        account_id=account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        source="workout_plan",
        source_id=plan_id,
    )
    db.add(busy_slot)
    db.flush()
    return busy_slot


def create_manual_busy_slot(db: Session, account_id: int, start_dt: datetime, end_dt: datetime, note: str | None = None) -> BusySlot:
    busy_slot = BusySlot(
        account_id=account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        source="manual",
        note=note,
    )
    db.add(busy_slot)
    db.flush()
    return busy_slot


def list_busy_slots_for_account(db: Session, account_id: int, range_start: datetime, range_end: datetime) -> List[Dict[str, Any]]:
    start_dt = _normalize_datetime(range_start)
    end_dt = _normalize_datetime(range_end)
    rows = list(db.exec(select(BusySlot).where(BusySlot.account_id == account_id)).all())
    payload: List[Dict[str, Any]] = []

    for busy_slot in rows:
        if busy_slot.start_dt is None or busy_slot.end_dt is None:
            continue
        busy_start = _normalize_datetime(busy_slot.start_dt)
        busy_end = _normalize_datetime(busy_slot.end_dt)
        if not _overlaps(busy_start, busy_end, start_dt, end_dt):
            continue

        source_name = busy_slot.note or "Busy slot"
        source_link = None
        if busy_slot.source == "workout_plan" and busy_slot.source_id is not None:
            source_plan = db.get(ClientWorkoutPlan, busy_slot.source_id)
            if source_plan is not None:
                workout_plan = db.get(WorkoutPlan, source_plan.workout_plan_id)
                if workout_plan is not None:
                    source_name = workout_plan.strata_name
                source_link = f"/plan-my-week?focus=cwp&id={source_plan.id}"

        payload.append(
            {
                "busy_slot_id": busy_slot.id,
                "account_id": busy_slot.account_id,
                "start_dt": busy_start.isoformat(),
                "end_dt": busy_end.isoformat(),
                "source": busy_slot.source,
                "source_id": busy_slot.source_id,
                "source_name": source_name,
                "source_link": source_link,
                "note": busy_slot.note,
            }
        )

    return payload


def remove_busy_for_plan(db: Session, plan_id: int) -> int:
    busy_slots = list(db.exec(select(BusySlot).where(BusySlot.source == "workout_plan", BusySlot.source_id == plan_id)).all())
    removed = 0
    for busy_slot in busy_slots:
        db.delete(busy_slot)
        removed += 1
    db.flush()
    return removed


def delete_busy_slot_row(db: Session, account_id: int, busy_slot_id: int) -> None:
    busy_slot = db.get(BusySlot, busy_slot_id)
    if busy_slot is None or busy_slot.account_id != account_id:
        raise HTTPException(404, detail="Busy slot not found")
    if busy_slot.source != "manual":
        raise HTTPException(403, detail="Only manual busy slots can be deleted directly")
    db.delete(busy_slot)
    db.flush()


def _cwp_occurrences_in_range(
    cwp: "ClientWorkoutPlan",
    range_start: datetime,
    range_end: datetime,
) -> List[Tuple[datetime, datetime]]:
    """Project a ClientWorkoutPlan into concrete (start, end) occurrences within the range."""
    start_dt = _normalize_datetime(cwp.start_time)
    end_dt = _normalize_datetime(cwp.end_time)
    cutoff = _normalize_datetime(cwp.recurrence_end_dt) if cwp.recurrence_end_dt is not None else None
    projected: List[Tuple[datetime, datetime]] = []

    if not cwp.repeats_weekly:
        if _overlaps(start_dt, end_dt, range_start, range_end):
            projected.append((start_dt, end_dt))
        return projected

    while end_dt <= range_start:
        start_dt += timedelta(days=7)
        end_dt += timedelta(days=7)

    while start_dt < range_end:
        if cutoff is not None and start_dt >= cutoff:
            break
        if _overlaps(start_dt, end_dt, range_start, range_end):
            projected.append((start_dt, end_dt))
        start_dt += timedelta(days=7)
        end_dt += timedelta(days=7)

    return projected


def _enrich_cwp(db: Session, cwp: ClientWorkoutPlan, occurrences: list) -> Dict[str, Any]:
    plan = db.get(WorkoutPlan, cwp.workout_plan_id)
    plan_activities: List[Dict[str, Any]] = []
    if plan is not None:
        for pa in db.exec(select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan.id)).all():
            activity = db.get(WorkoutActivity, pa.workout_activity_id)
            workout = db.get(Workout, activity.workout_id) if activity else None
            plan_activities.append({
                "id": pa.id,
                "workout_activity_id": pa.workout_activity_id,
                "workout_id": activity.workout_id if activity else None,
                "workout_name": workout.name if workout else None,
                "workout_type": workout.workout_type if workout else None,
                "intensity_measure": activity.intensity_measure if activity else None,
                "intensity_value": activity.intensity_value if activity else None,
                "planned_reps": pa.planned_reps,
                "planned_sets": pa.planned_sets,
                "planned_duration": pa.planned_duration,
                "estimated_calories": float(pa.estimated_calories) if pa.estimated_calories is not None else None,
            })
    return {
        "id": cwp.id,
        "client_id": cwp.client_id,
        "workout_plan_id": cwp.workout_plan_id,
        "strata_name": plan.strata_name if plan else None,
        "is_public": plan.is_public if plan else False,
        "is_hidden": plan.is_hidden if plan else False,
        "created_by_account_id": plan.created_by_account_id if plan else None,
        "start_time": _normalize_datetime(cwp.start_time).isoformat(),
        "end_time": _normalize_datetime(cwp.end_time).isoformat(),
        "repeats_weekly": cwp.repeats_weekly,
        "recurrence_end_dt": _normalize_datetime(cwp.recurrence_end_dt).isoformat() if cwp.recurrence_end_dt else None,
        "occurrences": [
            {"start_dt": s.isoformat(), "end_dt": e.isoformat()}
            for s, e in occurrences
        ],
        "activities": plan_activities,
    }


def list_scheduled_plans_for_client_in_range(
    db: Session,
    client_id: int,
    range_start: datetime,
    range_end: datetime,
) -> List[Dict[str, Any]]:
    range_start = _normalize_datetime(range_start)
    range_end = _normalize_datetime(range_end)
    cwps = list(db.exec(select(ClientWorkoutPlan).where(ClientWorkoutPlan.client_id == client_id)).all())
    result: List[Dict[str, Any]] = []
    for cwp in cwps:
        occurrences = _cwp_occurrences_in_range(cwp, range_start, range_end)
        if not occurrences and cwp.repeats_weekly:
            continue
        result.append(_enrich_cwp(db, cwp, occurrences))
    return result


def get_account_availability_rows(db: Session, account_id: int) -> List[Availability]:
    return list(db.exec(select(Availability).where(Availability.account_id == account_id)).all())


def list_availability_for_account(db: Session, account_id: int, range_start: datetime, range_end: datetime) -> List[Dict[str, Any]]:
    rows = get_account_availability_rows(db, account_id)
    payload: List[Dict[str, Any]] = []

    for row in rows:
        occurrences = _availability_occurrences_in_range(row, range_start, range_end)
        payload.append(
            {
                "id": row.id,
                "account_id": row.account_id,
                "start_dt": row.start_dt.isoformat(),
                "end_dt": row.end_dt.isoformat(),
                "repeats_weekly": row.repeats_weekly,
                "recurrence_end_dt": row.recurrence_end_dt.isoformat() if row.recurrence_end_dt is not None else None,
                "max_time_commitment_seconds": float(row.max_time_commitment_seconds) if row.max_time_commitment_seconds is not None else None,
                "occurrences": [
                    {
                        "start_dt": occurrence_start.isoformat(),
                        "end_dt": occurrence_end.isoformat(),
                    }
                    for occurrence_start, occurrence_end in occurrences
                ],
            }
        )

    return payload


def create_availability_row(
    db: Session,
    account_id: int,
    *,
    start_dt: datetime,
    end_dt: datetime,
    repeats_weekly: bool = False,
    recurrence_end_dt: datetime | None = None,
    max_time_commitment_seconds: Any = None,
) -> Availability:
    row = Availability(
        account_id=account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        repeats_weekly=repeats_weekly,
        recurrence_end_dt=recurrence_end_dt,
        max_time_commitment_seconds=max_time_commitment_seconds,
    )
    db.add(row)
    db.flush()
    return row


def delete_availability_row(db: Session, account_id: int, availability_id: int) -> None:
    row = db.get(Availability, availability_id)
    if row is None or row.account_id != account_id:
        raise HTTPException(404, detail="Availability not found")

    validate_availability_edit_safe(db, account_id, [(row.start_dt, row.end_dt)])

    db.delete(row)
    db.flush()


def update_availability_row(
    db: Session,
    account_id: int,
    availability_id: int,
    *,
    start_dt: datetime,
    end_dt: datetime,
    repeats_weekly: bool = False,
    recurrence_end_dt: datetime | None = None,
    max_time_commitment_seconds: Any = None,
) -> Availability:
    delete_availability_row(db, account_id, availability_id)
    return create_availability_row(
        db,
        account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        repeats_weekly=repeats_weekly,
        recurrence_end_dt=recurrence_end_dt,
        max_time_commitment_seconds=max_time_commitment_seconds,
    )
