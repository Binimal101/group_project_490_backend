from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
import os
import secrets
import requests

from src.api.auth.domain import AuthTokenResponse, LoginRequest, SignupRequest
from src.api.auth.services import create_account
from src.api.dependencies import authenticate_user, create_jwt_token
from src.database.account.models import Account
from src.database.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def issue_token(user: Account) -> AuthTokenResponse:
    token = create_jwt_token(user)
    return AuthTokenResponse(access_token=token)


@router.post("/signup", response_model=AuthTokenResponse)
def signup(
    data: SignupRequest,
    db: Session = Depends(get_session),
):
    existing_user = db.exec(select(Account).where(Account.email == data.email)).first()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    user = create_account(data)
    db.add(user)
    db.commit()
    db.refresh(user)

    return issue_token(user)


@router.post("/login", response_model=AuthTokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_session),
):
    user = authenticate_user(db, data.email, data.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return issue_token(user)


@router.post("/token", response_model=AuthTokenResponse)
def token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_session),
):
    user = authenticate_user(db, form_data.username, form_data.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return issue_token(user)


@router.get("/google")
def google_oauth(request: Request, code: str | None = None, state: str | None = None, db: Session = Depends(get_session)):
    """
    OAuth2 Authorization Code flow for Google.

    - Calling redirects to Google's consent screen.
    On success this endpoint issues a local JWT for the user.
    """

    client_id = os.getenv("GCP_CLIENT_ID")
    client_secret = os.getenv("GCP_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GCP_CLIENT_ID and GCP_CLIENT_SECRET must be configured")

    redirect_uri =  "https://api.till-failure.us/auth/google"

    if code is None:
        oauth_state = secrets.token_urlsafe(16)
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email profile",
            "redirect_uri": redirect_uri,
            "state": oauth_state,
            "access_type": "offline",
            "prompt": "consent",
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth"
        qs = "?" + "&".join(f"{k}={requests.utils.requote_uri(str(v))}" for k, v in params.items())
        resp = RedirectResponse(url + qs)

        resp.set_cookie("oauth_state", oauth_state, httponly=True, secure=True, samesite="lax")
        return resp

    # Verify state from callback
    cookie_state = request.cookies.get("oauth_state")
    if cookie_state is None or state is None or cookie_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    token_res = requests.post(token_url, data=data)
    
    if token_res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {token_res.text}")
    
    token_json = token_res.json()
    id_token = token_json.get("id_token")
    
    if not id_token:
        raise HTTPException(status_code=502, detail="No id_token returned from Google")

    #validate
    info_res = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token})
    if info_res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"id_token validation failed: {info_res.text}")
    info = info_res.json()

    if info.get("aud") != client_id:
        raise HTTPException(status_code=400, detail="id_token aud mismatch")

    google_user_id = info.get("sub")
    email = info.get("email")
    name = info.get("name") or email.split("@")[0]
    picture = info.get("picture")

    # Find or create local account
    user = db.exec(select(Account).where(Account.gcp_user_id == google_user_id)).first()
    if not user:
        existing = db.exec(select(Account).where(Account.email == email)).first()
        if existing:
            existing.gcp_user_id = google_user_id
            existing.pfp_url = existing.pfp_url or picture
            db.add(existing)
            db.commit()
            db.refresh(existing)
            user = existing
        else:
            user = Account(name=name, email=email, gcp_user_id=google_user_id, pfp_url=picture)
            db.add(user)
            db.commit()
            db.refresh(user)

    # Issue local JWT
    token_resp = issue_token(user)
    jwt_token = token_resp.access_token

    redirect_to = "https://till-failure.us/onboarding"
    resp = RedirectResponse(redirect_to)

    cookie_value = requests.utils.requote_uri(jwt_token)
    cookie_args = {
        "httponly": False,
        "secure": True,
        "samesite": "none",
        "domain": ".till-failure.us",
        "max_age": 60 * 60 * 24 * 30,  # 30 days
    }

    resp.set_cookie("jwt", cookie_value, **cookie_args)

    # cleanup
    resp.delete_cookie("oauth_state")

    return resp