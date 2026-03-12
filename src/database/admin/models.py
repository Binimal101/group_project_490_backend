from sqlmodel import SQLModel, Field
from datetime import datetime

class Admin(SQLModel, table=True):
    __tablename__ = "admin"

    id: int = Field(primary_key=True)
    last_updated: datetime
