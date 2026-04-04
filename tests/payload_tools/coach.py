def build_coach_request_payload(weekday="tuesday"):
    """
    Builds a mock payload for completing the coach registration request.
    """
    return {
        "availabilities": [
            {
                "weekday": weekday,
                "start_time": "18:00:00",
                "end_time": "20:00:00",
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
    }
