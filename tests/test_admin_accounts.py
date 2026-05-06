from sqlmodel import select

from src.database.account.models import Account
from tests.payload_tools.auth import build_signup_payload


def _signup_account(test_client, *, email_prefix, name):
    payload = build_signup_payload(email_prefix=email_prefix, name=name)
    response = test_client.post("/auth/signup", json=payload)
    assert response.status_code == 200
    return payload


def test_admin_can_query_accounts_sorted_by_name(test_client, admin_auth_header, db_session):
    _signup_account(test_client, email_prefix="z_account", name="Zoe Account")
    inactive_payload = _signup_account(test_client, email_prefix="a_account", name="Ari Account")

    inactive_account = db_session.exec(
        select(Account).where(Account.email == inactive_payload["email"])
    ).first()
    assert inactive_account is not None
    inactive_account.is_active = False
    db_session.add(inactive_account)
    db_session.commit()

    response = test_client.get(
        "/roles/admin/accounts?sort_by=name&sort_dir=asc&limit=1000",
        headers=admin_auth_header,
    )

    assert response.status_code == 200
    accounts = response.json()
    names = [account["name"] for account in accounts]
    assert names == sorted(names)

    ari = next(account for account in accounts if account["email"] == inactive_payload["email"])
    assert ari["name"] == "Ari Account"
    assert ari["status"] == "deactivated"
    assert ari["is_active"] is False
    assert ari["role"] == "client"
    assert ari["roles"] == ["client"]


def test_admin_can_query_accounts_sorted_by_email_desc(test_client, admin_auth_header):
    first = _signup_account(test_client, email_prefix="aaa_admin_sort", name="First Sort")
    second = _signup_account(test_client, email_prefix="zzz_admin_sort", name="Second Sort")

    response = test_client.get(
        "/roles/admin/accounts?sort_by=email&sort_dir=desc&limit=1000",
        headers=admin_auth_header,
    )

    assert response.status_code == 200
    accounts = [
        account
        for account in response.json()
        if account["email"] in {first["email"], second["email"]}
    ]
    assert [account["email"] for account in accounts] == sorted(
        [first["email"], second["email"]],
        reverse=True,
    )


def test_non_admin_cannot_query_accounts(test_client, auth_header):
    response = test_client.get("/roles/admin/accounts", headers=auth_header)

    assert response.status_code == 401
