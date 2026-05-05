from src import config
from sqlalchemy import create_engine, text

engine = create_engine(config.DATABASE_URL)
with engine.connect() as conn:
    result = conn.execute(text("SELECT enumlabel FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = 'weekday' ORDER BY enumsortorder"))
    print(result.all())
    for label in ['monday', 'MONDAY', 'tuesday', 'TUESDAY']:
        try:
            print(label, conn.execute(text(f"SELECT '{label}'::weekday")).all())
        except Exception as exc:
            print(label, type(exc).__name__, exc)
