from hashlib import sha256
from typing import Optional

from src import config
from src.api.auth.domain import SignupRequest
from src.database.account.models import Account

def hash_password(password: str) -> str:
    salted = f"{password}{config.JWT_SECRET}".encode("utf-8")
    return sha256(salted).hexdigest()

def create_account(payload: SignupRequest) -> Account:
    account_data = payload.dict(exclude_none=True, exclude={"password"})
    account_data["hashed_password"] = hash_password(payload.password)
    return Account(**account_data)

def account_roles(account: Account) -> list[str]:
    roles: list[str] = []

    if account.client_id is not None:
        roles.append("client")
    if account.coach_id is not None:
        roles.append("coach")
    if account.admin_id is not None:
        roles.append("admin")

    if not roles:
        roles.append("client")

    return roles

def serialize_account(account: Account) -> dict:
    data = account.model_dump(exclude={"hashed_password"})

    return data