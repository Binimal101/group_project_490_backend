import os
from sqlmodel import create_engine, Session
from src import config

DATABASE_URL = config.DATABASE_URL

# Control SQLAlchemy echo via env `SQL_ECHO` (false by default to reduce verbosity)
SQL_ECHO = str(os.getenv("SQL_ECHO", "false")).strip().lower() in ("1", "true", "yes")

# Keep the pool small by default so multiple teammates can run local backends
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "4"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "0"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

engine = create_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
)
