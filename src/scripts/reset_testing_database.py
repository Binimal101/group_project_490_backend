"""Reset the database schema using SQLModel metadata.

This script reads DATABASE_URL from environment variables,
drops all existing tables, and recreates tables from current ORM metadata.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import MetaData
from sqlmodel import SQLModel, create_engine

import src.database #will load all submodules and their models, which registers them with SQLModel.metadata


def reset_database_schema(database_url: str) -> None:
    engine = create_engine(database_url, echo=True)

    # Drop everything that currently exists in the target DB.
    reflected_metadata = MetaData()
    reflected_metadata.reflect(bind=engine)
    reflected_metadata.drop_all(bind=engine)

    # Recreate schema from current ORM metadata.
    SQLModel.metadata.create_all(bind=engine)


def main() -> None:
    load_dotenv()

    from src import config
    
    print("Overwriting config values to ensure testing database is used for this script...")
    config.DATABASE_URL = os.getenv("TESTING_DATABASE_URL") # type: ignore
    database_url = config.DATABASE_URL
    
    if not database_url:
        raise RuntimeError("TESTING_DATABASE_URL environment variable is not set")

    if input("This will IRREVERSIBLY DESTROY ALL DATA in the testing database. Type 'y' to confirm: ") != "y":
        print("Aborting.")
        return

    reset_database_schema(database_url)
    print("Database schema reset complete.")


if __name__ == "__main__":
    main()
