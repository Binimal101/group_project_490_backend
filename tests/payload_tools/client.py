from datetime import date

def build_client_init_payload(goal="weight loss", weight=170, weekday="monday"):
    """
    Builds a mock payload for completing the initial client survey
    and creating a client role.
    """
    return {
        "fitness_goals": {"goal_enum": goal},
        "payment_information": {
            "ccnum": "4242424242424242",
            "cv": "123",
            "exp_date": str(date(2026, 12, 31)),
        },
        "availabilities": [
            {"weekday": weekday, "start_time": "08:00:00", "end_time": "10:00:00"}
        ],
        "initial_health_metric": { "weight": weight, "client_telemetry_id": 0 },
    }
