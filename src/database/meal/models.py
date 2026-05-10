from datetime import date, datetime
from typing import Optional

from sqlmodel import Field

from src.database.base import SQLModelLU


class Unit(SQLModelLU, table=True):
    __tablename__ = "unit"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    unit_name: str
    is_imperial: bool


class Food(SQLModelLU, table=True):
    """A single food item, optionally cached from the USDA FoodData Central API.
    Macros are stored per-100g so we can compute calories for any serving by
    multiplying by `grams / 100`. `fdc_id` is nullable so admins/clients can
    add custom foods (e.g. homemade dishes) that aren't in USDA's database."""
    __tablename__ = "food"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    fdc_id: Optional[int] = Field(default=None, index=True, unique=True)
    name: str = Field(index=True)
    brand_owner: Optional[str] = None
    data_type: Optional[str] = None  # "Foundation", "Branded", "SR Legacy", etc.
    calories_per_100g: float
    protein_g_per_100g: float = 0.0
    carbs_g_per_100g: float = 0.0
    fat_g_per_100g: float = 0.0
    cached_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class MealFood(SQLModelLU, table=True):
    """Join row: meal X contains `grams` grams of food Y. Calories for the
    line are derived (food.calories_per_100g * grams / 100), not stored.
    This is the path used by all *new* coach- and client-built meals.
    Legacy seed-data meals continue to use `meal_ingredient` instead; the
    meal-detail and calorie aggregation queries union across both."""
    __tablename__ = "meal_food"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id", ondelete="CASCADE", index=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    grams: float


class PortionSize(SQLModelLU, table=True):
    __tablename__ = "portion_size"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id")
    count: int


class MealIngredient(SQLModelLU, table=True): #each meal ingredient calories is sourced from USDA food database, which provides calories per portion size, and portion size is defined by a count and unit (e.g. 1 cup of rice, 2 tbsp of olive oil)
    __tablename__ = "meal_ingredient"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id")
    ingredient_name: str
    portion_size_id: int = Field(foreign_key="portion_size.id")
    calories: int


class Meal(SQLModelLU, table=True):
    __tablename__ = "meal"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    # SET NULL — when a coach who authored a meal deletes their account, the
    # meal stays in the catalog (other clients may have it prescribed) but
    # loses its author attribution.
    created_by_account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="SET NULL")
    meal_name: str


class ClientPrescribedMeal(SQLModelLU, table=True):
    __tablename__ = "client_prescribed_meal"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id")
    # Both FKs SET NULL: a deleted client / coach doesn't take prescription
    # history with them. The row still resolves through `meal_id` and the
    # date/kind so historical compliance reports keep working.
    client_id: Optional[int] = Field(default=None, foreign_key="client.id", ondelete="SET NULL")
    prescribed_by_account_id: Optional[int] = Field(default=None, foreign_key="account.id", index=True, ondelete="SET NULL")
    # Weekly plan support: a coach can schedule a meal to a specific date
    # + meal_kind ("breakfast"/"lunch"/"dinner"/"snack"). When NULL, the
    # prescription is a standing recipe the client can log on any day.
    scheduled_date: Optional[date] = Field(default=None, index=True)
    meal_kind: Optional[str] = Field(default=None)