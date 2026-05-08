from io import BytesIO

from src.api import storage
from src.database.telemetry.models import ClientTelemetry, DailyProgressPicture


class MockSupabaseResponse:
    status_code = 200
    text = "ok"


def configure_mock_supabase(monkeypatch):
    monkeypatch.setattr(storage.config, "SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setattr(storage.config, "SUPABASE_SERVICE_KEY", "test-service-key")
    calls = []

    def mock_put(url, data, headers, timeout):
        calls.append({
            "url": url,
            "headers": headers,
            "timeout": timeout,
        })
        return MockSupabaseResponse()

    monkeypatch.setattr(storage.requests, "put", mock_put)
    return calls


def test_upload_progress_picture_returns_url(test_client, client_auth_header, monkeypatch):
    calls = configure_mock_supabase(monkeypatch)
    files = {"file": ("progress.png", BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}

    resp = test_client.post("/roles/client/upload_progress_picture", files=files, headers=client_auth_header)
    assert resp.status_code == 200

    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("https://unit-test.supabase.co/storage/v1/object/public/progress_picture/")
    assert len(calls) == 1
    assert "/storage/v1/object/progress_picture/" in calls[0]["url"]
    assert calls[0]["headers"]["Content-Type"] == "image/png"
    assert calls[0]["timeout"] == 10


def test_upload_progress_picture_persists_daily_picture(test_client, client_auth_header, monkeypatch, db_session):
    configure_mock_supabase(monkeypatch)

    first = test_client.post(
        "/roles/client/upload_progress_picture",
        files={"file": ("progress-1.png", BytesIO(b"first"), "image/png")},
        headers=client_auth_header,
    )
    assert first.status_code == 200
    first_data = first.json()

    picture = db_session.get(DailyProgressPicture, first_data["id"])
    assert picture is not None
    assert picture.id == first_data["id"]
    assert picture.url == first_data["url"]

    telemetry = db_session.get(ClientTelemetry, picture.client_telemetry_id)
    assert telemetry is not None
    assert telemetry.telemetry_type == "progress_picture"

    second = test_client.post(
        "/roles/client/upload_progress_picture",
        files={"file": ("progress-2.png", BytesIO(b"second"), "image/png")},
        headers=client_auth_header,
    )
    assert second.status_code == 200

    db_session.refresh(picture)
    assert picture.url == second.json()["url"]
    assert picture.client_telemetry_id == first_data["client_telemetry_id"]


def test_update_pfp_updates_account(test_client, auth_header, monkeypatch):
    calls = configure_mock_supabase(monkeypatch)
    files = {"file": ("pfp.png", BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}

    resp = test_client.post("/roles/shared/account/update_pfp", files=files, headers=auth_header)
    assert resp.status_code == 200

    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("https://unit-test.supabase.co/storage/v1/object/public/profile_picture/")
    assert len(calls) == 1
    assert "/storage/v1/object/profile_picture/" in calls[0]["url"]

    me_resp = test_client.get("/me", headers=auth_header)
    assert me_resp.status_code == 200
    account = me_resp.json()
    assert account.get("pfp_url") == data["url"]
