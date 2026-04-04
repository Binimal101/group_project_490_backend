from tests.payload_tools.coach import build_coach_request_payload

def test_coach_request_flow(test_client, client_auth_header):
    """
    Test applying for a Coach role. Uses client_auth_header, because creating a Coach Request 
    requires the user to already be a registered Client who completed an initial survey.
    """
    coach_request_payload = build_coach_request_payload()

    coach_request_response = test_client.post(
        "/roles/coach/request_coach_creation",
        json=coach_request_payload,
        headers=client_auth_header,
    )
    
    assert coach_request_response.status_code == 200
    coach_request_data = coach_request_response.json()
    assert "coach_id" in coach_request_data
    assert "coach_request_id" in coach_request_data

def test_coach_me_endpoint(test_client, coach_auth_header):
    """
    Test that a registered coach can fetch their coach profile details via the /me endpoint.
    """
    coach_me_response = test_client.post(
        "/roles/coach/me",
        headers=coach_auth_header,
    )
    
    assert coach_me_response.status_code == 200
    
    coach_me_data = coach_me_response.json()
    assert "@example.com" in coach_me_data["base_account"]["email"]
    assert isinstance(coach_me_data["coach_account"]["id"], int)