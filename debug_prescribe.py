"""
Temporary diagnostic script — do not commit.

Connects to the PRODUCTION database, simulates the availability projection
for bingus (account_id=274, client_id=147) against a range of time windows,
then uses a freshly-minted JWT for Matty T (account_id=1) to hit the live
prescribe endpoint at http://localhost:9090.
"""

import sys
import json
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt as jose_jwt
from sqlmodel import Session, create_engine, select

# ── config ───────────────────────────────────────────────────────────────────
DATABASE_URL = (
    "postgresql://postgres.fktdltfqbutqrercodql:SC8d3JBQ0hkq9oHA"
    "@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
)
JWT_SECRET   = "97g86crybb7865wy89q78gf6vyb7qtvy8bocv7q8o947869qfhy897gfciybqwuoefgy4cq8o6gy"
ALGORITHM    = "HS256"
API_BASE     = "http://localhost:9090"

MATTY_ACCOUNT_ID = 1
BINGUS_ACCOUNT_ID = 274
BINGUS_CLIENT_ID  = 147

# ── helpers ───────────────────────────────────────────────────────────────────

def make_token(account_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=2)
    return jose_jwt.encode({"sub": str(account_id), "exp": expire}, JWT_SECRET, algorithm=ALGORITHM)


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _overlaps(ls, le, rs, re) -> bool:
    return ls < re and rs < le


