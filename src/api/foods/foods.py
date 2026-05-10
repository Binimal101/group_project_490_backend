"""Foods API — search USDA, fetch detail (with caching), list local cache.

Routes are role-agnostic: any authenticated user can call them. They're used
by both the coach UI (when building a meal) and the client UI (when adding a
custom logged meal).
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
import httpx

from src.api.dependencies import get_active_account
from src.database.session import get_session
from src.database.account.models import Account
from src.database.meal.models import Food
from src.api.foods.domain import (
    FoodSearchResponse,
    FoodSearchResultItem,
    FoodDetailResponse,
)
from src.api.foods import services as usda

router = APIRouter(prefix="/api/foods", tags=["foods"])


@router.get("/search", response_model=FoodSearchResponse)
async def search_foods(
    q: str = Query(..., min_length=1, description="Search term (food name)"),
    page_size: int = Query(25, ge=1, le=50),
    acc: Account = Depends(get_active_account),
):
    """Pass-through to USDA `/foods/search` with the abridged macro fields
    pulled out so the client can render a search list without a second
    round-trip per row.

    USDA returns 401 if the API key is invalid or 429 if rate-limited; we
    surface those as 502/429 rather than 500 so callers can tell the
    difference between a USDA outage and our own bug."""
    try:
        payload = await usda.search_foods(q, page_size=page_size)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise HTTPException(502, "USDA API key rejected by upstream.") from e
        if e.response.status_code == 429:
            raise HTTPException(429, "USDA rate limit hit; try again shortly.") from e
        raise HTTPException(502, f"USDA upstream error ({e.response.status_code}).") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"USDA upstream unreachable: {e}") from e

    foods_raw = payload.get("foods") or []
    items: List[FoodSearchResultItem] = []
    for hit in foods_raw:
        fdc_id = hit.get("fdcId")
        if fdc_id is None:
            continue
        macros = usda.extract_search_macros(hit)
        items.append(FoodSearchResultItem(
            fdc_id=int(fdc_id),
            name=usda.pick_food_name(hit),
            brand_owner=usda.pick_brand(hit),
            data_type=usda.pick_data_type(hit),
            calories_per_100g=macros["calories_per_100g"],
            protein_g_per_100g=macros["protein_g_per_100g"],
            carbs_g_per_100g=macros["carbs_g_per_100g"],
            fat_g_per_100g=macros["fat_g_per_100g"],
        ))

    return FoodSearchResponse(
        query=q,
        total_hits=int(payload.get("totalHits") or len(items)),
        foods=items,
    )


@router.get("/{fdc_id}", response_model=FoodDetailResponse)
async def get_food(
    fdc_id: int,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Fetch one USDA food and upsert it into our `food` table.
    Subsequent calls for the same `fdc_id` return the cached row without
    hitting USDA. This is the route the meal-builder UI calls when the
    user picks a food from search results — gives us a stable
    internal `food.id` to reference in `meal_food`."""
    # Cache hit: serve straight from DB.
    cached = db.exec(select(Food).where(Food.fdc_id == fdc_id)).first()
    if cached:
        return FoodDetailResponse(
            id=cached.id,
            fdc_id=cached.fdc_id,
            name=cached.name,
            brand_owner=cached.brand_owner,
            data_type=cached.data_type,
            calories_per_100g=cached.calories_per_100g,
            protein_g_per_100g=cached.protein_g_per_100g,
            carbs_g_per_100g=cached.carbs_g_per_100g,
            fat_g_per_100g=cached.fat_g_per_100g,
        )

    # Cache miss: hit USDA, parse, persist, return.
    try:
        payload = await usda.get_food_detail(fdc_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(404, f"USDA food {fdc_id} not found.") from e
        if e.response.status_code in (401, 403):
            raise HTTPException(502, "USDA API key rejected by upstream.") from e
        if e.response.status_code == 429:
            raise HTTPException(429, "USDA rate limit hit; try again shortly.") from e
        raise HTTPException(502, f"USDA upstream error ({e.response.status_code}).") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"USDA upstream unreachable: {e}") from e

    macros = usda.extract_macros_per_100g(payload)
    food = Food(
        fdc_id=fdc_id,
        name=usda.pick_food_name(payload),
        brand_owner=usda.pick_brand(payload),
        data_type=usda.pick_data_type(payload),
        calories_per_100g=macros["calories_per_100g"],
        protein_g_per_100g=macros["protein_g_per_100g"],
        carbs_g_per_100g=macros["carbs_g_per_100g"],
        fat_g_per_100g=macros["fat_g_per_100g"],
    )
    db.add(food)
    db.commit()
    db.refresh(food)
    return FoodDetailResponse(
        id=food.id,
        fdc_id=food.fdc_id,
        name=food.name,
        brand_owner=food.brand_owner,
        data_type=food.data_type,
        calories_per_100g=food.calories_per_100g,
        protein_g_per_100g=food.protein_g_per_100g,
        carbs_g_per_100g=food.carbs_g_per_100g,
        fat_g_per_100g=food.fat_g_per_100g,
    )


@router.get("/library/cached", response_model=List[FoodDetailResponse])
def list_cached_foods(
    q: Optional[str] = Query(None, description="Optional name filter"),
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """List foods we've already cached locally — useful for offline-style
    meal building when USDA is rate-limited, or for showing 'recently used'
    foods. Filters by name substring if `q` provided."""
    stmt = select(Food)
    if q:
        stmt = stmt.where(Food.name.ilike(f"%{q}%"))  # type: ignore[attr-defined]
    stmt = stmt.order_by(Food.name.asc()).offset(skip).limit(limit)
    rows = db.exec(stmt).all()
    return [
        FoodDetailResponse(
            id=r.id,
            fdc_id=r.fdc_id,
            name=r.name,
            brand_owner=r.brand_owner,
            data_type=r.data_type,
            calories_per_100g=r.calories_per_100g,
            protein_g_per_100g=r.protein_g_per_100g,
            carbs_g_per_100g=r.carbs_g_per_100g,
            fat_g_per_100g=r.fat_g_per_100g,
        )
        for r in rows
    ]
