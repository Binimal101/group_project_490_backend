from tests.payload_tools.coach import build_coach_request_payload

def test_admin_query_and_resolve_coach_requests(test_client, admin_auth_header, client_auth_header):
    # Step 1: Client submits a coach request.
    coach_request_payload = build_coach_request_payload()

    coach_request_response = test_client.post(
        "/roles/coach/request_coach_creation",
        json=coach_request_payload,
        headers=client_auth_header,
    )
    assert coach_request_response.status_code == 200
    coach_request_id = coach_request_response.json()["coach_request_id"]

    # Step 2: Admin queries for unresolved coach requests.
    query_resp = test_client.get(
        "/roles/admin/query/coach_requests",
        headers=admin_auth_header
    )
    assert query_resp.status_code == 200
    requests = query_resp.json()
    assert len(requests) >= 1
    assert any(r["id"] == coach_request_id for r in requests)

    # Step 3: Admin resolves the coach request by approving it.
    resolve_payload = {
        "coach_request_id": coach_request_id,
        "is_approved": True
    }
    resolve_resp = test_client.post(
        "/roles/admin/resolve_coach_request",
        json=resolve_payload,
        headers=admin_auth_header
    )
    assert resolve_resp.status_code == 200
    resolve_data = resolve_resp.json()
    assert resolve_data["message"] == "Coach request resolved successfully"
    assert "resolution_id" in resolve_data

    # Step 4: Admin queries again, should not see the resolved request.
    query_resp_2 = test_client.get(
        "/roles/admin/query/coach_requests",
        headers=admin_auth_header
    )
    assert query_resp_2.status_code == 200
    requests_2 = query_resp_2.json()
    # verify the request is no longer returned
    assert not any(r["id"] == coach_request_id for r in requests_2)