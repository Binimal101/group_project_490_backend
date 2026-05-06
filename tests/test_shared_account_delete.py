from sqlmodel import select

from src.database.account.models import Account
from src.database.client.models import Client
from src.database.coach.models import Coach


def test_delete_base_account(test_client, auth_header, db_session):
    me_resp = test_client.get("/me", headers=auth_header)
    assert me_resp.status_code == 200
    account_id = me_resp.json()["id"]

    delete_resp = test_client.delete("/roles/shared/account/delete", headers=auth_header)
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json() == {
        "success": True,
        "message": "Account deleted successfully.",
    }

    assert db_session.get(Account, account_id) is None

    me_after_delete = test_client.get("/me", headers=auth_header)
    assert me_after_delete.status_code == 401


def test_delete_client_account_removes_client_role(test_client, client_auth_header, db_session):
    me_resp = test_client.get("/me", headers=client_auth_header)
    assert me_resp.status_code == 200
    account_id = me_resp.json()["id"]
    client_id = me_resp.json()["client_id"]

    delete_resp = test_client.delete("/roles/shared/account/delete", headers=client_auth_header)
    assert delete_resp.status_code == 200, delete_resp.text

    db_session.expire_all()
    assert db_session.get(Account, account_id) is None
    assert db_session.get(Client, client_id) is None


def test_delete_coach_account_removes_coach_role(test_client, coach_auth_header, db_session):
    coach_me_resp = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me_resp.status_code == 200
    account_id = coach_me_resp.json()["base_account"]["id"]
    coach_id = coach_me_resp.json()["coach_account"]["id"]

    delete_resp = test_client.delete("/roles/shared/account/delete", headers=coach_auth_header)
    assert delete_resp.status_code == 200, delete_resp.text

    db_session.expire_all()
    assert db_session.get(Account, account_id) is None
    assert db_session.get(Coach, coach_id) is None
    assert db_session.exec(select(Account).where(Account.coach_id == coach_id)).first() is None
