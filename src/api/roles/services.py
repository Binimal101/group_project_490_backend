from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from src.database.account.models import Availability, BusySlot, Weekday
from src.database.client.models import Client, ClientWorkoutPlan
from src.database.workouts_and_activities.models import WorkoutPlan


_WEEKDAY_BY_INDEX = [
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
    Weekday.SATURDAY,
    Weekday.SUNDAY,
]


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _time_to_seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _seconds_to_time(seconds: int, tzinfo=None) -> time:
    if seconds < 0 or seconds >= 86400:
        raise ValueError(f"seconds out of day range: {seconds}")
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return time(h, m, s, tzinfo=tzinfo)


def _block_to_weekday_segment(start_dt: datetime, end_dt: datetime) -> Tuple[Weekday, time, time]:
    """A block must be on a single calendar day (UTC). Returns (weekday, start_time, end_time)."""
    start_dt = _ensure_aware(start_dt)
    end_dt = _ensure_aware(end_dt)
    if start_dt >= end_dt:
        raise HTTPException(400, detail="start_dt must be before end_dt")
    if start_dt.date() != end_dt.date():
        # Allow exact-midnight boundary (end_dt at 00:00 of next day = end of start day)
        midnight_next = datetime.combine(
            start_dt.date() + timedelta(days=1), time.min, tzinfo=start_dt.tzinfo
        )
        if end_dt != midnight_next:
            raise HTTPException(
                400,
                detail="Each block must fall on a single calendar day. Split overnight bookings into separate blocks.",
            )
        # Treat midnight-end as 23:59:59 for time-of-day storage
        seg_end = time(23, 59, 59, tzinfo=start_dt.tzinfo)
    else:
        seg_end = end_dt.timetz()

    weekday = _WEEKDAY_BY_INDEX[start_dt.weekday()]
    seg_start = start_dt.timetz()
    return weekday, seg_start, seg_end


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
        if start_dt <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end_dt))
        else:
            merged.append((start_dt, end_dt))
    return merged


def _normalize_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _availability_occurrences_in_range(
    row: Availability,
    range_start: datetime,
    range_end: datetime,
) -> List[Tuple[datetime, datetime]]:
    if row.start_dt is None or row.end_dt is None:
        return []

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
    for interval_start, interval_end in projected:
        if interval_start > cursor:
            return False
        if interval_end > cursor:
            cursor = interval_end
        if cursor >= _normalize_datetime(end_dt):
            return True
    return cursor >= _normalize_datetime(end_dt)


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
    projected = {row.id: _availability_occurrences_in_range(row, range_start, range_end) for row in rows}
    payload: List[Dict[str, Any]] = []

    for row in rows:
        occurrences = projected.get(row.id, [])
        payload.append(
            {
                "id": row.id,
                "account_id": row.account_id,
                "start_dt": row.start_dt.isoformat() if row.start_dt is not None else None,
                "end_dt": row.end_dt.isoformat() if row.end_dt is not None else None,
                "repeats_weekly": row.repeats_weekly,
                "recurrence_end_dt": row.recurrence_end_dt.isoformat() if row.recurrence_end_dt is not None else None,
                "weekday": row.weekday,
                "start_time": row.start_time.isoformat() if row.start_time is not None else None,
                "end_time": row.end_time.isoformat() if row.end_time is not None else None,
                "max_time_commitment_seconds": float(row.max_time_commitment_seconds) if row.max_time_commitment_seconds is not None else None,
                "client_availability_id": row.client_availability_id,
                "coach_availability_id": row.coach_availability_id,
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
    weekday: Weekday | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    max_time_commitment_seconds: Any = None,
    client_availability_id: int | None = None,
    coach_availability_id: int | None = None,
) -> Availability:
    row = Availability(
        account_id=account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        repeats_weekly=repeats_weekly,
        recurrence_end_dt=recurrence_end_dt,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        max_time_commitment_seconds=max_time_commitment_seconds,
        client_availability_id=client_availability_id,
        coach_availability_id=coach_availability_id,
    )
    db.add(row)
    db.flush()
    return row


def delete_availability_row(db: Session, account_id: int, availability_id: int) -> None:
    row = db.get(Availability, availability_id)
    if row is None or row.account_id != account_id:
        raise HTTPException(404, detail="Availability not found")

    if row.start_dt is not None and row.end_dt is not None:
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
    weekday: Weekday | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    max_time_commitment_seconds: Any = None,
    client_availability_id: int | None = None,
    coach_availability_id: int | None = None,
) -> Availability:
    delete_availability_row(db, account_id, availability_id)
    return create_availability_row(
        db,
        account_id,
        start_dt=start_dt,
        end_dt=end_dt,
        repeats_weekly=repeats_weekly,
        recurrence_end_dt=recurrence_end_dt,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        max_time_commitment_seconds=max_time_commitment_seconds,
        client_availability_id=client_availability_id,
        coach_availability_id=coach_availability_id,
    )


