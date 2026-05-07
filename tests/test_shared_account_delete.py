from sqlmodel import select

from src.database.account.models import Account
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.role_management.models import CoachRequest, RolePromotionResolution
from tests.payload_tools.coach import build_coach_request_payload


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


def test_delete_coach_account_removes_role_promotion_resolution(
    test_client,
    create_client,
    admin_auth_header,
    db_session,
):
    coach_header, _ = create_client(email_prefix="delete-approved-coach")

    coach_request_resp = test_client.post(
        "/roles/coach/request_coach_creation",
        json=build_coach_request_payload(),
        headers=coach_header,
    )
    assert coach_request_resp.status_code == 200, coach_request_resp.text
    coach_request_id = coach_request_resp.json()["coach_request_id"]

    resolve_resp = test_client.post(
        "/roles/admin/resolve_coach_request",
        json={"coach_request_id": coach_request_id, "is_approved": True},
        headers=admin_auth_header,
    )
    assert resolve_resp.status_code == 200, resolve_resp.text

    coach_request = db_session.get(CoachRequest, coach_request_id)
    assert coach_request is not None
    resolution_id = coach_request.role_promotion_resolution_id
    assert resolution_id is not None

    delete_resp = test_client.delete(
        "/roles/shared/account/delete",
        headers=coach_header,
    )
    assert delete_resp.status_code == 200, delete_resp.text

    db_session.expire_all()
    assert db_session.get(CoachRequest, coach_request_id) is None
    assert db_session.get(RolePromotionResolution, resolution_id) is None
