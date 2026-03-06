import os
from dataclasses import dataclass

if (db_conn_str := os.getenv("DATABASE_CONNECTION_STRING", None)) is None:
    raise Exception("Error, no database connection string found")

...

@dataclass
class project_settings:
    database_connection_string: str = db_conn_str

