"""Promote an existing account to admin if it does not already have an admin row."""

from sqlmodel import Session

import src.database  # noqa: F401 - registers ORM models with SQLModel.metadata
from src import config  # noqa: F401 - loads env-backed config during import
from src.database.account.models import Account
from src.database.admin.models import Admin
from src.database.session import engine


def _prompt_for_account_id() -> int:
    while True:
        raw_value = input("Enter account_id: ").strip()
        try:
            return int(raw_value)
        except ValueError:
            print("Please enter a valid integer account_id.")


def main() -> None:
    account_id = _prompt_for_account_id()

    with Session(engine) as session:
        account = session.get(Account, account_id)

        if account is None:
            print(f"account_{account_id} was not found")
            return

        if account.admin_id is not None:
            print("this account is already an admin")
            return

        admin = Admin()
        session.add(admin)
        session.flush()

        account.admin_id = admin.id
        session.add(account)
        session.commit()
        session.refresh(admin)
        session.refresh(account)

        print(f"account_{account_id} is now also admin_{admin.id}")


if __name__ == "__main__":
    main()