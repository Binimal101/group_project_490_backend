import os

import requests
from fastapi import HTTPException, UploadFile

from src import config


def upload_public_file_to_supabase(file: UploadFile, bucket: str, filename_prefix: str) -> str:
    supabase_url = config.SUPABASE_URL or os.getenv("SUPABASE_URL")
    supabase_service_key = (
        config.SUPABASE_SERVICE_KEY
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )

    if not supabase_url or not supabase_service_key:
        raise HTTPException(500, detail="Supabase storage is not configured on the server")

    raw_filename = file.filename or "upload"
    safe_filename = raw_filename.replace("\\", "/").split("/")[-1]
    filename = f"{filename_prefix}_{safe_filename}"
    base_url = supabase_url.rstrip("/")
    upload_url = f"{base_url}/storage/v1/object/{bucket}/{filename}"

    headers = {
        "Authorization": f"Bearer {supabase_service_key}",
        "apikey": supabase_service_key,
    }
    if file.content_type:
        headers["Content-Type"] = file.content_type

    try:
        resp = requests.put(upload_url, data=file.file, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise HTTPException(500, detail=f"Upload failed: {e}")

    if resp.status_code not in (200, 201, 204):
        raise HTTPException(resp.status_code, detail=f"Upload failed: {resp.text}")

    return f"{base_url}/storage/v1/object/public/{bucket}/{filename}"