def _merge(intervals):
    ordered = sorted(intervals, key=lambda x: x[0])
    merged = []
    for s, e in ordered:
        if not merged:
            merged.append((s, e))
        elif s - merged[-1][1] <= timedelta(minutes=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def project_availability(rows, range_start, range_end):
    range_start = _ensure_aware(range_start)
    range_end   = _ensure_aware(range_end)
    intervals = []
    for row in rows:
        s = _ensure_aware(row.start_dt)
        e = _ensure_aware(row.end_dt)
        cutoff = _ensure_aware(row.recurrence_end_dt) if row.recurrence_end_dt else None
        if not row.repeats_weekly:
            if _overlaps(s, e, range_start, range_end):
                intervals.append((max(s, range_start), min(e, range_end)))
            continue
        while e <= range_start:
            s += timedelta(days=7)
            e += timedelta(days=7)
        while s < range_end:
            if cutoff and s >= cutoff:
                break
            if _overlaps(s, e, range_start, range_end):
                intervals.append((max(s, range_start), min(e, range_end)))
            s += timedelta(days=7)
            e += timedelta(days=7)
    return _merge(intervals)


def is_fully_available(rows, start_dt, end_dt) -> bool:
    if not rows:
        return False
    projected = project_availability(rows, start_dt, end_dt)
    if not projected:
        return False
    cursor = _ensure_aware(start_dt)
    target = _ensure_aware(end_dt)
    for iv_s, iv_e in projected:
        if iv_s > cursor:
            return False
        if iv_e > cursor:
            cursor = iv_e
        if cursor >= target:
            return True
    return cursor >= target


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    engine = create_engine(DATABASE_URL, echo=False)

    from src.database.account.models import Availability, BusySlot  # noqa: E402

    with Session(engine) as db:
        avail_rows = list(db.exec(select(Availability).where(Availability.account_id == BINGUS_ACCOUNT_ID)).all())
        busy_slots = list(db.exec(select(BusySlot).where(BusySlot.account_id == BINGUS_ACCOUNT_ID)).all())

    print("=== bingus availability rows ===")
    for r in avail_rows:
        print(f"  id={r.id}  start={r.start_dt}  end={r.end_dt}  weekly={r.repeats_weekly}  cutoff={r.recurrence_end_dt}")

    print(f"\n=== bingus busy slots: {len(busy_slots)} ===")
    for b in busy_slots:
        print(f"  id={b.id}  {b.start_dt} → {b.end_dt}  source={b.source}")

    # ── probe a range of candidate windows ───────────────────────────────────
    print("\n=== probing candidate windows ===")
    base = avail_rows[0].start_dt if avail_rows else None
    if base is None:
        print("No availability rows — nothing to probe.")
        return

    base = _ensure_aware(base)
    # try this week's occurrence and the next 4 weeks
    for week_offset in range(5):
        week_start = base + timedelta(weeks=week_offset)
        week_end   = _ensure_aware(avail_rows[0].end_dt) + timedelta(weeks=week_offset)
        # test a 2-hour window 1 hour into the occurrence
        block_s = week_start + timedelta(hours=1)
        block_e = block_s   + timedelta(hours=2)
        ok = is_fully_available(avail_rows, block_s, block_e)
        symbol = "OK" if ok else "NO"
        print(f"  [{symbol}]  {block_s.isoformat()} to {block_e.isoformat()}")

    # ── find first valid 2-hour window ───────────────────────────────────────
    valid_start = valid_end = None
    for week_offset in range(1, 6):  # skip current week to be safe, use future
        week_s = base + timedelta(weeks=week_offset)
        candidate_s = week_s + timedelta(hours=1)
        candidate_e = candidate_s + timedelta(hours=2)
        if is_fully_available(avail_rows, candidate_s, candidate_e):
            valid_start = candidate_s
            valid_end   = candidate_e
            break

    if valid_start is None:
        print("\nCould not find any valid window — check availability data.")
        return

    print(f"\n=== first valid future window ===")
    print(f"  {valid_start.isoformat()} to {valid_end.isoformat()}")

    # ── pick workout plan 1 ───────────────────────────────────────────────────
    workout_plan_id = 1

    # ── hit the API ───────────────────────────────────────────────────────────
    token = make_token(MATTY_ACCOUNT_ID)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "workout_plan_id": workout_plan_id,
        "client_id": BINGUS_CLIENT_ID,
        "blocks": [
            {
                "start_dt": valid_start.isoformat(),
                "end_dt":   valid_end.isoformat(),
            }
        ],
    }
    print(f"\n=== POST {API_BASE}/roles/coach/prescribe_plan ===")
    print(json.dumps(payload, indent=2))

    resp = httpx.post(f"{API_BASE}/roles/coach/prescribe_plan", json=payload, headers=headers)
    print(f"\nHTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)

    # Clean up the test record we just created
    if resp.status_code == 200:
        cwp_ids = resp.json().get("client_workout_plan_ids", [])
        for cwp_id in cwp_ids:
            del_resp = httpx.delete(
                f"{API_BASE}/roles/coach/client_workout_plan/{cwp_id}",
                headers=headers,
            )
            print(f"Cleaned up cwp {cwp_id}: HTTP {del_resp.status_code}")

    print("\n--- REPRODUCING THE ORIGINAL BUG (no-timezone naive datetimes) ---")
    # This is what the OLD frontend was sending. Backend treats it as UTC.
    # User in EDT (UTC-4) enters 9 AM local, frontend sends "T09:00:00" → backend
    # sees 9AM UTC, but availability starts at 13:00 UTC → 409 NOT COVERED.
    naive_start = valid_start.strftime("%Y-%m-%dT%H:%M:%S")  # strips timezone
    naive_end   = valid_end.strftime("%Y-%m-%dT%H:%M:%S")
    # Shift to 9AM UTC to demonstrate the mismatch (availability starts 13:00 UTC)
    local_9am   = valid_start.replace(hour=9, minute=0, second=0)
    local_9am_naive = local_9am.strftime("%Y-%m-%dT%H:%M:%S")
    local_11pm  = valid_start.replace(hour=23, minute=59, second=0)
    local_11pm_naive = local_11pm.strftime("%Y-%m-%dT%H:%M:%S")

    payload_bug = {
        "workout_plan_id": workout_plan_id,
        "client_id": BINGUS_CLIENT_ID,
        "blocks": [{"start_dt": local_9am_naive, "end_dt": local_11pm_naive}],
    }
    print(f"Sending naive 09:00 UTC (user intended 9AM local = 13:00 UTC):")
    resp_bug = httpx.post(f"{API_BASE}/roles/coach/prescribe_plan", json=payload_bug, headers=headers)
    print(f"HTTP {resp_bug.status_code} (expect 409 — this is the original bug)")
    try:
        d = resp_bug.json()
        print(d.get("detail", {}).get("detail", d))
    except Exception:
        print(resp_bug.text)


if __name__ == "__main__":
    # Add backend src to path
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    main()
