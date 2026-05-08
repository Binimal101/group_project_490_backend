from datetime import date, datetime, timedelta, timezone

from tests.payload_tools.constants import TEST_CARD_NUMBER


def make_client_profile(test_client, auth_header):
    start = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=0, hour=8) + timedelta(days=1)
    end = start + timedelta(hours=2)
    payload = {
        "fitness_goals": {
            "goal_enum": "weight loss"
        },
        "payment_information": {
            "ccnum": TEST_CARD_NUMBER,
            "cv": "123",
            "exp_date": str(date(date.today().year + 5, 12, 31))
        },
        "availabilities": [
            {
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
            }
        ],
        "initial_health_metric": {
            "weight": 180
        }
    }

    response = test_client.post(
        "/roles/client/initial_survey",
        json=payload,
        headers=auth_header
    )

    assert response.status_code == 200


def test_get_my_coach(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/my_coach",
        headers=auth_header
    )

    assert response.status_code == 200
    assert response.json()["coach"] is None


def test_get_coach_profile(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/coach_profile/999999",
        headers=auth_header
    )

    assert response.status_code == 404


def test_get_progress_pictures(test_client, auth_header):
    make_client_profile(test_client, auth_header)

    response = test_client.get(
        "/roles/client/progress_pictures",
        headers=auth_header
    )

    assert response.status_code == 200


def test_get_my_clients(test_client, coach_auth_header):
    response = test_client.get(
        "/roles/coach/my_clients",
        headers=coach_auth_header
    )

    assert response.status_code == 200
