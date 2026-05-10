"""
PRD v2 plans-system migration.

Brings an existing database forward to the copy-to-own model:
  1. Add WorkoutPlan.is_forked, WorkoutPlan.forked_from_plan_id
  2. Add WorkoutPlanActivity.is_hidden
  3. Create plan_library_entry table
  4. Backfill plan_library_entry for every non-hidden plan, attributing
     prescribed plans to the coach who originally prescribed them (inferred
     from ClientCoachRequest chronology + ClientWorkoutPlan rows). Where the
     v1 prescribe_plan flow had clobbered created_by_account_id with the
     client's id, we restore the coach's id.

Idempotent — every ALTER uses IF NOT EXISTS, and the backfill INSERTs use
ON CONFLICT DO NOTHING under the unique (account_id, workout_plan_id, source).

Run once:
    python -m src.scripts.apply_plans_v2_migration
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


SCHEMA_SQL = [
    # workout_plan additions
    """
    ALTER TABLE workout_plan
      ADD COLUMN IF NOT EXISTS is_forked BOOLEAN NOT NULL DEFAULT FALSE;
    """,
    """
    ALTER TABLE workout_plan
      ADD COLUMN IF NOT EXISTS forked_from_plan_id INTEGER NULL
        REFERENCES workout_plan(id) ON DELETE SET NULL;
    """,
    # workout_plan_activity additions
    """
    ALTER TABLE workout_plan_activity
      ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
    """,
    # plan_library_entry table
    """
    CREATE TABLE IF NOT EXISTS plan_library_entry (
      id SERIAL PRIMARY KEY,
      account_id INTEGER NOT NULL
        REFERENCES account(id) ON DELETE CASCADE,
      workout_plan_id INTEGER NOT NULL
        REFERENCES workout_plan(id) ON DELETE CASCADE,
      source TEXT NOT NULL
        CHECK (source IN ('self_authored', 'prescribed', 'public_save')),
      source_coach_account_id INTEGER NULL
        REFERENCES account(id) ON DELETE SET NULL,
      granted_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
      revoked_at TIMESTAMP NULL,
      last_updated TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
      UNIQUE (account_id, workout_plan_id, source)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ple_account
      ON plan_library_entry(account_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ple_plan
      ON plan_library_entry(workout_plan_id);
    """,
]


# Backfill — three passes:
#
# Pass A. Self-authored library entries for every plan whose creator is the
#         current owner. Includes plans that were never prescribed.
#
# Pass B. Identify plans where the v1 prescribe_plan flow transferred
#         ownership to a client. Heuristic: a plan whose `created_by_account_id`
#         resolves to a client account AND has at least one CWP row for that
#         same client. We can't perfectly recover the original coach in all
#         cases — we fall back to looking for any active or historical
#         ClientCoachRequest for the client, taking the most recent accepted
#         one (the most likely prescriber).
#
# Pass C. After ownership rewind, insert a self_authored library entry for
#         the (restored) coach owner, plus a prescribed entry for the client
#         with source_coach_account_id set.
BACKFILL_SQL = [
    # ----- Pass A: self-authored entries for every visible plan -----
    """
    INSERT INTO plan_library_entry (account_id, workout_plan_id, source, granted_at)
    SELECT wp.created_by_account_id, wp.id, 'self_authored', wp.last_updated
    FROM workout_plan wp
    WHERE wp.is_hidden = FALSE
      AND wp.created_by_account_id IS NOT NULL
    ON CONFLICT (account_id, workout_plan_id, source) DO NOTHING;
    """,

    # ----- Pass B+C: rewind v1 ownership transfers, attribute to coach -----
    # Build a temp view: for every non-hidden plan whose owner is the client
    # of any CWP referencing that plan, find the latest accepted coach for
    # that client and rewind ownership to the coach's account.
    """
    WITH transfer_candidates AS (
        SELECT
            wp.id                            AS plan_id,
            owner_acct.client_id             AS client_id,
            client_acct.id                   AS client_account_id
        FROM workout_plan wp
        JOIN account owner_acct
          ON owner_acct.id = wp.created_by_account_id
        JOIN client_workout_plan cwp
          ON cwp.workout_plan_id = wp.id
         AND cwp.client_id = owner_acct.client_id
        JOIN account client_acct
          ON client_acct.id = owner_acct.id
        WHERE wp.is_hidden = FALSE
          AND owner_acct.client_id IS NOT NULL
        GROUP BY wp.id, owner_acct.client_id, client_acct.id
    ),
    coach_inference AS (
        SELECT DISTINCT ON (tc.plan_id)
            tc.plan_id,
            tc.client_id,
            tc.client_account_id,
            ccr.coach_id              AS source_coach_id,
            coach_acct.id             AS source_coach_account_id
        FROM transfer_candidates tc
        JOIN client_coach_request ccr
          ON ccr.client_id = tc.client_id
         AND ccr.is_accepted = TRUE
        JOIN account coach_acct
          ON coach_acct.coach_id = ccr.coach_id
        ORDER BY tc.plan_id, ccr.last_updated DESC NULLS LAST
    )
    -- (a) re-attribute the plan to the coach
    UPDATE workout_plan wp
       SET created_by_account_id = ci.source_coach_account_id
      FROM coach_inference ci
     WHERE wp.id = ci.plan_id;
    """,

    # Now that ownership is correct, ensure the coach has a self_authored entry
    """
    INSERT INTO plan_library_entry (account_id, workout_plan_id, source, granted_at)
    SELECT wp.created_by_account_id, wp.id, 'self_authored', wp.last_updated
    FROM workout_plan wp
    WHERE wp.is_hidden = FALSE
      AND wp.created_by_account_id IS NOT NULL
    ON CONFLICT (account_id, workout_plan_id, source) DO NOTHING;
    """,

    # And the client gets a prescribed entry pointing at that coach.
    """
    INSERT INTO plan_library_entry
        (account_id, workout_plan_id, source, source_coach_account_id, granted_at)
    SELECT
        client_acct.id,
        cwp.workout_plan_id,
        'prescribed',
        coach_acct.id,
        MIN(cwp.start_time)
    FROM client_workout_plan cwp
    JOIN account client_acct
      ON client_acct.client_id = cwp.client_id
    JOIN client_coach_request ccr
      ON ccr.client_id = cwp.client_id
     AND ccr.is_accepted = TRUE
    JOIN account coach_acct
      ON coach_acct.coach_id = ccr.coach_id
    JOIN workout_plan wp
      ON wp.id = cwp.workout_plan_id
     AND wp.is_hidden = FALSE
    -- exclude rows where the coach IS the client (self-assigned), those
    -- already have a self_authored entry from Pass A
    WHERE coach_acct.id <> client_acct.id
    GROUP BY client_acct.id, cwp.workout_plan_id, coach_acct.id
    ON CONFLICT (account_id, workout_plan_id, source) DO NOTHING;
    """,
]


def apply_migration(database_url: str) -> None:
    engine = create_engine(database_url, echo=True)
    with engine.begin() as conn:
        for stmt in SCHEMA_SQL:
            conn.execute(text(stmt))
    print("Schema migration applied.")
    with engine.begin() as conn:
        for stmt in BACKFILL_SQL:
            conn.execute(text(stmt))
    print("Backfill complete: plan_library_entry populated, ownership transfers rewound.")


def main() -> None:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set.")
    apply_migration(database_url)


if __name__ == "__main__":
    main()
