from io import BytesIO
import os
import pytest
import requests

# Allow running these tests against a real Supabase project when credentials/buckets exist.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")


@pytest.mark.skipif(not (SUPABASE_URL and SUPABASE_SERVICE_KEY), reason="Supabase credentials not set; skipping integration upload tests")
def test_upload_progress_picture_returns_url(test_client, client_auth_header):
    # Prepare a simple in-memory file
    file_content = b"\x89PNG\r\n\x1a\n"  # PNG header bytes
    files = {"file": ("progress.png", BytesIO(file_content), "image/png")}

    # Ensure the bucket exists and is public (create via admin API if necessary)
    def ensure_bucket(bucket_name):
        admin_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/admin/buckets"
        headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY, "Content-Type": "application/json"}
        # Try to create; if exists, API returns 409 or similar — ignore errors
        try:
            resp = requests.post(admin_url, json={"id": bucket_name, "name": bucket_name, "public": True}, headers=headers, timeout=10)
        except Exception:
            resp = None
        return resp

    ensure_bucket('progress_picture')

    # This will perform a live upload to the configured Supabase project/bucket.
    resp = test_client.post("/roles/client/upload_progress_picture", files=files, headers=client_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("http")


@pytest.mark.skipif(not (SUPABASE_URL and SUPABASE_SERVICE_KEY), reason="Supabase credentials not set; skipping integration upload tests")
def test_update_pfp_updates_account(test_client, auth_header, db_session):
    # sign up / auth_header fixture creates user and returns auth header
    file_content = b"\x89PNG\r\n\x1a\n"
    files = {"file": ("pfp.png", BytesIO(file_content), "image/png")}
    # Ensure the profile bucket exists and is public
    def ensure_bucket(bucket_name):
        admin_url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/admin/buckets"
        headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY, "Content-Type": "application/json"}
        try:
            resp = requests.post(admin_url, json={"id": bucket_name, "name": bucket_name, "public": True}, headers=headers, timeout=10)
        except Exception:
            resp = None
        return resp

    ensure_bucket('profile_picture')

    # This will perform a live upload to the configured Supabase project/bucket.
    resp = test_client.post("/roles/shared/account/update_pfp", files=files, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("http")

    # Verify DB account has pfp_url set
    me_resp = test_client.get("/me", headers=auth_header)
    assert me_resp.status_code == 200
    account = me_resp.json()
    assert account.get("pfp_url") == data["url"]
