"""Pydantic models for meal building, browsing, and prescribing.

The shape of a "meal" the UI works with:
  - meal_name (str)
  - foods: [{food_id, name, grams, calories, protein, carbs, fat}]
  - totals: {calories, protein, carbs, fat}

Calories/macros are always derived (food.kcal_per_100g * grams / 100), never
stored, so a meal stays correct even if upstream USDA data is later
re-cached.
"""
from datetime import date, datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

# Meal kinds the UI offers. We accept anything (the column is plain text) but
# constrain inputs to this set so the data stays clean.
MealKind = Literal["breakfast", "lunch", "dinner", "snack"]


class MealFoodInput(BaseModel):
    """One ingredient line in a create-meal request."""
    food_id: int
    grams: float = Field(gt=0, description="Serving in grams; must be positive.")


class CreateMealRequest(BaseModel):
    meal_name: str = Field(min_length=1, max_length=120)
    foods: List[MealFoodInput] = Field(min_length=1)


class MealFoodLine(BaseModel):
    """One ingredient line in a meal-detail response."""
    food_id: int
    food_name: str
    grams: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MealTotals(BaseModel):
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MealSummary(BaseModel):
    """Used for library listings — name + totals only, no ingredient breakdown."""
    id: int
    meal_name: str
    created_by_account_id: int
    created_by_name: Optional[str] = None
    totals: MealTotals


class MealDetailResponse(BaseModel):
    """Full meal — used by both coach (when building/editing) and client
    (when viewing a prescribed meal)."""
    id: int
    meal_name: str
    created_by_account_id: int
    created_by_name: Optional[str] = None
    foods: List[MealFoodLine]
    totals: MealTotals


class PrescribeMealRequest(BaseModel):
    """Coach assigns a meal to a client. `scheduled_date` + `meal_kind` are
    optional — when both are set, the meal lives on the weekly planner;
    when both null, it's a standing recipe the client can log any day.
    Mixed (one set, one null) is allowed but rare in practice."""
    meal_id: int
    scheduled_date: Optional[date] = None
    meal_kind: Optional[MealKind] = None


class PrescribedMealItem(BaseModel):
    """One row in 'meals my coach prescribed me' / 'meals I prescribed to X'.
    Includes the embedded meal so the client UI can render without a second
    fetch per row."""
    id: int
    meal_id: int
    client_id: int
    prescribed_by_account_id: int
    prescribed_by_name: Optional[str] = None
    prescribed_at: Optional[datetime] = None
    scheduled_date: Optional[date] = None
    meal_kind: Optional[str] = None
    meal: MealDetailResponse


class CaloriesTodayResponse(BaseModel):
    """Summed calories for the calories card on the client dashboard.
    `meal_calories` is the bit derived from logged meals; `goal` is the
    client's daily target (placeholder for now — wires through whatever
    the dashboard uses)."""
    calories_consumed: float
    protein_g: float
    carbs_g: float
    fat_g: float
    meal_count: int