def get_client_availability_id(db: Session, client_id: int) -> int:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, detail="Client not found")
    if client.client_availability_id is None:
        # Auto-create container if missing
        from src.database.client.models import ClientAvailability
        ca = ClientAvailability()
        db.add(ca)
        db.flush()
        client.client_availability_id = ca.id
        db.add(client)
        db.flush()
    return client.client_availability_id  # type: ignore


def get_client_availability_rows(db: Session, client_id: int) -> List[Availability]:
    client = db.get(Client, client_id)
    if client is None or client.client_availability_id is None:
        return []
    return list(
        db.exec(
            select(Availability).where(
                Availability.client_availability_id == client.client_availability_id
            )
        ).all()
    )


def _rows_for_weekday(rows: List[Availability], weekday: Weekday) -> List[Availability]:
    return [r for r in rows if r.weekday == weekday]


def _is_fully_covered(rows: List[Availability], weekday: Weekday, seg_start: time, seg_end: time) -> bool:
    """Check union of rows of this weekday fully covers [seg_start, seg_end]."""
    intervals = sorted(
        ((_time_to_seconds(r.start_time), _time_to_seconds(r.end_time)) for r in _rows_for_weekday(rows, weekday)),
        key=lambda iv: iv[0],
    )
    target_s = _time_to_seconds(seg_start)
    target_e = _time_to_seconds(seg_end)
    cursor = target_s
    for s, e in intervals:
        if s > cursor:
            return False  # gap before this row
        cursor = max(cursor, e)
        if cursor >= target_e:
            return True
    return cursor >= target_e


def validate_blocks_against_availability(
    db: Session,
    client_id: int,
    blocks: List[Tuple[datetime, datetime]],
) -> None:
    """Raise 409 if any block is not fully covered by the client's recurring availability template.

    Booked slots are physically removed via split, so a booked region simply won't appear
    among the rows during validation.
    """
    rows = get_client_availability_rows(db, client_id)
    for start_dt, end_dt in blocks:
        weekday, seg_start, seg_end = _block_to_weekday_segment(start_dt, end_dt)
        if not _is_fully_covered(rows, weekday, seg_start, seg_end):
            raise HTTPException(
                409,
                detail=(
                    f"Block {start_dt.isoformat()} → {end_dt.isoformat()} is not fully covered by "
                    f"your declared availability."
                ),
            )


