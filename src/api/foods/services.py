"""USDA FoodData Central client + nutrient extraction.

The USDA payload is verbose and shape-shifty. This module is the only place
that knows about it; the route layer just gets clean dicts back.

Nutrient identifiers we care about (USDA-stable across data types):
  1008 = Energy (kcal)
  1003 = Protein (g)
  1005 = Carbohydrate, by difference (g)
  1004 = Total lipid (fat) (g)
"""
import httpx
from typing import Optional

from src import config

_BASE = "https://api.nal.usda.gov/fdc/v1"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Nutrient IDs per USDA's nutrient table.
NUTRIENT_KCAL = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_CARBS = 1005
NUTRIENT_FAT = 1004


def _api_key() -> str:
    return config.USDA_API_KEY or "DEMO_KEY"


async def search_foods(query: str, page_size: int = 25) -> dict:
    """Hit /foods/search via POST so we can pass dataType as a JSON array.
    USDA's GET endpoint 400s when dataType is sent as repeated query params,
    which is what httpx generates for a list value. POST with a JSON body is
    the supported way to filter by multiple data types.

    We default to Foundation/Survey/SR Legacy and skip Branded foods because
    Branded is huge and dominates results with noisy commercial products."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_BASE}/foods/search",
            params={"api_key": _api_key()},
            json={
                "query": query,
                "pageSize": page_size,
                "dataType": ["Foundation", "Survey (FNDDS)", "SR Legacy"],
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_food_detail(fdc_id: int) -> dict:
    """Hit /food/{fdcId}. Returns raw USDA payload."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_BASE}/food/{fdc_id}",
            params={"api_key": _api_key()},
        )
        resp.raise_for_status()
        return resp.json()


def extract_macros_per_100g(food_payload: dict) -> dict:
    """Normalize a USDA food detail to {kcal, protein, carbs, fat} per 100g.
    USDA stores nutrients in a `foodNutrients` list; each entry has a nested
    `nutrient` block with an `id` we match against our constants. Branded
    foods sometimes use a flatter shape (`nutrientId` directly on the
    foodNutrient row), so we handle both."""
    out = {
        "calories_per_100g": 0.0,
        "protein_g_per_100g": 0.0,
        "carbs_g_per_100g": 0.0,
        "fat_g_per_100g": 0.0,
    }
    for n in food_payload.get("foodNutrients") or []:
        nid = (
            (n.get("nutrient") or {}).get("id")
            or n.get("nutrientId")
            or n.get("number")
        )
        try:
            nid = int(nid) if nid is not None else None
        except (TypeError, ValueError):
            nid = None
        amount = n.get("amount") if n.get("amount") is not None else n.get("value")
        if amount is None:
            continue
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if nid == NUTRIENT_KCAL:
            out["calories_per_100g"] = amount
        elif nid == NUTRIENT_PROTEIN:
            out["protein_g_per_100g"] = amount
        elif nid == NUTRIENT_CARBS:
            out["carbs_g_per_100g"] = amount
        elif nid == NUTRIENT_FAT:
            out["fat_g_per_100g"] = amount
    return out


def extract_search_macros(hit: dict) -> dict:
    """Same as extract_macros_per_100g but for the abridged search-result
    shape, which USDA returns in `foodNutrients` with slightly different keys."""
    out = {
        "calories_per_100g": None,
        "protein_g_per_100g": None,
        "carbs_g_per_100g": None,
        "fat_g_per_100g": None,
    }
    for n in hit.get("foodNutrients") or []:
        # Abridged hits use `nutrientId` directly + `value`.
        nid = n.get("nutrientId") or (n.get("nutrient") or {}).get("id")
        try:
            nid = int(nid) if nid is not None else None
        except (TypeError, ValueError):
            continue
        val = n.get("value") if n.get("value") is not None else n.get("amount")
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if nid == NUTRIENT_KCAL:
            out["calories_per_100g"] = val
        elif nid == NUTRIENT_PROTEIN:
            out["protein_g_per_100g"] = val
        elif nid == NUTRIENT_CARBS:
            out["carbs_g_per_100g"] = val
        elif nid == NUTRIENT_FAT:
            out["fat_g_per_100g"] = val
    return out


def pick_food_name(payload: dict) -> str:
    """USDA detail uses `description`; search hits sometimes use
    `lowercaseDescription`. Fall back through the chain."""
    return (
        payload.get("description")
        or payload.get("lowercaseDescription")
        or payload.get("name")
        or "Unknown food"
    )


def pick_brand(payload: dict) -> Optional[str]:
    return payload.get("brandOwner") or payload.get("brandName") or None


def pick_data_type(payload: dict) -> Optional[str]:
    return payload.get("dataType") or None
