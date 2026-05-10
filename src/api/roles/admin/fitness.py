"""Admin fitness CRUD — full authority over Workouts, WorkoutActivities,
Equipment, and WorkoutPlans. Edit creates a VCS fork (clone + hide old);
Delete soft-hides via `is_hidden` so telemetry & scheduled CWPs still resolve.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from src.api.dependencies import get_admin_account, PaginationParams
from src.database.account.models import Account
from src.database.session import get_session
from src.database.workouts_and_activities.models import (
    Equiptment,
    Workout,
    WorkoutActivity,
    WorkoutEquiptment,
    WorkoutPlan,
    WorkoutPlanActivity,
    WorkoutType,
)

router = APIRouter(prefix="/roles/admin/fitness", tags=["admin", "fitness"])


# ─── enrichment helpers ──────────────────────────────────────────────────────

def _enrich_workout(db: Session, w: Workout) -> dict:
    activities = db.exec(
        select(WorkoutActivity).where(WorkoutActivity.workout_id == w.id)
    ).all()
    equipment_links = db.exec(
        select(WorkoutEquiptment, Equiptment)
        .join(Equiptment, Equiptment.id == WorkoutEquiptment.equiptment_id)
        .where(WorkoutEquiptment.workout_id == w.id)
    ).all()
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "instructions": w.instructions,
        "workout_type": w.workout_type,
        "is_hidden": w.is_hidden,
        "activities": [
            {
                "id": a.id,
                "intensity_measure": a.intensity_measure,
                "intensity_value": a.intensity_value,
                "estimated_calories_per_unit_frequency": float(a.estimated_calories_per_unit_frequency),
                "is_hidden": a.is_hidden,
            }
            for a in activities
        ],
        "equipment": [
            {
                "id": e.id,
                "name": e.name,
                "description": e.description,
                "is_required": link.is_required,
                "is_recommended": link.is_recommended,
            }
            for link, e in equipment_links
        ],
    }


def _enrich_plan(db: Session, plan: WorkoutPlan) -> dict:
    return _enrich_plans(db, [plan])[0]


def _enrich_plans(db: Session, plans: list[WorkoutPlan]) -> list[dict]:
    """Batch variant: 3 queries total regardless of plan count.

    Admin's listing endpoint calls this with up to PaginationParams.limit
    plans; without batching, a 50-plan page with 5 activities each ran 500+
    SELECTs (loop × 2 db.gets per activity).
    """
    if not plans:
        return []

    plan_ids = [p.id for p in plans if p.id is not None]
    if plan_ids:
        wpas = db.exec(
            select(WorkoutPlanActivity).where(
                WorkoutPlanActivity.workout_plan_id.in_(plan_ids)  # type: ignore
            )
        ).all()
    else:
        wpas = []

    activity_ids = {pa.workout_activity_id for pa in wpas if pa.workout_activity_id is not None}
    activities_by_id: dict[int, WorkoutActivity] = {}
    if activity_ids:
        for a in db.exec(
            select(WorkoutActivity).where(WorkoutActivity.id.in_(activity_ids))  # type: ignore
        ).all():
            if a.id is not None:
                activities_by_id[a.id] = a

    workout_ids = {a.workout_id for a in activities_by_id.values() if a.workout_id is not None}
    workouts_by_id: dict[int, Workout] = {}
    if workout_ids:
        for w in db.exec(
            select(Workout).where(Workout.id.in_(workout_ids))  # type: ignore
        ).all():
            if w.id is not None:
                workouts_by_id[w.id] = w

    wpas_by_plan: dict[int, list[WorkoutPlanActivity]] = {}
    for pa in wpas:
        wpas_by_plan.setdefault(pa.workout_plan_id, []).append(pa)

    out: list[dict] = []
    for plan in plans:
        rows = []
        for pa in wpas_by_plan.get(plan.id, []):  # type: ignore[arg-type]
            wa = activities_by_id.get(pa.workout_activity_id)
            wo = workouts_by_id.get(wa.workout_id) if wa else None
            rows.append({
                "id": pa.id,
                "workout_activity_id": pa.workout_activity_id,
                "workout_id": wa.workout_id if wa else None,
                "workout_name": wo.name if wo else None,
                "workout_type": wo.workout_type if wo else None,
                "intensity_measure": wa.intensity_measure if wa else None,
                "intensity_value": wa.intensity_value if wa else None,
                "planned_reps": pa.planned_reps,
                "planned_sets": pa.planned_sets,
                "planned_duration": pa.planned_duration,
                "estimated_calories": float(pa.estimated_calories) if pa.estimated_calories is not None else None,
            })
        out.append({
            "id": plan.id,
            "strata_name": plan.strata_name,
            "is_public": plan.is_public,
            "is_hidden": plan.is_hidden,
            "created_by_account_id": plan.created_by_account_id,
            "activities": rows,
        })
    return out


# ─── reference checks (do telemetry/scheduled CWPs touch this row?) ──────────

def _workout_activity_has_references(db: Session, activity_id: int) -> bool:
    """True iff this activity is referenced by any plan or completed_workout."""
    from src.database.telemetry.models import CompletedWorkout
    if db.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_activity_id == activity_id)
    ).first() is not None:
        return True
    return db.exec(
        select(CompletedWorkout).where(CompletedWorkout.workout_activity_id == activity_id)
    ).first() is not None


def _workout_has_references(db: Session, workout_id: int) -> bool:
    """True iff any of this workout's activities is referenced anywhere."""
    activities = db.exec(
        select(WorkoutActivity).where(WorkoutActivity.workout_id == workout_id)
    ).all()
    for a in activities:
        if a.id is not None and _workout_activity_has_references(db, a.id):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# WORKOUTS
