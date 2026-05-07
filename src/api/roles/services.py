from datetime import datetime, time, timedelta, timezone
from typing import List, Tuple

from fastapi import HTTPException
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
