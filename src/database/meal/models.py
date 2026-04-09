from typing import Optional

from sqlmodel import Field

from src.database.base import SQLModelLU


class Unit(SQLModelLU, table=True):
    __tablename__ = "unit"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    unit_name: str
    is_imperial: bool


class PortionSize(SQLModelLU, table=True):
    __tablename__ = "portion_size"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id")
    count: int


class Meal(SQLModelLU, table=True):
    __tablename__ = "meal"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    created_by_account_id: int = Field(foreign_key="account.id", index=True)
    meal_name: str
    calories: int
    portion_size_id: int = Field(foreign_key="portion_size.id")


class ClientPrescribedMeal(SQLModelLU, table=True):
    __tablename__ = "client_prescribed_meal"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id")
    client_id: int = Field(foreign_key="client.id", ondelete="CASCADE")
    prescribed_by_account_id: int = Field(foreign_key="account.id", index=True)