# ═══════════════════════════════════════════════════════════════════════════

class WorkoutEquipmentItem(BaseModel):
    equiptment_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_required: bool = True
    is_recommended: bool = True


class ActivityTierItem(BaseModel):
    intensity_value: int
    estimated_calories_per_unit_frequency: float


class CreateWorkoutInput(BaseModel):
    name: str
    description: str
    instructions: str
    workout_type: str
    intensity_measure: Optional[str] = None
    activity_tiers: list[ActivityTierItem] = []
    equipment: list[WorkoutEquipmentItem] = []


class UpdateWorkoutInput(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    workout_type: Optional[str] = None


@router.get("/workouts")
def list_workouts(
    text: Optional[str] = None,
    workout_type: Optional[WorkoutType] = None,
    include_hidden: bool = True,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Admin sees all workouts including hidden ones (toggleable)."""
    query = select(Workout)
    if not include_hidden:
        query = query.where(Workout.is_hidden == False)  # type: ignore
    if text:
        query = query.where(
            (Workout.name.contains(text)) | (Workout.description.contains(text))  # type: ignore
        )
    if workout_type is not None:
        query = query.where(Workout.workout_type == workout_type)
    rows = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return [_enrich_workout(db, w) for w in rows]


@router.post("/workouts")
def create_workout(
    payload: CreateWorkoutInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    try:
        wt = WorkoutType(payload.workout_type)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid workout_type. Must be one of {[t.value for t in WorkoutType]}")

    workout = Workout(
        name=payload.name,
        description=payload.description,
        instructions=payload.instructions,
        workout_type=wt,
        is_hidden=False,
    )
    db.add(workout)
    db.flush()

    for tier in payload.activity_tiers:
        db.add(WorkoutActivity(
            workout_id=workout.id,  # type: ignore
            intensity_measure=payload.intensity_measure,
            intensity_value=tier.intensity_value,
            estimated_calories_per_unit_frequency=tier.estimated_calories_per_unit_frequency,  # type: ignore
            is_hidden=False,
        ))

    for eq_in in payload.equipment:
        if eq_in.equiptment_id is not None:
            eq = db.get(Equiptment, eq_in.equiptment_id)
            if not eq:
                raise HTTPException(404, detail=f"Equipment {eq_in.equiptment_id} not found")
        elif eq_in.name:
            eq = db.exec(select(Equiptment).where(Equiptment.name == eq_in.name)).first()
            if not eq:
                eq = Equiptment(name=eq_in.name, description=eq_in.description)
                db.add(eq)
                db.flush()
        else:
            raise HTTPException(400, detail="Must provide equiptment_id or name for equipment link")
        db.add(WorkoutEquiptment(
            equiptment_id=eq.id,
            workout_id=workout.id,
            is_required=eq_in.is_required,
            is_recommended=eq_in.is_recommended,
        ))

    db.commit()
    db.refresh(workout)
    return _enrich_workout(db, workout)


def _fork_workout(db: Session, old: Workout) -> Workout:
    """Clone workout + its activities + equipment links into a new row, hide old."""
    new = Workout(
        name=old.name,
        description=old.description,
        instructions=old.instructions,
        workout_type=old.workout_type,
        is_hidden=False,
    )
    db.add(new)
    db.flush()

    for old_a in db.exec(select(WorkoutActivity).where(WorkoutActivity.workout_id == old.id)).all():
        db.add(WorkoutActivity(
            workout_id=new.id,
            intensity_measure=old_a.intensity_measure,
            intensity_value=old_a.intensity_value,
            estimated_calories_per_unit_frequency=old_a.estimated_calories_per_unit_frequency,
            is_hidden=False,
        ))

    for old_link in db.exec(select(WorkoutEquiptment).where(WorkoutEquiptment.workout_id == old.id)).all():
        db.add(WorkoutEquiptment(
            equiptment_id=old_link.equiptment_id,
            workout_id=new.id,
            is_required=old_link.is_required,
            is_recommended=old_link.is_recommended,
        ))

    old.is_hidden = True
    db.add(old)
    return new


@router.patch("/workouts/{workout_id}")
def update_workout(
    workout_id: int,
    payload: UpdateWorkoutInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Edit creates a VCS fork if the workout is referenced by anything (telemetry
    or any plan); otherwise mutates in place. Old version is hidden after fork."""
    workout = db.get(Workout, workout_id)
    if workout is None or workout.is_hidden:
        raise HTTPException(404, detail="Workout not found")

    target = _fork_workout(db, workout) if _workout_has_references(db, workout_id) else workout

    if payload.name is not None:
        target.name = payload.name
    if payload.description is not None:
        target.description = payload.description
    if payload.instructions is not None:
        target.instructions = payload.instructions
    if payload.workout_type is not None:
        try:
            target.workout_type = WorkoutType(payload.workout_type)
        except ValueError:
            raise HTTPException(400, detail="Invalid workout_type")
    db.add(target)
    db.commit()
    db.refresh(target)
    return _enrich_workout(db, target)


@router.delete("/workouts/{workout_id}")
def delete_workout(
    workout_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Soft-delete: sets is_hidden=true. Hides from listings; telemetry &
    scheduled CWPs continue to resolve names because hidden rows still exist."""
    workout = db.get(Workout, workout_id)
    if workout is None:
        raise HTTPException(404, detail="Workout not found")
    workout.is_hidden = True
    db.add(workout)
    # Cascade-hide its activities so they vanish from coach pickers
    for a in db.exec(select(WorkoutActivity).where(WorkoutActivity.workout_id == workout_id)).all():
        a.is_hidden = True
        db.add(a)
    db.commit()
    return {"hidden": workout_id}


@router.post("/workouts/{workout_id}/unhide")
def unhide_workout(
    workout_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    workout = db.get(Workout, workout_id)
    if workout is None:
        raise HTTPException(404, detail="Workout not found")
    workout.is_hidden = False
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return _enrich_workout(db, workout)


# ═══════════════════════════════════════════════════════════════════════════
# WORKOUT ACTIVITIES (intensity tiers)
# ═══════════════════════════════════════════════════════════════════════════

class CreateActivityInput(BaseModel):
    workout_id: int
    intensity_measure: Optional[str] = None
    intensity_value: int
    estimated_calories_per_unit_frequency: float


class UpdateActivityInput(BaseModel):
    intensity_measure: Optional[str] = None
    intensity_value: Optional[int] = None
    estimated_calories_per_unit_frequency: Optional[float] = None


@router.get("/activities")
def list_activities(
    workout_id: Optional[int] = None,
    include_hidden: bool = True,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    query = select(WorkoutActivity)
    if workout_id is not None:
        query = query.where(WorkoutActivity.workout_id == workout_id)
    if not include_hidden:
        query = query.where(WorkoutActivity.is_hidden == False)  # type: ignore
    rows = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    out = []
    for a in rows:
        wo = db.get(Workout, a.workout_id)
        out.append({
            "id": a.id,
            "workout_id": a.workout_id,
            "workout_name": wo.name if wo else None,
            "intensity_measure": a.intensity_measure,
            "intensity_value": a.intensity_value,
            "estimated_calories_per_unit_frequency": float(a.estimated_calories_per_unit_frequency),
            "is_hidden": a.is_hidden,
        })
    return out


@router.post("/activities")
def create_activity(
    payload: CreateActivityInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    if not db.get(Workout, payload.workout_id):
        raise HTTPException(404, detail=f"Workout {payload.workout_id} not found")
    a = WorkoutActivity(
        workout_id=payload.workout_id,
        intensity_measure=payload.intensity_measure,
        intensity_value=payload.intensity_value,
        estimated_calories_per_unit_frequency=payload.estimated_calories_per_unit_frequency,  # type: ignore
        is_hidden=False,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {
        "id": a.id,
        "workout_id": a.workout_id,
        "intensity_measure": a.intensity_measure,
        "intensity_value": a.intensity_value,
        "estimated_calories_per_unit_frequency": float(a.estimated_calories_per_unit_frequency),
        "is_hidden": a.is_hidden,
    }


def _fork_activity(db: Session, old: WorkoutActivity) -> WorkoutActivity:
    new = WorkoutActivity(
        workout_id=old.workout_id,
        intensity_measure=old.intensity_measure,
        intensity_value=old.intensity_value,
        estimated_calories_per_unit_frequency=old.estimated_calories_per_unit_frequency,
        is_hidden=False,
    )
    db.add(new)
    old.is_hidden = True
    db.add(old)
    db.flush()
    return new


@router.patch("/activities/{activity_id}")
def update_activity(
    activity_id: int,
    payload: UpdateActivityInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    a = db.get(WorkoutActivity, activity_id)
    if a is None or a.is_hidden:
        raise HTTPException(404, detail="Activity not found")

    target = _fork_activity(db, a) if _workout_activity_has_references(db, activity_id) else a

    if payload.intensity_measure is not None:
        target.intensity_measure = payload.intensity_measure
    if payload.intensity_value is not None:
        target.intensity_value = payload.intensity_value
    if payload.estimated_calories_per_unit_frequency is not None:
        target.estimated_calories_per_unit_frequency = payload.estimated_calories_per_unit_frequency  # type: ignore
    db.add(target)
    db.commit()
    db.refresh(target)
    return {
        "id": target.id,
        "workout_id": target.workout_id,
        "intensity_measure": target.intensity_measure,
        "intensity_value": target.intensity_value,
        "estimated_calories_per_unit_frequency": float(target.estimated_calories_per_unit_frequency),
        "is_hidden": target.is_hidden,
    }


@router.delete("/activities/{activity_id}")
def delete_activity(
    activity_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    a = db.get(WorkoutActivity, activity_id)
    if a is None:
        raise HTTPException(404, detail="Activity not found")
    a.is_hidden = True
    db.add(a)
    db.commit()
    return {"hidden": activity_id}


@router.post("/activities/{activity_id}/unhide")
def unhide_activity(
    activity_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Restore a previously soft-hidden activity tier. Mirrors the workouts/plans unhide pattern."""
    a = db.get(WorkoutActivity, activity_id)
    if a is None:
        raise HTTPException(404, detail="Activity not found")
    a.is_hidden = False
    db.add(a)
    db.commit()
    db.refresh(a)
    wo = db.get(Workout, a.workout_id)
    return {
        "id": a.id,
        "workout_id": a.workout_id,
        "workout_name": wo.name if wo else None,
        "intensity_measure": a.intensity_measure,
        "intensity_value": a.intensity_value,
        "estimated_calories_per_unit_frequency": float(a.estimated_calories_per_unit_frequency),
        "is_hidden": a.is_hidden,
    }


# ═══════════════════════════════════════════════════════════════════════════
# EQUIPMENT
# ═══════════════════════════════════════════════════════════════════════════

class EquipmentInput(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("/equipment")
def list_equipment(
    text: Optional[str] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    query = select(Equiptment)
    if text:
        query = query.where(Equiptment.name.contains(text))  # type: ignore
    rows = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    out = []
    for eq in rows:
        link_count = len(db.exec(
            select(WorkoutEquiptment).where(WorkoutEquiptment.equiptment_id == eq.id)
        ).all())
        out.append({
            "id": eq.id,
            "name": eq.name,
            "description": eq.description,
            "linked_workout_count": link_count,
        })
    return out


@router.post("/equipment")
def create_equipment(
    payload: EquipmentInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    existing = db.exec(select(Equiptment).where(Equiptment.name == payload.name)).first()
    if existing:
        raise HTTPException(409, detail=f"Equipment '{payload.name}' already exists")
    eq = Equiptment(name=payload.name, description=payload.description)
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return {"id": eq.id, "name": eq.name, "description": eq.description}


@router.patch("/equipment/{equipment_id}")
def update_equipment(
    equipment_id: int,
    payload: EquipmentInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    eq = db.get(Equiptment, equipment_id)
    if eq is None:
        raise HTTPException(404, detail="Equipment not found")
    eq.name = payload.name
    eq.description = payload.description
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return {"id": eq.id, "name": eq.name, "description": eq.description}


@router.delete("/equipment/{equipment_id}")
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Hard-delete: equipment has no telemetry references. Cascades the
    WorkoutEquiptment join rows so the equipment vanishes from workout cards."""
    eq = db.get(Equiptment, equipment_id)
    if eq is None:
        raise HTTPException(404, detail="Equipment not found")
    for link in db.exec(select(WorkoutEquiptment).where(WorkoutEquiptment.equiptment_id == equipment_id)).all():
        db.delete(link)
    db.flush()
    db.delete(eq)
    db.commit()
    return {"deleted": equipment_id}


# ═══════════════════════════════════════════════════════════════════════════
# WORKOUT PLANS — admin override of ownership + telemetry guards
# ═══════════════════════════════════════════════════════════════════════════

class CreatePlanActivityInput(BaseModel):
    workout_activity_id: int
    planned_duration: Optional[int] = None
    planned_reps: Optional[int] = None
    planned_sets: Optional[int] = None


class CreatePlanInput(BaseModel):
    strata_name: str
    is_public: bool = False
    activities: list[CreatePlanActivityInput] = []


class UpdatePlanInput(BaseModel):
    strata_name: Optional[str] = None
    is_public: Optional[bool] = None


@router.get("/plans")
def list_plans(
    text: Optional[str] = None,
    include_hidden: bool = True,
    public_only: bool = False,
    created_by_account_id: Optional[int] = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    query = select(WorkoutPlan)
    if not include_hidden:
        query = query.where(WorkoutPlan.is_hidden == False)  # type: ignore
    if public_only:
        query = query.where(WorkoutPlan.is_public == True)  # type: ignore
    if created_by_account_id is not None:
        query = query.where(WorkoutPlan.created_by_account_id == created_by_account_id)
    if text:
        query = query.where(WorkoutPlan.strata_name.contains(text))  # type: ignore
    rows = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    return _enrich_plans(db, list(rows))


@router.post("/plans")
def create_plan(
    payload: CreatePlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Admin creates a plan — owns it, may publish."""
    plan = WorkoutPlan(
        strata_name=payload.strata_name,
        is_public=payload.is_public,
        is_hidden=False,
        created_by_account_id=acc.id,
    )
    db.add(plan)
    db.flush()

    for ai in payload.activities:
        wa = db.get(WorkoutActivity, ai.workout_activity_id)
        if not wa:
            raise HTTPException(404, detail=f"WorkoutActivity {ai.workout_activity_id} not found")
        freq = ai.planned_duration or ((ai.planned_reps or 0) * (ai.planned_sets or 0))
        est = wa.estimated_calories_per_unit_frequency * freq
        db.add(WorkoutPlanActivity(
            workout_plan_id=plan.id,  # type: ignore
            workout_activity_id=ai.workout_activity_id,
            estimated_calories=est,
            modified_by_account_id=acc.id,  # type: ignore
            planned_duration=ai.planned_duration,
            planned_reps=ai.planned_reps,
            planned_sets=ai.planned_sets,
        ))

    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


@router.patch("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    payload: UpdatePlanInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Admin can edit any plan (cross-owner). PRD v2: in-place mutation, no fork."""
    from src.api.roles.shared.fitness import _fanout_plan_changed

    plan = db.get(WorkoutPlan, plan_id)
    if plan is None or plan.is_hidden:
        raise HTTPException(404, detail="Plan not found")

    old_name = plan.strata_name
    changes = []
    if payload.strata_name is not None and payload.strata_name != plan.strata_name:
        plan.strata_name = payload.strata_name
        changes.append(f"renamed to '{payload.strata_name}'")
    if payload.is_public is not None:
        if payload.is_public and plan.is_forked:
            raise HTTPException(400, detail="Forked plans cannot be published.")
        if payload.is_public != plan.is_public:
            plan.is_public = payload.is_public
            changes.append("published" if payload.is_public else "unpublished")
    db.add(plan)
    if changes and acc.id is not None:
        _fanout_plan_changed(
            db,
            plan=plan,
            editor_account_id=acc.id,
            summary=f"'{old_name}': " + ", ".join(changes) + " (by admin)",
        )
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    """Admin force-delete: always soft-deletes (is_hidden=true) regardless of
    telemetry or scheduled CWPs. Hidden plans still resolve at log time."""
    plan = db.get(WorkoutPlan, plan_id)
    if plan is None:
        raise HTTPException(404, detail="Plan not found")
    plan.is_hidden = True
    db.add(plan)
    db.commit()
    return {"hidden": plan_id}


@router.post("/plans/{plan_id}/unhide")
def unhide_plan(
    plan_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_admin_account),
):
    plan = db.get(WorkoutPlan, plan_id)
    if plan is None:
        raise HTTPException(404, detail="Plan not found")
    plan.is_hidden = False
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)
