def test_account_deactivate_and_activate(test_client, auth_header):
    # Deactivate account
    resp = test_client.post("/roles/shared/account/deactivate", headers=auth_header)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert "deactivated" in data["message"].lower()

    # Try to access a protected endpoint (should fail)
    resp2 = test_client.patch("/roles/shared/account/update", json={}, headers=auth_header)
    assert resp2.status_code in (400, 401)
    assert "inactive account" in resp2.text.lower()

    # Activate
    resp3 = test_client.post("/roles/shared/account/activate", headers=auth_header)
    assert resp3.status_code == 200, resp3.text
    data3 = resp3.json()
    assert data3["success"] is True
    assert "activated" in data3["message"].lower()

    # Should be able to access protected endpoint again
    resp4 = test_client.patch("/roles/shared/account/update", json={}, headers=auth_header)
    assert resp4.status_code == 200
