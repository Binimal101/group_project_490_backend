from tests.payload_tools.auth import build_signup_payload, build_login_payload

def test_auth_flow(test_client):
    """
    Test the complete authentication lifecycle:
    1. Creating an account
    2. Signing in to get a JWT
    3. Fetching the /me endpoint using the JWT
    """
    signup_payload = build_signup_payload()
    
    # 1. Create account
    signup_res = test_client.post("/auth/signup", json=signup_payload)
    assert signup_res.status_code == 200
    
    # 2. Sign in
    login_res = test_client.post(
        "/auth/login", 
        json=build_login_payload(signup_payload["email"], signup_payload["password"])
    )
    assert login_res.status_code == 200
    
    token = login_res.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}
    
    # 3. Call /me endpoint
    me_res = test_client.get("/me", headers=auth_header)
    assert me_res.status_code == 200
    
    me_data = me_res.json()
    assert me_data["email"] == signup_payload["email"]
    assert "id" in me_data
