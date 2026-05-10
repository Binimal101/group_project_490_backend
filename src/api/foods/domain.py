"""Pydantic models for the foods/USDA proxy.

The USDA FoodData Central response is large and inconsistent (different shapes
for Foundation vs Branded vs Survey foods). The models here only expose the
fields the rest of the app actually needs — name + macros — so callers don't
have to know the upstream wire format.
"""
from typing import List, Optional
from pydantic import BaseModel


class FoodSearchResultItem(BaseModel):
    """One row in a USDA search result. `fdc_id` is the upstream identifier;
    we expose it so the client can call /api/foods/{fdc_id} for full detail."""
    fdc_id: int
    name: str
    brand_owner: Optional[str] = None
    data_type: Optional[str] = None
    # USDA returns "abridged" macro fields on search hits, so we surface them
    # to avoid a second round-trip just to render the search list.
    calories_per_100g: Optional[float] = None
    protein_g_per_100g: Optional[float] = None
    carbs_g_per_100g: Optional[float] = None
    fat_g_per_100g: Optional[float] = None


class FoodSearchResponse(BaseModel):
    query: str
    total_hits: int
    foods: List[FoodSearchResultItem]


class FoodDetailResponse(BaseModel):
    """Macros for a single food, normalized per 100g.
    `id` is our internal `food.id` (created/upserted on detail fetch);
    `fdc_id` is the USDA identifier. Callers building a meal use `id`."""
    id: int
    fdc_id: Optional[int] = None
    name: str
    brand_owner: Optional[str] = None
    data_type: Optional[str] = None
    calories_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
