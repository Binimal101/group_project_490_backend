import random
from datetime import datetime, timedelta, timezone


def _next_weekday_dt(weekday_name: str, hour: int, minute: int = 0):
    days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    today = datetime.now(timezone.utc).replace(microsecond=0, second=0, minute=minute, hour=hour)
    delta = (days[weekday_name.lower()] - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)

def build_coach_request_payload(weekday="tuesday", payment_interval="monthly", price_cents=3000):
    """
    Builds a mock payload for completing the coach registration request.
    Includes pricing fields required by the current API contract.
    """
    start = _next_weekday_dt(weekday, 18)
    end = start + timedelta(hours=2)
    return {
        "availabilities": [
            {
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
            }
        ],
        "experiences": [
            {
                "experience_name": "Personal Trainer",
                "experience_title": "Senior Trainer",
                "experience_description": "Provided coaching services for 3 years.",
                "experience_start": "2020-01-01",
                "experience_end": "2023-01-01",
            }
        ],
        "certifications": [
            {
                "certification_name": "Certified Coach",
                "certification_title": "Level 1",
                "certification_description": "Basic coaching certification.",
                "certification_date": "2024-01-01",
                "certification_score": "A",
                "certification_organization": "Test Institute",
            }
        ],
        "payment_interval": payment_interval,
        "price_cents": price_cents,
    }

def build_update_coach_info_payload(weekday="wednesday"):
    """
    Builds a mock payload for updating coach information, which includes certifications, experiences, and availability.
    """
    start = _next_weekday_dt(weekday, 19)
    end = start + timedelta(hours=2)
    return {
        "availabilities": [
            {
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "repeats_weekly": True,
            }
        ],
        "experiences": [
            {
                "experience_name": "Group Fitness Instructor",
                "experience_title": "Lead Instructor",
                "experience_description": "Led group fitness classes for 2 years.",
                "experience_start": "2021-01-01",
                "experience_end": "2023-01-01",
            }
        ],
        "certifications": [
            {
                "certification_name": "Advanced Coaching Certificate",
                "certification_title": "Level 2",
                "certification_description": "Advanced coaching certification.",
                "certification_date": "2024-06-01",
                "certification_score": "A+",
                "certification_organization": "Test Institute",
            }
        ],
        "specialties": [random.choice(["Strength Training", "Cardio", "Flexibility", "Nutrition"]) for _ in range(random.randint(1, 3))],
    }
