"""Meals API — coach + client meal CRUD and prescription routes.

URL layout:
  GET    /api/meals/library            ← all meals visible to caller (own or prescribed-to)
  POST   /api/meals                    ← create a meal (coach or client)
  GET    /api/meals/{meal_id}          ← meal detail (must own or be prescribed it)
  DELETE /api/meals/{meal_id}          ← delete a meal you own
  POST   /api/meals/prescribe          ← coach prescribes a meal to a client
  GET    /api/meals/prescribed/mine    ← client lists meals their coach prescribed
  GET    /api/meals/prescribed/by_client/{client_id}  ← coach lists meals they prescribed to a client
  DELETE /api/meals/prescribed/{prescription_id}      ← coach unassigns

Calorie/macro totals are computed fresh from food.calories_per_100g * grams / 100
on every read so a meal updates if upstream USDA data is recached.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from sqlalchemy import delete

from src.api.dependencies import get_active_account
from src.database.session import get_session
from src.database.account.models import Account
from src.database.coach_client_relationship.models import (
    ClientCoachRequest,
    ClientCoachRelationship,
)
from src.database.meal.models import (
    Meal,
    MealFood,
    MealIngredient,
    Food,
    ClientPrescribedMeal,
)
from src.api.meals.domain import (
    CreateMealRequest,
    MealDetailResponse,
    MealFoodLine,
    MealSummary,
    MealTotals,
    PrescribeMealRequest,
    PrescribedMealItem,
)

router = APIRouter(prefix="/api/meals", tags=["meals"])


# ─── helpers ────────────────────────────────────────────────────────────────


def _coach_has_active_relationship(db: Session, coach_id: int, client_id: int) -> bool:
    """Stricter than the read-side authorize helper: only returns True for
    coaches with an active (accepted + relationship row exists) relationship.
    Used for write operations like prescribing meals — a coach with only a
    pending request shouldn't be able to push meal plans onto a client who
    hasn't accepted them yet.

    Note: ClientCoachRelationship doesn't have an is_active flag anymore.
    The presence of the row itself signals an active pairing — termination
    deletes the row rather than flipping a flag."""
    accepted = db.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_id,
            ClientCoachRequest.coach_id == coach_id,
            ClientCoachRequest.is_accepted == True,  # noqa: E712
        )
    ).first()
    if not accepted:
        return False
    rel = db.exec(
        select(ClientCoachRelationship).where(
            ClientCoachRelationship.request_id == accepted.id,
        )
    ).first()
    return rel is not None


def _coach_authorized_for_client(db: Session, coach_id: int, client_id: int) -> bool:
    """Read-side authorization: True iff the coach has a pending request or
    active relationship. Lets coaches view client info while a request is
    being decided, but write operations should use _coach_has_active_relationship."""
    pending = db.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_id,
            ClientCoachRequest.coach_id == coach_id,
            ClientCoachRequest.is_accepted.is_(None),
        )
    ).first()
    if pending:
        return True
    return _coach_has_active_relationship(db, coach_id, client_id)


def _meal_food_lines(db: Session, meal_id: int) -> List[MealFoodLine]:
    """Build a meal's ingredient list from `meal_food` (new path) and fall
    back to `meal_ingredient` (legacy seed data) when there are no
    meal_food rows. We don't try to merge both — legacy meals stay legacy.

    Macro fields on legacy ingredients are 0 except for calories, since the
    seeded `meal_ingredient` schema only stores calories at the row level.
    Coach-built meals have full macro breakouts because they go through
    `meal_food` joined to the cached `food` row."""
    rows = db.exec(
        select(MealFood, Food)
        .where(MealFood.meal_id == meal_id)
        .where(MealFood.food_id == Food.id)
    ).all()
    if rows:
        return [
            MealFoodLine(
                food_id=mf.food_id,
                food_name=f.name,
                grams=mf.grams,
                calories=round(f.calories_per_100g * mf.grams / 100.0, 1),
                protein_g=round(f.protein_g_per_100g * mf.grams / 100.0, 1),
                carbs_g=round(f.carbs_g_per_100g * mf.grams / 100.0, 1),
                fat_g=round(f.fat_g_per_100g * mf.grams / 100.0, 1),
            )
            for mf, f in rows
        ]

    # Legacy fallback — `meal_ingredient` rows have name + calories but no
    # macro breakout. Surface them as a single-line per ingredient with
    # placeholder macro zeros so the UI can still render and total kcal
    # is correct.
    legacy = db.exec(
        select(MealIngredient).where(MealIngredient.meal_id == meal_id)
    ).all()
    return [
        MealFoodLine(
            food_id=0,  # 0 = legacy/synthetic; client UI treats as read-only
            food_name=ing.ingredient_name,
            grams=0.0,
            calories=float(ing.calories or 0),
            protein_g=0.0,
            carbs_g=0.0,
            fat_g=0.0,
        )
        for ing in legacy
    ]


def _meal_totals(lines: List[MealFoodLine]) -> MealTotals:
    return MealTotals(
        calories=round(sum(l.calories for l in lines), 1),
        protein_g=round(sum(l.protein_g for l in lines), 1),
        carbs_g=round(sum(l.carbs_g for l in lines), 1),
        fat_g=round(sum(l.fat_g for l in lines), 1),
    )


def _serialize_meal_detail(db: Session, meal: Meal) -> MealDetailResponse:
    lines = _meal_food_lines(db, meal.id)
    creator = db.get(Account, meal.created_by_account_id)
    return MealDetailResponse(
        id=meal.id,
        meal_name=meal.meal_name,
        created_by_account_id=meal.created_by_account_id,
        created_by_name=creator.name if creator else None,
        foods=lines,
        totals=_meal_totals(lines),
    )


def _serialize_meal_summary(db: Session, meal: Meal) -> MealSummary:
    lines = _meal_food_lines(db, meal.id)
    creator = db.get(Account, meal.created_by_account_id)
    return MealSummary(
        id=meal.id,
        meal_name=meal.meal_name,
        created_by_account_id=meal.created_by_account_id,
        created_by_name=creator.name if creator else None,
        totals=_meal_totals(lines),
    )


def _user_can_view_meal(db: Session, meal: Meal, acc: Account) -> bool:
    """A user can view a meal if:
      - they created it, or
      - they're a client and the meal is prescribed to them, or
      - they're a coach and the meal is prescribed by them.
    Admins can view anything (handled by route guard, not here)."""
    if meal.created_by_account_id == acc.id:
        return True
    if acc.client_id is not None:
        prescribed = db.exec(
            select(ClientPrescribedMeal).where(
                ClientPrescribedMeal.meal_id == meal.id,
                ClientPrescribedMeal.client_id == acc.client_id,
            )
        ).first()
        if prescribed:
            return True
    if acc.coach_id is not None:
        prescribed_by_coach = db.exec(
            select(ClientPrescribedMeal).where(
                ClientPrescribedMeal.meal_id == meal.id,
                ClientPrescribedMeal.prescribed_by_account_id == acc.id,
            )
        ).first()
        if prescribed_by_coach:
            return True
    return False


# ─── meal CRUD ──────────────────────────────────────────────────────────────


@router.post("", response_model=MealDetailResponse)
def create_meal(
    payload: CreateMealRequest,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Create a meal. Used by both coaches (building meals to prescribe) and
    clients (logging custom meals). Same shape, same route — the
    `created_by_account_id` is what distinguishes them."""
    # Verify every food_id exists in our cache before writing the meal,
    # so we don't end up with partial meals on a bad request.
    food_ids = [f.food_id for f in payload.foods]
    found = db.exec(select(Food.id).where(Food.id.in_(food_ids))).all()
    found_ids = {row for row in found}
    missing = set(food_ids) - found_ids
    if missing:
        raise HTTPException(
            400,
            detail=f"Unknown food_id(s): {sorted(missing)}. "
                   f"Call /api/foods/{{fdc_id}} first to cache them.",
        )

    meal = Meal(
        created_by_account_id=acc.id,
        meal_name=payload.meal_name.strip(),
    )
    db.add(meal)
    db.flush()  # need meal.id

    for f in payload.foods:
        db.add(MealFood(meal_id=meal.id, food_id=f.food_id, grams=f.grams))
    db.commit()
    db.refresh(meal)

    return _serialize_meal_detail(db, meal)