def block_availability_range(
    db: Session,
    client_id: int,
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    """Carve [start_dt, end_dt) out of the client's recurring Availability rows.

    For each row of the matching weekday that overlaps [seg_start, seg_end):
      - If the booking covers the row entirely → delete the row.
      - Else if booking covers the start → row.start_time = seg_end.
      - Else if booking covers the end → row.end_time = seg_start.
      - Else split: shrink current row to (row.start, seg_start) and insert a new row (seg_end, row.end).

    Caller commits. Validation (full coverage) must have happened beforehand.
    """
    weekday, seg_start, seg_end = _block_to_weekday_segment(start_dt, end_dt)
    seg_s = _time_to_seconds(seg_start)
    seg_e = _time_to_seconds(seg_end)

    rows = get_client_availability_rows(db, client_id)
    ca_id = get_client_availability_id(db, client_id)
    for row in _rows_for_weekday(rows, weekday):
        rs = _time_to_seconds(row.start_time)
        re = _time_to_seconds(row.end_time)
        # No overlap
        if re <= seg_s or rs >= seg_e:
            continue
        if seg_s <= rs and seg_e >= re:
            db.delete(row)
        elif seg_s <= rs < seg_e < re:
            row.start_time = _seconds_to_time(seg_e, tzinfo=row.start_time.tzinfo)
            db.add(row)
        elif rs < seg_s < re <= seg_e:
            row.end_time = _seconds_to_time(seg_s, tzinfo=row.end_time.tzinfo)
            db.add(row)
        else:
            # rs < seg_s and seg_e < re: split
            new_start = _seconds_to_time(seg_e, tzinfo=row.start_time.tzinfo)
            new_end = row.end_time
            row.end_time = _seconds_to_time(seg_s, tzinfo=row.end_time.tzinfo)
            db.add(row)
            db.add(Availability(
                weekday=weekday,
                start_time=new_start,
                end_time=new_end,
                client_availability_id=ca_id,
                max_time_commitment_seconds=row.max_time_commitment_seconds,
            ))
    db.flush()


def unblock_availability_range(
    db: Session,
    client_id: int,
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    """Re-insert availability for [start_dt, end_dt), then merge contiguous same-weekday rows.

    Caller commits.
    """
    weekday, seg_start, seg_end = _block_to_weekday_segment(start_dt, end_dt)
    ca_id = get_client_availability_id(db, client_id)

    db.add(Availability(
        weekday=weekday,
        start_time=seg_start,
        end_time=seg_end,
        client_availability_id=ca_id,
    ))
    db.flush()

    # Merge: pull all rows for this weekday, sort, fold contiguous.
    rows = sorted(
        _rows_for_weekday(get_client_availability_rows(db, client_id), weekday),
        key=lambda r: _time_to_seconds(r.start_time),
    )
    merged: List[Availability] = []
    for r in rows:
        if not merged:
            merged.append(r)
            continue
        prev = merged[-1]
        if _time_to_seconds(prev.end_time) >= _time_to_seconds(r.start_time):
            # Contiguous or overlapping — extend prev, drop r
            if _time_to_seconds(r.end_time) > _time_to_seconds(prev.end_time):
                prev.end_time = r.end_time
                db.add(prev)
            db.delete(r)
        else:
            merged.append(r)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────────
# BACKWARDS-COMPAT SHIMS — still imported by existing endpoints; new code should
# use the explicit functions above.
# ──────────────────────────────────────────────────────────────────────────────
def collect_availability_rows_for_range(
    db: Session,
    client_id: int,
    start_dt: datetime,
    end_dt: datetime,
):
    """Legacy: returns (matched_rows, uncovered_segments) — uncovered is empty if fully covered."""
    rows = get_client_availability_rows(db, client_id)
    weekday, seg_start, seg_end = _block_to_weekday_segment(start_dt, end_dt)
    if _is_fully_covered(rows, weekday, seg_start, seg_end):
        matched = [r for r in _rows_for_weekday(rows, weekday)
                   if _time_to_seconds(r.start_time) < _time_to_seconds(seg_end)
                   and _time_to_seconds(r.end_time) > _time_to_seconds(seg_start)]
        return matched, []
    return [], [(weekday, seg_start, seg_end)]


def set_availability_blocked(db: Session, client_id: int, start_dt: datetime, end_dt: datetime, *, blocked: bool):
    """Legacy shim: route to split/merge. `blocked=True` carves out, `False` re-inserts+merges."""
    if blocked:
        block_availability_range(db, client_id, start_dt, end_dt)
    else:
        unblock_availability_range(db, client_id, start_dt, end_dt)
    return []
