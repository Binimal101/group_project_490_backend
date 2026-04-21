from fastapi import APIRouter, Depends, UploadFile, HTTPException
import requests
from src import config

from src.database.session import get_session
from src.database.account.models import Account
from src.api.dependencies import get_account_from_bearer
from sqlmodel import Session

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