@router.get("/library", response_model=List[MealSummary])
def list_meal_library(
    skip: int = 0,
    limit: int = 50,
    mine_only: bool = False,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List meals visible to the caller.
    - Coaches see meals they've created (and seeded ones if not `mine_only`).
    - Clients see meals they've created plus meals prescribed to them.
    Ordered newest-first."""
    visible_meal_ids: set[int] = set()

    own = db.exec(
        select(Meal.id).where(Meal.created_by_account_id == acc.id)
    ).all()
    visible_meal_ids.update(own)

    if not mine_only:
        if acc.client_id is not None:
            prescribed = db.exec(
                select(ClientPrescribedMeal.meal_id)
                .where(ClientPrescribedMeal.client_id == acc.client_id)
            ).all()
            visible_meal_ids.update(prescribed)
        if acc.coach_id is not None:
            # coaches also see seeded library meals (created_by != them but
            # still useful as templates). Treat any meal whose creator is an
            # admin or seeded account as fair game.
            seeded = db.exec(
                select(Meal.id)
                .join(Account, Account.id == Meal.created_by_account_id)
                .where(Account.admin_id.isnot(None))
            ).all()
            visible_meal_ids.update(seeded)

    if not visible_meal_ids:
        return []

    meals = db.exec(
        select(Meal)
        .where(Meal.id.in_(visible_meal_ids))
        .order_by(Meal.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()

    return [_serialize_meal_summary(db, m) for m in meals]


@router.get("/{meal_id}", response_model=MealDetailResponse)
def get_meal(
    meal_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    meal = db.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(404, "Meal not found.")
    if not _user_can_view_meal(db, meal, acc):
        raise HTTPException(403, "Not authorized to view this meal.")
    return _serialize_meal_detail(db, meal)


@router.delete("/{meal_id}")
def delete_meal(
    meal_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Delete a meal you created. Cascades to meal_food (FK ON DELETE CASCADE)
    and any client_prescribed_meal rows referencing it."""
    meal = db.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(404, "Meal not found.")
    if meal.created_by_account_id != acc.id:
        raise HTTPException(403, "Only the creator can delete this meal.")

    # client_prescribed_meal has no ON DELETE on meal_id → clear it manually.
    db.exec(delete(ClientPrescribedMeal).where(ClientPrescribedMeal.meal_id == meal_id))
    db.delete(meal)
    db.commit()
    return {"success": True, "message": "Meal deleted."}


# ─── prescribe ──────────────────────────────────────────────────────────────


@router.post("/prescribe/{client_id}", response_model=PrescribedMealItem)
def prescribe_meal(
    client_id: int,
    payload: PrescribeMealRequest,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Coach-only: assign a meal to one of their clients. Same meal+date+kind
    combo can be prescribed multiple times (each call creates a new row),
    but the typical flow is one prescription per (date, kind) slot.
    `scheduled_date` and `meal_kind` are optional — leave both null for a
    standing recipe."""
    if acc.coach_id is None:
        raise HTTPException(403, "Only coaches can prescribe meals.")
    if not _coach_has_active_relationship(db, acc.coach_id, client_id):
        raise HTTPException(
            403,
            "You can only prescribe meals to clients you currently coach. "
            "Pending or terminated relationships don't qualify.",
        )

    meal = db.get(Meal, payload.meal_id)
    if meal is None:
        raise HTTPException(404, "Meal not found.")

    # If the coach is filling a specific (date, kind) slot, replace any
    # existing prescription for that same slot to keep the planner clean.
    # Without this, repeated drag-and-drops would stack up duplicates.
    if payload.scheduled_date is not None and payload.meal_kind is not None:
        existing = db.exec(
            select(ClientPrescribedMeal).where(
                ClientPrescribedMeal.client_id == client_id,
                ClientPrescribedMeal.scheduled_date == payload.scheduled_date,
                ClientPrescribedMeal.meal_kind == payload.meal_kind,
            )
        ).all()
        for old in existing:
            db.delete(old)

    row = ClientPrescribedMeal(
        meal_id=meal.id,
        client_id=client_id,
        prescribed_by_account_id=acc.id,
        scheduled_date=payload.scheduled_date,
        meal_kind=payload.meal_kind,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return _build_prescribed_item(db, row)


@router.get("/prescribed/mine", response_model=List[PrescribedMealItem])
def list_my_prescribed_meals(
    on_date: Optional[str] = Query(None, description="Filter to a single date (YYYY-MM-DD)"),
    include_standing: bool = Query(True, description="Include standing recipes (scheduled_date IS NULL)"),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Client-only: list meals their coach(es) have prescribed to them.
    With `on_date`, returns just that day's plan plus (by default) any
    standing recipes — used by the client dashboard's "Today" view.
    Without `on_date`, returns everything ever prescribed."""
    if acc.client_id is None:
        raise HTTPException(403, "Only clients have prescribed meals.")
    stmt = select(ClientPrescribedMeal).where(
        ClientPrescribedMeal.client_id == acc.client_id
    )
    if on_date:
        try:
            parsed = datetime.strptime(on_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "on_date must be YYYY-MM-DD")
        if include_standing:
            stmt = stmt.where(
                (ClientPrescribedMeal.scheduled_date == parsed)
                | (ClientPrescribedMeal.scheduled_date.is_(None))
            )
        else:
            stmt = stmt.where(ClientPrescribedMeal.scheduled_date == parsed)
    rows = db.exec(stmt.order_by(ClientPrescribedMeal.id.desc())).all()
    return [_build_prescribed_item(db, r) for r in rows]


@router.get("/prescribed/by_client/{client_id}", response_model=List[PrescribedMealItem])
def list_meals_prescribed_to_client(
    client_id: int,
    week_start: Optional[str] = Query(None, description="Monday of the week to view (YYYY-MM-DD)"),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Coach-only: meals this coach has prescribed to a specific client.
    With `week_start`, returns just that week's plan (Mon–Sun) — used by
    the weekly planner grid on the coach UI. Without it, returns all
    historical prescriptions."""
    if acc.coach_id is None:
        raise HTTPException(403, "Only coaches can list prescriptions.")
    if not _coach_has_active_relationship(db, acc.coach_id, client_id):
        raise HTTPException(
            403,
            "You can only view meal plans for clients you currently coach.",
        )

    stmt = select(ClientPrescribedMeal).where(
        ClientPrescribedMeal.client_id == client_id,
        ClientPrescribedMeal.prescribed_by_account_id == acc.id,
    )
    if week_start:
        try:
            start = datetime.strptime(week_start, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "week_start must be YYYY-MM-DD")
        from datetime import timedelta as _td
        end = start + _td(days=6)
        stmt = stmt.where(
            ClientPrescribedMeal.scheduled_date >= start,
            ClientPrescribedMeal.scheduled_date <= end,
        )
    rows = db.exec(stmt.order_by(ClientPrescribedMeal.id.desc())).all()
    return [_build_prescribed_item(db, r) for r in rows]


@router.delete("/prescribed/{prescription_id}")
def unprescribe_meal(
    prescription_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Coach-only: remove a previously-assigned meal. The coach must be the
    one who created the prescription."""
    row = db.get(ClientPrescribedMeal, prescription_id)
    if row is None:
        raise HTTPException(404, "Prescription not found.")
    if row.prescribed_by_account_id != acc.id:
        raise HTTPException(403, "Only the prescribing coach can remove this.")
    db.delete(row)
    db.commit()
    return {"success": True, "message": "Prescription removed."}


def _build_prescribed_item(
    db: Session, row: ClientPrescribedMeal
) -> PrescribedMealItem:
    meal = db.get(Meal, row.meal_id)
    if meal is None:
        # The meal got deleted but the prescription row dangling. Surface it
        # gracefully with a placeholder rather than 500ing.
        return PrescribedMealItem(
            id=row.id,
            meal_id=row.meal_id,
            client_id=row.client_id,
            prescribed_by_account_id=row.prescribed_by_account_id,
            prescribed_by_name=None,
            prescribed_at=row.last_updated,
            scheduled_date=row.scheduled_date,
            meal_kind=row.meal_kind,
            meal=MealDetailResponse(
                id=row.meal_id,
                meal_name="(deleted meal)",
                created_by_account_id=0,
                created_by_name=None,
                foods=[],
                totals=MealTotals(calories=0, protein_g=0, carbs_g=0, fat_g=0),
            ),
        )
    coach = db.get(Account, row.prescribed_by_account_id)
    return PrescribedMealItem(
        id=row.id,
        meal_id=row.meal_id,
        client_id=row.client_id,
        prescribed_by_account_id=row.prescribed_by_account_id,
        prescribed_by_name=coach.name if coach else None,
        prescribed_at=row.last_updated,
        scheduled_date=row.scheduled_date,
        meal_kind=row.meal_kind,
        meal=_serialize_meal_detail(db, meal),
    )
