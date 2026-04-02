from datetime import datetime

from sqlmodel import Field, SQLModel


class SQLModelLU(SQLModel):
    last_updated: datetime = Field(default_factory=datetime.utcnow)
