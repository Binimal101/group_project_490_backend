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

def build_update_coach_info_payload(weekday="wednesday"):
    """
    Builds a mock payload for updating coach information, which includes certifications, experiences, and availability.
    """
    return {
        "availabilities": [
            {
                "weekday": weekday,
                "start_time": "19:00:00",
                "end_time": "21:00:00",
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
    }
