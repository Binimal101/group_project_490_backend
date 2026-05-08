from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from src.database.account.models import Availability, BusySlot
from src.database.client.models import ClientWorkoutPlan
from src.database.workouts_and_activities.models import WorkoutPlan


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
    if is_range_fully_available(db, account_id, start_dt, end_dt):
        conflicts = find_busy_conflicts(db, account_id, start_dt, end_dt)
        if not conflicts:
            return

    conflicts = find_busy_conflicts(db, account_id, start_dt, end_dt)
    if conflicts:
        _raise_conflict(
            f"You have {len(conflicts)} booked workout(s) in this window. Remove them first.",
            conflicts,
        )

    _raise_conflict(
        "The selected time window is not fully covered by availability.",
        [],
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
