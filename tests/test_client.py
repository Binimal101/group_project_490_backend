from datetime import date
from sqlmodel import Session
from tests.payload_tools.client import build_client_init_payload

def test_client_survey_flow(test_client, auth_header):
    """
    Test creating a Client profile on top of an authenticated base User account.
    """
    client_init_payload = build_client_init_payload()

    client_survey_response = test_client.post(
        "/roles/client/initial_survey",
        json=client_init_payload,
        headers=auth_header,
    )
    
    assert client_survey_response.status_code == 200
    client_survey_data = client_survey_response.json()
    assert "client_id" in client_survey_data
    assert isinstance(client_survey_data["client_id"], int)

def test_client_me_endpoint(test_client, client_auth_header):
    """
    Test that a registered client can fetch their client profile details via the /me endpoint.
    """
    client_me_response = test_client.post(
        "/roles/client/me",
        headers=client_auth_header,
    )
    assert client_me_response.status_code == 200
    
    client_me_data = client_me_response.json()
    assert "@example.com" in client_me_data["base_account"]["email"]
    assert isinstance(client_me_data["client_account"]["id"], int)
