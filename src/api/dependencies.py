from fastapi import Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import Session, select
from datetime import datetime, timedelta

from src import config
from src.api.auth.services import hash_password
from src.database.account.models import Account
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import ClientCoachRequest, ClientCoachRelationship
from src.database.session import get_session
from src.api.roles.shared.domain import ClientCoachContext

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
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive account")

    return user

def get_active_account(account: Account = Depends(get_account_from_bearer)) -> Account:
    if not account.is_active:
        raise HTTPException(status_code=400, detail="Inactive account")
    return account

def get_account_even_if_inactive(
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
def get_client_account(account: Account = Depends(get_active_account)):
    if account.client_id is None:
        raise role_authorization_exception
    else:
        return account #account routes down to role resources

def get_coach_account(
    account: Account = Depends(get_active_account),
    db: Session = Depends(get_session)
):
    if account.coach_id is None:
        raise role_authorization_exception
    coach = db.get(Coach, account.coach_id)
    if not coach or not coach.verified:
        raise role_authorization_exception
    return account #account routes down to role resources
    
def get_admin_account(account: Account = Depends(get_active_account)):
    if account.admin_id is None:
        raise role_authorization_exception
    else:
        return account #account routes down to role resources


#client-coach stateful decoupling

def build_client_coach_contexts(
    *,
    account: Account,
    request: ClientCoachRequest,
    db: Session,
) -> dict[str, ClientCoachContext]:
    if account.id is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.client_id == request.client_id:
        other_account = db.exec(select(Account).where(Account.coach_id == request.coach_id)).first()
        user_context = ClientCoachContext(is_client=True, is_coach=False, account=account)
        other_context = ClientCoachContext(is_client=False, is_coach=True, account=other_account) if other_account and other_account.id is not None else None
    elif account.coach_id == request.coach_id:
        other_account = db.exec(select(Account).where(Account.client_id == request.client_id)).first()
        user_context = ClientCoachContext(is_client=False, is_coach=True, account=account)
        other_context = ClientCoachContext(is_client=True, is_coach=False, account=other_account) if other_account and other_account.id is not None else None
    else:
        raise HTTPException(status_code=403, detail="Not authorized to use this request")

    if other_context is None:
        raise HTTPException(status_code=404, detail="Target account not found")

    return {"user": user_context, "other": other_context}

# developer facing DI functions

def client_coach_request_context(
    request_id: int,
    db: Session = Depends(get_session),
    account: Account = Depends(get_active_account),
) -> dict[str, ClientCoachContext]:
    request = db.get(ClientCoachRequest, request_id)

    if request is None:
        raise HTTPException(status_code=404, detail="Request not found")

    return build_client_coach_contexts(account=account, request=request, db=db)


def client_coach_relationship_context(
    relationship_id: int,
    db: Session = Depends(get_session),
    account: Account = Depends(get_active_account),
) -> dict[str, ClientCoachContext]:
    relationship = db.get(ClientCoachRelationship, relationship_id)

    if relationship is None:
        raise HTTPException(status_code=404, detail="Relationship not found")

    request = db.get(ClientCoachRequest, relationship.request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Associated request not found")

    return build_client_coach_contexts(account=account, request=request, db=db)

# Parametrization dependencies

class PaginationParams:
    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Number of records to skip for pagination"),
        limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return")
    ):
        self.skip = skip
        self.limit = limit

