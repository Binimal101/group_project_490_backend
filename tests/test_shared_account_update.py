from tests.payload_tools.auth import build_update_account_payload


def test_shared_account_update(test_client, auth_header):
    payload = build_update_account_payload()

    resp = test_client.patch("/roles/shared/account/update", json=payload, headers=auth_header)
    assert resp.status_code == 200, resp.text

    account = resp.json()

    assert account["email"] == payload["email"]
    assert account["bio"] == payload["bio"]
    assert account["age"] == payload["age"]
    assert account["gender"] == payload["gender"]
    assert account["pfp_url"] == payload["pfp_url"]
