from tests.payload_tools.auth import build_signup_payload, build_login_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload


def _create_and_login(test_client, signup_payload):
    test_client.post("/auth/signup", json=signup_payload)
    login_resp = test_client.post("/auth/login", json=build_login_payload(signup_payload["email"], signup_payload["password"]))
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_client_requests_list_format_and_contains(test_client, coach_auth_header):
    # create a fresh client user and promote to client
    signup = build_signup_payload(email_prefix="client")
    client_header = _create_and_login(test_client, signup)

    init_payload = build_client_init_payload()
    init_resp = test_client.post("/roles/client/initial_survey", json=init_payload, headers=client_header)
    assert init_resp.status_code == 200
    client_id = init_resp.json()["client_id"]

    # get coach id for the coach fixture
    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    assert coach_me.status_code == 200
    coach_id = coach_me.json()["coach_account"]["id"]

    # create a client -> coach request
    req_resp = test_client.post(f"/roles/client/request_coach/{coach_id}", headers=client_header)
    assert req_resp.status_code == 200
    request_id = req_resp.json()["request_id"]

    # coach should see the pending request as a list of objects keyed by client_id+request_id.
    # The endpoint enriches each entry with name/age/gender/pfp_url/goal for dashboard
    # display, so we match on the identifying fields rather than exact dict equality.
    list_resp = test_client.get("/roles/coach/client_requests", headers=coach_auth_header)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert isinstance(items, list)
    match = next(
        (i for i in items if i.get("client_id") == client_id and i.get("request_id") == request_id),
        None,
    )
    assert match is not None, f"expected request {request_id} for client {client_id} in {items}"


def test_lookup_client_pending_request_returns_details(test_client, coach_auth_header):
    # create client and a pending request
    signup = build_signup_payload(email_prefix="client_lookup")
    client_header = _create_and_login(test_client, signup)

    init_payload = build_client_init_payload(weekday="wednesday")
    init_resp = test_client.post("/roles/client/initial_survey", json=init_payload, headers=client_header)
    assert init_resp.status_code == 200
    client_id = init_resp.json()["client_id"]

    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    coach_id = coach_me.json()["coach_account"]["id"]

    req_resp = test_client.post(f"/roles/client/request_coach/{coach_id}", headers=client_header)
    assert req_resp.status_code == 200

    # lookup by the (potential) contracted coach
    lookup_resp = test_client.get(f"/roles/coach/lookup_client/{client_id}", headers=coach_auth_header)
    assert lookup_resp.status_code == 200
    data = lookup_resp.json()

    assert "base_account" in data
    assert data["base_account"]["email"] == signup["email"]
    assert "hashed_password" not in data["base_account"]

    assert "client_account" in data and data["client_account"]["id"] == client_id
    assert "availabilities" in data and isinstance(data["availabilities"], list)
    assert data["availabilities"][0]["weekday"] == init_payload["availabilities"][0]["weekday"]
    assert "fitness_goals" in data


def test_lookup_client_forbidden_for_unrelated_verified_coach(test_client, coach_auth_header, admin_auth_header):
    # create a client and a pending request to the first coach
    signup = build_signup_payload(email_prefix="client_x")
    client_header = _create_and_login(test_client, signup)
    init_payload = build_client_init_payload()
    resp = test_client.post("/roles/client/initial_survey", json=init_payload, headers=client_header)
    assert resp.status_code == 200
    client_id = resp.json()["client_id"]

    coach_me = test_client.post("/roles/coach/me", headers=coach_auth_header)
    coach_id = coach_me.json()["coach_account"]["id"]

    create_req = test_client.post(f"/roles/client/request_coach/{coach_id}", headers=client_header)
    assert create_req.status_code == 200

    # create another coach and verify them via admin so they're a verified but unrelated coach
    signup2 = build_signup_payload(email_prefix="othercoach")
    other_header = _create_and_login(test_client, signup2)

    # promote to client and request coach creation
    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=other_header)
    create_coach_resp = test_client.post("/roles/coach/request_coach_creation", json=build_coach_request_payload(), headers=other_header)
    assert create_coach_resp.status_code == 200
    coach_request_id = create_coach_resp.json()["coach_request_id"]

    # admin approves the other coach
    approve_resp = test_client.post("/roles/admin/resolve_coach_request", json={"coach_request_id": coach_request_id, "is_approved": True}, headers=admin_auth_header)
    assert approve_resp.status_code == 200

    # other verified coach should NOT be authorized to lookup our client
    other_me = test_client.post("/roles/coach/me", headers=other_header)
    assert other_me.status_code == 200

    lookup_resp = test_client.get(f"/roles/coach/lookup_client/{client_id}", headers=other_header)
    assert lookup_resp.status_code == 403
