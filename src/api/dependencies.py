from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import Session, select

from src import config
from src.api.auth.services import hash_password
from src.database.account.models import Account
from src.database.session import get_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def create_jwt_token(user: Account) -> str:
    expire = datetime.utcnow() + timedelta(hours=2)
    to_encode = {"sub": str(user.id), "exp": expire}
    return jwt.encode(to_encode, config.JWT_SECRET, algorithm=config.ALGORITHM)


def authenticate_user(db: Session, email: str, password: str) -> Account | None:
    user = db.exec(select(Account).where(Account.email == email)).first()

    if user is None:
        return None

    if user.hashed_password != hash_password(password):
        return None

    return user

#authorization: bearer <tok> # tok == jwt

def get_account_from_bearer(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> Account:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.ALGORITHM])
        account_id_str = payload.get("sub")

        if account_id_str is None:
            raise credentials_exception

        account_id = int(account_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.get(Account, account_id)

    if user is None:
        raise credentials_exception

    return user


"""
ROLE BASED DEPENDENCIES, USE FOR FEATURES / ENDPOINTS THAT REQUIRE THESE ROLES SPECIFICALLY
"""

role_authorization_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your are not authorized to use this resource",
        headers={"WWW-Authenticate": "Bearer"},
)

#this will err when the user doesn't fill out initial survey
def get_client_account(account: Account = Depends(get_account_from_bearer)):
    if account.client_id is None:
        raise role_authorization_exception
    else:
        return account #account routes down to role resources

def get_coach_account(account: Account = Depends(get_account_from_bearer)):
    if account.coach_id is None:
        raise role_authorization_exception
    else:
        return account #account routes down to role resources
    
def get_admin_account(account: Account = Depends(get_account_from_bearer)):
    if account.admin_id is None:
        raise role_authorization_exception
    else:
        return account #account routes down to role resources

