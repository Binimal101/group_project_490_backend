from fastapi import APIRouter, Depends, UploadFile, HTTPException
import requests
from src import config

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_account_from_bearer, get_active_account, get_account_even_if_inactive
from sqlmodel import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/roles/shared/account", tags=["shared", "account"])


@router.post("/update_pfp")
def update_profile_picture(
    file: UploadFile,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_account_from_bearer),
):
    """
    Uploads the provided file to the `profile_picture` bucket and updates the
    current account's `pfp_url` to the public URL for the uploaded object.
    """
    import os

    SUPABASE_URL = config.SUPABASE_URL or os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = config.SUPABASE_SERVICE_KEY or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(500, detail="Supabase storage is not configured on the server")

    bucket = "profile_picture"
    filename = f"{acc.id}_{file.filename}"
    upload_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{filename}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }

    try:
        # stream upload
        resp = requests.put(upload_url, data=file.file, headers=headers)
    except Exception as e:
        raise HTTPException(500, detail=f"Upload failed: {e}")

    if resp.status_code not in (200, 201, 204):
        raise HTTPException(resp.status_code, detail=f"Upload failed: {resp.text}")

    public_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{filename}"

    # persist to account
    account = db.get(Account, acc.id)
    account.pfp_url = public_url
    db.add(account)
    db.commit()
    db.refresh(account)

    return {"url": public_url}


class UpdateAccountInput(BaseModel):
    age: Optional[int] = None
    email: Optional[EmailStr] = None
    bio: Optional[str] = None
    pfp_url: Optional[str] = None
    gender: Optional[str] = None


class AccountResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    gender: Optional[str] = None
    bio: Optional[str] = None
    age: Optional[int] = None
    pfp_url: Optional[str] = None
    client_id: Optional[int] = None
    coach_id: Optional[int] = None
    admin_id: Optional[int] = None
    created_at: Optional[datetime] = None


class DeactivateAccountResponse(BaseModel):
    success: bool
    message: str

class ActivateAccountResponse(BaseModel):
    success: bool
    message: str


@router.post("/deactivate", response_model=DeactivateAccountResponse)
def deactivate_account(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Deactivate the current user's account. This sets is_active to False and prevents login/access.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")
    if not account.is_active:
        return DeactivateAccountResponse(success=False, message="Account is already deactivated.")
    account.is_active = False
    db.add(account)
    db.commit()
    db.refresh(account)
    return DeactivateAccountResponse(success=True, message="Account deactivated successfully.")


@router.post("/activate", response_model=ActivateAccountResponse)
def activate_account(
    db: Session = Depends(get_session),
    acc: Account = Depends(get_account_even_if_inactive),
):
    """
    Activate the current user's account. This sets is_active to True and allows login/access.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")
    if account.is_active:
        return ActivateAccountResponse(success=False, message="Account is already active.")
    account.is_active = True
    db.add(account)
    db.commit()
    db.refresh(account)
    return ActivateAccountResponse(success=True, message="Account activated successfully.")


@router.patch("/update", response_model=AccountResponse)
def update_account(
    payload: UpdateAccountInput,
    db: Session = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """
    Update mutable fields on the current user's Account: `age`, `email`, `bio`, `pfp_url`, and `gender`.
    Only fields present in the payload are updated.
    """
    account = db.get(Account, acc.id)
    if account is None:
        raise HTTPException(404, detail="Account not found")

    if payload.age is not None:
        account.age = payload.age
    if payload.email is not None:
        account.email = payload.email
    if payload.bio is not None:
        account.bio = payload.bio
    if payload.pfp_url is not None:
        account.pfp_url = payload.pfp_url
    if payload.gender is not None:
        account.gender = payload.gender

    db.add(account)
    db.commit()
    db.refresh(account)

    # Return the account using the response_model which will exclude sensitive fields
    return account
