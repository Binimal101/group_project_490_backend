import os
from sqlmodel import create_engine, Session
from src import config

DATABASE_URL = config.DATABASE_URL

# Control SQLAlchemy echo via env `SQL_ECHO` (false by default to reduce verbosity)
SQL_ECHO = str(os.getenv("SQL_ECHO", "false")).strip().lower() in ("1", "true", "yes")
engine = create_engine(DATABASE_URL, echo=SQL_ECHO)

# dependency that FastAPI can inject

def get_session():
    with Session(engine) as session:
        yield session
