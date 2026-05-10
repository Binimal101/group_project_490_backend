from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from typing import Optional

from src.database.session import get_session
from src.database.account.models import Account, Notification
from src.api.dependencies import get_active_account, PaginationParams
from src.database.workouts_and_activities.models import (
    WorkoutPlan, WorkoutPlanActivity, WorkoutActivity,
    Workout, WorkoutType, WorkoutEquiptment, Equiptment,
    PlanLibraryEntry, PlanLibrarySource,
)
from src.api.roles.shared.domain import CreateWorkoutPlanInput, CreateWorkoutPlanResponse
from src.api.roles.services import notify_coaches_of_client_action

router = APIRouter(prefix="/roles/shared/fitness", tags=["shared", "fitness"])


def _enrich_plan(db: Session, plan: WorkoutPlan) -> dict:
    # PRD v2: skip soft-deleted activities so callers see the live plan shape.
    plan_activities = db.exec(
        select(WorkoutPlanActivity)
        .where(WorkoutPlanActivity.workout_plan_id == plan.id)
        .where(WorkoutPlanActivity.is_hidden == False)  # noqa: E712
    ).all()
    enriched_activities = []
    for pa in plan_activities:
        activity = db.get(WorkoutActivity, pa.workout_activity_id)
        workout = db.get(Workout, activity.workout_id) if activity else None
        enriched_activities.append({
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
        "id": plan.id,
        "strata_name": plan.strata_name,
        "is_public": plan.is_public,
        "is_hidden": plan.is_hidden,
        "is_forked": plan.is_forked,
        "forked_from_plan_id": plan.forked_from_plan_id,
        "created_by_account_id": plan.created_by_account_id,
        "activities": enriched_activities,
    }


# ─── PRD v2 helpers ──────────────────────────────────────────────────────────

def _ensure_library_entry(
    db: Session,
    *,
    account_id: int,
    workout_plan_id: int,
    source: PlanLibrarySource,
    source_coach_account_id: Optional[int] = None,
) -> PlanLibraryEntry:
    """Idempotent insert against the (account_id, plan_id, source) uniq index."""
    existing = db.exec(
        select(PlanLibraryEntry)
        .where(PlanLibraryEntry.account_id == account_id)
        .where(PlanLibraryEntry.workout_plan_id == workout_plan_id)
        .where(PlanLibraryEntry.source == source)
    ).first()
    if existing is not None:
        # If we're upserting a prescription, refresh the coach attribution and
        # clear any prior revoked_at — re-prescribing is a re-grant.
        if source == PlanLibrarySource.PRESCRIBED:
            if source_coach_account_id is not None:
                existing.source_coach_account_id = source_coach_account_id
            existing.revoked_at = None
            db.add(existing)
        return existing
    entry = PlanLibraryEntry(
        account_id=account_id,
        workout_plan_id=workout_plan_id,
        source=source,
        source_coach_account_id=source_coach_account_id,
    )
    db.add(entry)
    db.flush()
    return entry


def _fanout_plan_changed(
    db: Session,
    *,
    plan: WorkoutPlan,
    editor_account_id: int,
    summary: str,
    category: str = "plan_changed",
) -> None:
    """Notify every account with this plan in their library, except the editor.

    PRD v2 fires on rename / publish toggle / activity add/remove / archive /
    delete. Recipients are not gated on relationship — a coach editing a script
    that 7 clients have prescribed produces 7 notifications.
    """
    rows = db.exec(
        select(PlanLibraryEntry)
        .where(PlanLibraryEntry.workout_plan_id == plan.id)
    ).all()
    seen: set[int] = set()
    for entry in rows:
        if entry.account_id == editor_account_id:
            continue
        if entry.account_id in seen:
            continue
        seen.add(entry.account_id)
        db.add(Notification(
            account_id=entry.account_id,
            fav_category=category,
            message=f"'{plan.strata_name}' was updated",
            details=summary,
        ))


def _plan_has_telemetry(db: Session, plan_id: int) -> bool:
    """Return True if any completed_workout entry references an activity in this plan."""
    from src.database.telemetry.models import CompletedWorkout
    activity_ids = [
        pa.id for pa in db.exec(
            select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
        ).all()
        if pa.id is not None
    ]
    if not activity_ids:
        return False
    hit = db.exec(
        select(CompletedWorkout).where(CompletedWorkout.workout_plan_activity_id.in_(activity_ids))  # type: ignore
    ).first()
    return hit is not None


# PRD v2: _fork_plan is removed. Edits are in-place; explicit copy lives in
# /plan/{id}/copy below.


@router.post("/plan", response_model=CreateWorkoutPlanResponse)
def create_workout_plan(
    payload: CreateWorkoutPlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    is_coach = acc.coach_id is not None
    is_public = payload.is_public and is_coach

    plan = WorkoutPlan(
        strata_name=payload.strata_name,
        is_public=is_public,
        is_hidden=False,
        created_by_account_id=acc.id,
    )
    db.add(plan)
    db.flush()

    for act_input in payload.activities:
        activity = db.get(WorkoutActivity, act_input.workout_activity_id)
        if not activity:
            raise HTTPException(status_code=404, detail=f"WorkoutActivity {act_input.workout_activity_id} not found")

        frequency = act_input.planned_duration or (act_input.planned_reps * act_input.planned_sets) or 0  # type: ignore
        estimated_calories = activity.estimated_calories_per_unit_frequency * frequency

        db.add(WorkoutPlanActivity(
            workout_plan_id=plan.id,  # type: ignore
            workout_activity_id=act_input.workout_activity_id,
            estimated_calories=estimated_calories,
            modified_by_account_id=acc.id,  # type: ignore
            planned_duration=act_input.planned_duration,
            planned_reps=act_input.planned_reps,
            planned_sets=act_input.planned_sets,
        ))

    # PRD v2: every owner gets a self_authored library entry on create.
    # This is what "My Plans" / "Previous Scripts" listings join through.
    if acc.id is not None and plan.id is not None:
        _ensure_library_entry(
            db,
            account_id=acc.id,
            workout_plan_id=plan.id,
            source=PlanLibrarySource.SELF_AUTHORED,
        )

    db.commit()
    return CreateWorkoutPlanResponse(workout_plan_id=plan.id)  # type: ignore


@router.get("/query/activity")
def query_workout_activity(
    workout_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(WorkoutActivity).where(
        WorkoutActivity.workout_id == workout_id,
        WorkoutActivity.is_hidden == False,  # type: ignore
    )
    activities = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return activities


@router.get("/query/workout")
def query_workout(
    text: Optional[str] = None,
    workout_type: Optional[WorkoutType] = None,
    equiptment_id: Optional[int] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(Workout).where(Workout.is_hidden == False)  # type: ignore
    if equiptment_id is not None:
        query = query.join(WorkoutEquiptment).where(WorkoutEquiptment.equiptment_id == equiptment_id)
    if text:
        query = query.where(
            (Workout.name.contains(text)) |
            (Workout.description.contains(text))
        )
    if workout_type:
        query = query.where(Workout.workout_type == workout_type)

    workouts = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return workouts


@router.get("/query/supported_equiptment")
def query_supported_equiptment(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account)
):
    query = select(Equiptment)
    return db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()


@router.get("/query/workout_plan")
def query_workout_plans(
    text: Optional[str] = None,
    public_only: bool = False,
    # PRD v2: replaced mine_only with library_source. Accepts the deprecated
    # mine_only=true as a synonym for library_source=self_authored so the
    # frontend can roll out gradually.
    library_source: Optional[str] = None,
    mine_only: bool = False,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List visible (non-hidden) workout plans.

    public_only=true     → Browse Plans (every public plan).
    library_source=self_authored → "All Mine" (client) / "Previous Scripts" (coach).
    library_source=prescribed    → "From Coach" (client only).
    library_source=public_save   → saved-but-not-copied plans.
    library_source omitted + library scope → all of caller's library entries.
    """
    if mine_only and not library_source:
        library_source = PlanLibrarySource.SELF_AUTHORED.value

    query = select(WorkoutPlan).where(WorkoutPlan.is_hidden == False)  # type: ignore

    if library_source is not None:
        # Validate the source against the enum.
        try:
            src_enum = PlanLibrarySource(library_source)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown library_source: {library_source}")
        query = (
            query.join(PlanLibraryEntry, PlanLibraryEntry.workout_plan_id == WorkoutPlan.id)
                 .where(PlanLibraryEntry.account_id == acc.id)
                 .where(PlanLibraryEntry.source == src_enum)
        )

    if text:
        query = query.where(WorkoutPlan.strata_name.contains(text))  # type: ignore
    if public_only:
        query = query.where(WorkoutPlan.is_public == True)  # type: ignore

    plans = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return [_enrich_plan(db, plan) for plan in plans]


# ── Plan modification endpoints (owner only, VCS-backed) ─────────────────────


class RenamePlanInput(BaseModel):
    strata_name: Optional[str] = None
    is_public: Optional[bool] = None


class AddPlanActivityInput(BaseModel):
    workout_activity_id: int
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None


def _get_owned_plan(plan_id: int, db: Session, acc: Account) -> WorkoutPlan:
    plan = db.get(WorkoutPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    if plan.created_by_account_id != acc.id:
        raise HTTPException(status_code=403, detail="You do not own this plan")
    if plan.is_hidden:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    return plan


@router.patch("/plan/{plan_id}")
def update_workout_plan(
    plan_id: int,
    payload: RenamePlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: in-place rename / publish toggle. No fork.

    Forked plans cannot be made public (`is_public=True` 400's if `is_forked`).
    Notification fanout to every library holder ≠ editor.
    """
    plan = _get_owned_plan(plan_id, db, acc)
    old_name = plan.strata_name

    changes = []
    if payload.strata_name is not None:
        new_name = payload.strata_name.strip()
        if new_name and new_name != plan.strata_name:
            plan.strata_name = new_name
            changes.append(f"renamed to '{new_name}'")

    if payload.is_public is not None:
        if payload.is_public and plan.is_forked:
            raise HTTPException(
                status_code=400,
                detail="Forked plans cannot be published.",
            )
        if payload.is_public != plan.is_public:
            plan.is_public = payload.is_public
            changes.append("published" if payload.is_public else "unpublished")

    db.add(plan)

    if changes and acc.id is not None:
        _fanout_plan_changed(
            db,
            plan=plan,
            editor_account_id=acc.id,
            summary=f"'{old_name}': " + ", ".join(changes),
        )

    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


@router.delete("/plan/{plan_id}")
def delete_workout_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: hard-delete if no telemetry exists, else archive (is_hidden=True)
    so caloric history stays attributable. Library entries cascade on hard delete.
    """
    plan = _get_owned_plan(plan_id, db, acc)
    plan_name = plan.strata_name

    if _plan_has_telemetry(db, plan_id):
        # Archive: mark plan + every wpa hidden, leave library entries intact
        # so existing CompletedWorkout rows still resolve through the chain.
        plan.is_hidden = True
        db.add(plan)
        for pa in db.exec(
            select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
        ).all():
            pa.is_hidden = True
            db.add(pa)
        if acc.id is not None:
            _fanout_plan_changed(
                db,
                plan=plan,
                editor_account_id=acc.id,
                summary=f"'{plan_name}' was archived",
                category="plan_archived",
            )
        db.commit()
        return {"archived": plan_id}

    # No telemetry — hard delete. Library entries cascade via the FK.
    activities = db.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == plan_id)
    ).all()
    for a in activities:
        db.delete(a)
    # Notify holders BEFORE we delete the plan so plan.strata_name is still
    # available; library-entry FK has ON DELETE CASCADE so the notifications
    # can outlive the plan row.
    if acc.id is not None:
        _fanout_plan_changed(
            db,
            plan=plan,
            editor_account_id=acc.id,
            summary=f"'{plan_name}' was deleted",
            category="plan_deleted",
        )
    db.flush()
    db.delete(plan)
    db.commit()
    return {"deleted": plan_id}


@router.post("/plan/{plan_id}/activity")
def add_plan_activity(
    plan_id: int,
    payload: AddPlanActivityInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: append a WorkoutPlanActivity in place. No fork."""
    plan = _get_owned_plan(plan_id, db, acc)
    activity = db.get(WorkoutActivity, payload.workout_activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail=f"WorkoutActivity {payload.workout_activity_id} not found")

    frequency = payload.planned_duration or (
        (payload.planned_reps or 0) * (payload.planned_sets or 0)
    )
    estimated_calories = activity.estimated_calories_per_unit_frequency * frequency

    new_pa = WorkoutPlanActivity(
        workout_plan_id=plan.id,
        workout_activity_id=payload.workout_activity_id,
        estimated_calories=estimated_calories,
        modified_by_account_id=acc.id,
        planned_duration=payload.planned_duration,
        planned_reps=payload.planned_reps,
        planned_sets=payload.planned_sets,
    )
    db.add(new_pa)

    workout = db.get(Workout, activity.workout_id) if activity else None
    workout_name = workout.name if workout else f"activity #{payload.workout_activity_id}"
    if acc.id is not None:
        _fanout_plan_changed(
            db,
            plan=plan,
            editor_account_id=acc.id,
            summary=f"added '{workout_name}' to '{plan.strata_name}'",
        )

    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


@router.delete("/plan/{plan_id}/activity/{activity_id}")
def remove_plan_activity(
    plan_id: int,
    activity_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: in-place remove. Hard-delete if the wpa has no telemetry,
    else soft-delete (is_hidden=True) to preserve caloric attribution.
    """
    plan = _get_owned_plan(plan_id, db, acc)
    pa = db.get(WorkoutPlanActivity, activity_id)
    if pa is None or pa.workout_plan_id != plan_id or pa.is_hidden:
        raise HTTPException(status_code=404, detail="Activity not found in this plan")

    removed_activity = db.get(WorkoutActivity, pa.workout_activity_id)
    removed_workout = db.get(Workout, removed_activity.workout_id) if removed_activity else None
    removed_name = removed_workout.name if removed_workout else f"activity #{pa.workout_activity_id}"

    # Activity-level telemetry check.
    from src.database.telemetry.models import CompletedWorkout
    has_logs = db.exec(
        select(CompletedWorkout).where(CompletedWorkout.workout_plan_activity_id == activity_id)
    ).first() is not None

    if has_logs:
        pa.is_hidden = True
        db.add(pa)
    else:
        db.delete(pa)

    if acc.id is not None:
        _fanout_plan_changed(
            db,
            plan=plan,
            editor_account_id=acc.id,
            summary=f"removed '{removed_name}' from '{plan.strata_name}'",
        )

    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


# ─── PRD v2 NEW ENDPOINTS: save + copy ───────────────────────────────────────

def _plan_is_reachable(db: Session, plan: WorkoutPlan, account_id: int) -> bool:
    """A plan is reachable if it's public OR already in the caller's library."""
    if plan.is_public:
        return True
    existing = db.exec(
        select(PlanLibraryEntry)
        .where(PlanLibraryEntry.workout_plan_id == plan.id)
        .where(PlanLibraryEntry.account_id == account_id)
    ).first()
    return existing is not None


@router.post("/plan/{plan_id}/save")
def save_workout_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: client-only. Adds a public plan to the caller's library
    without creating a copy. Idempotent. Coaches are forbidden so they can't
    pull marketplace plans into their Previous Scripts.
    """
    if acc.coach_id is not None and acc.client_id is None:
        raise HTTPException(status_code=403, detail="Coaches cannot save plans.")
    if acc.id is None:
        raise HTTPException(status_code=404, detail="Account not found")
    plan = db.get(WorkoutPlan, plan_id)
    if plan is None or plan.is_hidden:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    if not plan.is_public and plan.created_by_account_id != acc.id:
        # Allow saving plans that are public or already in the user's library.
        if not _plan_is_reachable(db, plan, acc.id):
            raise HTTPException(status_code=403, detail="Cannot save a private plan.")

    _ensure_library_entry(
        db,
        account_id=acc.id,
        workout_plan_id=plan.id,
        source=PlanLibrarySource.PUBLIC_SAVE,
    )
    db.commit()
    return _enrich_plan(db, plan)


@router.post("/plan/{plan_id}/copy")
def copy_workout_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """PRD v2: client-only. Forks a public or library plan into a brand-new
    client-owned WorkoutPlan with `is_forked=True`. Forked plans cannot be
    published and cannot be prescribed.

    Coaches are forbidden — prevents pulling a public plan, copying it, then
    republishing under the coach's name.
    """
    if acc.coach_id is not None and acc.client_id is None:
        raise HTTPException(status_code=403, detail="Coaches cannot copy plans.")
    if acc.id is None:
        raise HTTPException(status_code=404, detail="Account not found")
    src = db.get(WorkoutPlan, plan_id)
    if src is None or src.is_hidden:
        raise HTTPException(status_code=404, detail="Workout plan not found")
    if not _plan_is_reachable(db, src, acc.id):
        raise HTTPException(status_code=403, detail="Cannot copy a private plan you don't have access to.")

    new_plan = WorkoutPlan(
        strata_name=src.strata_name,
        is_public=False,        # forks can never be public
        is_hidden=False,
        is_forked=True,
        forked_from_plan_id=src.id,
        created_by_account_id=acc.id,
    )
    db.add(new_plan)
    db.flush()

    # Clone every visible activity row (skip soft-deleted ones).
    for old_pa in db.exec(
        select(WorkoutPlanActivity)
        .where(WorkoutPlanActivity.workout_plan_id == src.id)
        .where(WorkoutPlanActivity.is_hidden == False)  # noqa: E712
    ).all():
        db.add(WorkoutPlanActivity(
            workout_plan_id=new_plan.id,
            workout_activity_id=old_pa.workout_activity_id,
            estimated_calories=old_pa.estimated_calories,
            modified_by_account_id=acc.id,
            planned_duration=old_pa.planned_duration,
            planned_reps=old_pa.planned_reps,
            planned_sets=old_pa.planned_sets,
        ))

    _ensure_library_entry(
        db,
        account_id=acc.id,
        workout_plan_id=new_plan.id,
        source=PlanLibrarySource.SELF_AUTHORED,
    )

    db.commit()
    db.refresh(new_plan)
    return _enrich_plan(db, new_plan)
