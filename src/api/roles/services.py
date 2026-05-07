from datetime import datetime, time, timedelta, timezone
from typing import Iterable, List, Tuple

from sqlmodel import Session, select

from src.database.account.models import Availability, Weekday
from src.database.client.models import Client


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


def _iter_day_segments(start_dt: datetime, end_dt: datetime) -> Iterable[Tuple[Weekday, time, time]]:
    """Walk [start_dt, end_dt) and yield (weekday, day_start_time, day_end_time) per calendar day."""
    start_dt = _ensure_aware(start_dt)
    end_dt = _ensure_aware(end_dt)
    cursor = start_dt
    while cursor < end_dt:
        day_end = datetime.combine(cursor.date(), time.max, tzinfo=cursor.tzinfo)
        next_midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo)
        segment_end = min(end_dt, next_midnight)

        # Map weekday: Python's Monday=0 .. Sunday=6
        weekday_enum = _WEEKDAY_BY_INDEX[cursor.weekday()]
        yield weekday_enum, cursor.timetz(), segment_end.timetz() if segment_end < next_midnight else time(23, 59, 59, 999999, tzinfo=cursor.tzinfo)

        cursor = next_midnight
        # avoid infinite loop on day_end unused warning
        _ = day_end


def get_client_availabilities(db: Session, client_id: int) -> List[Availability]:
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


def find_overlapping_availabilities(
    rows: List[Availability],
    weekday: Weekday,
    seg_start: time,
    seg_end: time,
) -> List[Availability]:
    """Return rows for the given weekday whose [start_time, end_time) overlaps [seg_start, seg_end)."""
    matches = []
    for row in rows:
        if row.weekday != weekday:
            continue
        # overlap: row.start_time < seg_end AND row.end_time > seg_start
        if _time_lt(row.start_time, seg_end) and _time_gt(row.end_time, seg_start):
            matches.append(row)
    return matches


def _time_lt(a: time, b: time) -> bool:
    return _time_to_seconds(a) < _time_to_seconds(b)


def _time_gt(a: time, b: time) -> bool:
    return _time_to_seconds(a) > _time_to_seconds(b)


def _time_to_seconds(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def collect_availability_rows_for_range(
    db: Session,
    client_id: int,
    start_dt: datetime,
    end_dt: datetime,
) -> Tuple[List[Availability], List[Tuple[Weekday, time, time]]]:
    """Return (matched availability rows, uncovered segments).

    A segment is "uncovered" if no Availability row of that weekday covers any part of it.
    Caller can use this to detect conflicts before booking.
    """
    rows = get_client_availabilities(db, client_id)
    matched: List[Availability] = []
    uncovered: List[Tuple[Weekday, time, time]] = []

    for weekday, seg_start, seg_end in _iter_day_segments(start_dt, end_dt):
        overlaps = find_overlapping_availabilities(rows, weekday, seg_start, seg_end)
        if not overlaps:
            uncovered.append((weekday, seg_start, seg_end))
        else:
            matched.extend(overlaps)

    # de-dup by id
    deduped = {r.id: r for r in matched if r.id is not None}
    return list(deduped.values()), uncovered


def set_availability_blocked(
    db: Session,
    client_id: int,
    start_dt: datetime,
    end_dt: datetime,
    *,
    blocked: bool,
) -> List[Availability]:
    """Toggle is_blocked on all Availability rows that overlap the given range. Caller commits."""
    rows, _ = collect_availability_rows_for_range(db, client_id, start_dt, end_dt)
    for r in rows:
        r.is_blocked = blocked
        db.add(r)
    return rows
