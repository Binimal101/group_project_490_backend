from datetime import date, datetime, timedelta, timezone

from tests.payload_tools.constants import TEST_ALT_CARD_NUMBER


def _next_weekday_dt(weekday_name: str, hour: int, minute: int = 0):
    days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    today = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=minute, hour=hour)
    delta = (days[weekday_name.lower()] - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def build_client_init_payload(
    goal="weight loss",
    weight=170,
    weekday="monday",
    age=30,
    gender="non-binary",
    bio="Test bio",
    pfp_url="https://example.com/default-pfp.png",
):
    """
    Builds a mock payload for completing the initial client survey
    and creating a client role.
    """
    start = _next_weekday_dt(weekday, 8)
    end = start + timedelta(hours=2)
    return {
        "age": age,
        "gender": gender,
        "bio": bio,
        "pfp_url": pfp_url,
        "fitness_goals": {"goal_enum": goal},
        "payment_information": {
            "ccnum": TEST_ALT_CARD_NUMBER,
            "cv": "123",
            "exp_date": str(date(date.today().year + 5, 12, 31)),
        },
        "availabilities": [
            {
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
            }
        ],
        "initial_health_metric": { "weight": weight, "client_telemetry_id": 0 },
    }
