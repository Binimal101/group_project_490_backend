from sqlmodel import Session

import src.database
from src import config
from src.database.account.models import Account
from src.database.admin.models import Admin
from src.database.session import engine



while True:
    raw_value = input("Enter account_id: ").strip()
    try:
        account_id = int(raw_value)
        break
    except ValueError:
        print("Please enter a valid integer account_id.")

with Session(engine) as session:
    account = session.get(Account, account_id)

    if account is None:
        print(f"account_{account_id} was not found")
        exit()

    if account.admin_id is not None:
        print("this account is already an admin")
        exit()

    admin = Admin()
    session.add(admin)
    session.flush()

    account.admin_id = admin.id
    session.add(account)
    session.commit()
    session.refresh(admin)
    session.refresh(account)

    print(f"account_{account_id} is now also admin_{admin.id}")