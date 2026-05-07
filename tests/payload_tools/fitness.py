def build_create_workout_payload(
    name: str = "Bicep Chiller",
    description: str = "A very intense bicep workout",
    instructions: str = "Lift the dumbbells",
    workout_type: str = "rep",
    equipment: list = [],
    intensity_measure: str = "weight",
    activity_tiers: list = None
):
    if activity_tiers is None:
        activity_tiers = [
            {"intensity_value": 50, "estimated_calories_per_unit_frequency": 2.5},
            {"intensity_value": 75, "estimated_calories_per_unit_frequency": 3.5},
            {"intensity_value": 100, "estimated_calories_per_unit_frequency": 4.5}
        ]
    return {
        "name": name,
        "description": description,
        "instructions": instructions,
        "workout_type": workout_type,
        "equipment": equipment,
        "intensity_measure": intensity_measure,
        "activity_tiers": activity_tiers
    }

def build_create_activity_payload(
    workout_id: int,
    intensity_measure: str = "weight",
    intensity_value: int = 50,
    estimated_calories_per_unit_frequency: float = 2.5
):
    return {
        "workout_id": workout_id,
        "intensity_measure": intensity_measure,
        "intensity_value": intensity_value,
        "estimated_calories_per_unit_frequency": estimated_calories_per_unit_frequency
    }

def build_create_plan_payload(
    workout_activity_id: int,
    strata_name: str = "Day 1: Arms",
    planned_reps: int = 12,
    planned_sets: int = 3,
    planned_duration: int = None
):
    activity_dict = {
        "workout_activity_id": workout_activity_id
    }
    if planned_reps is not None:
        activity_dict["planned_reps"] = planned_reps
    if planned_sets is not None:
        activity_dict["planned_sets"] = planned_sets
    if planned_duration is not None:
        activity_dict["planned_duration"] = planned_duration

    return {
        "strata_name": strata_name,
        "activities": [activity_dict]
    }
