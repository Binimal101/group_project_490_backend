from datetime import date

from tests.payload_tools.constants import TEST_CARD_NUMBER


def make_client_profile(test_client, auth_header):
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
                "weekday": "monday",
                "start_time": "08:00:00",
                "end_time": "10:00:00"
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

    assert response.status_code == 404


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
