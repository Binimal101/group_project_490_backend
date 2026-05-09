from datetime import datetime, timedelta

from src.database.account.models import Account
from src.database.client.models import Client
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import ClientCoachRelationship, ClientCoachRequest
from src.database.payment.models import PricingInterval, PricingPlan
from src.database.reports.models import CoachReviews
from src.database.telemetry.models import ClientTelemetry, CompletedWorkout, CompletedWorkoutActivity, StepCount
from src.database.workouts_and_activities.models import Workout, WorkoutType


def test_public_platform_stats_aggregates_site_data(test_client, db_session):
    verified_coach = Coach(verified=True, specialties="Strength")
    unverified_coach = Coach(verified=False, specialties="Mobility")
    db_session.add(verified_coach)
    db_session.add(unverified_coach)
    db_session.commit()
    db_session.refresh(verified_coach)
    db_session.refresh(unverified_coach)

    review_client_one = Client()
    review_client_two = Client()
    db_session.add(review_client_one)
    db_session.add(review_client_two)
    db_session.commit()
    db_session.refresh(review_client_one)
    db_session.refresh(review_client_two)

    db_session.add(
        Account(
            name="Coach Mike",
            email="coach-mike@example.com",
            hashed_password="hashed",
            coach_id=verified_coach.id,
            is_active=True,
        )
    )
    db_session.add(
        Account(
            name="Inactive Coach",
            email="inactive-coach@example.com",
            hashed_password="hashed",
            coach_id=unverified_coach.id,
            is_active=False,
        )
    )
    db_session.add(
        Account(
            name="Active Client",
            email="active-client@example.com",
            hashed_password="hashed",
            is_active=True,
        )
    )
    db_session.add(
        Workout(
            name="Push Day",
            description="Upper body push",
            instructions="Press safely",
            workout_type=WorkoutType.REPETITION_BASED,
        )
    )
    db_session.add(
        Workout(
            name="Zone 2",
            description="Cardio base",
            instructions="Keep it steady",
            workout_type=WorkoutType.DURATION_BASED,
        )
    )
    db_session.add(
        CoachReviews(
            coach_id=verified_coach.id,
            client_id=review_client_one.id,
            rating=4.0,
            review_text="Great plan",
        )
    )
    db_session.add(
        CoachReviews(
            coach_id=verified_coach.id,
            client_id=review_client_two.id,
            rating=5.0,
            review_text="Excellent feedback",
        )
    )
    db_session.commit()

    response = test_client.get("/public/platform_stats")

    assert response.status_code == 200
    assert response.json() == {
        "preset_workouts": 2,
        "active_users": 2,
        "verified_coaches": 1,
        "average_coach_rating": 4.5,
    }


def _seed_client_with_account(db_session, name, email):
    client = Client()
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)

    account = Account(
        name=name,
        email=email,
        hashed_password="hashed",
        client_id=client.id,
        is_active=True,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return client, account


def _seed_verified_coach_with_account(db_session, name, email, *, specialties, created_at=None):
    coach = Coach(verified=True, specialties=specialties)
    db_session.add(coach)
    db_session.commit()
    db_session.refresh(coach)

    account = Account(
        name=name,
        email=email,
        hashed_password="hashed",
        coach_id=coach.id,
        is_active=True,
        created_at=created_at,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return coach, account


def test_public_client_leaderboards_use_real_telemetry(test_client, db_session):
    maya, _ = _seed_client_with_account(db_session, "Maya Stone", "maya@example.com")
    jordan, _ = _seed_client_with_account(db_session, "Jordan Vale", "jordan@example.com")

    maya_telemetry = ClientTelemetry(client_id=maya.id, telemetry_type="workout", date=datetime.utcnow())
    jordan_telemetry = ClientTelemetry(client_id=jordan.id, telemetry_type="workout", date=datetime.utcnow())
    db_session.add(maya_telemetry)
    db_session.add(jordan_telemetry)
    db_session.commit()
    db_session.refresh(maya_telemetry)
    db_session.refresh(jordan_telemetry)

    maya_workout = CompletedWorkoutActivity(estimated_calories=900)
    jordan_workout = CompletedWorkoutActivity(estimated_calories=450)
    db_session.add(maya_workout)
    db_session.add(jordan_workout)
    db_session.commit()
    db_session.refresh(maya_workout)
    db_session.refresh(jordan_workout)

    db_session.add(CompletedWorkout(completed_workout_details_id=maya_workout.id, client_telemetry_id=maya_telemetry.id))
    db_session.add(CompletedWorkout(completed_workout_details_id=jordan_workout.id, client_telemetry_id=jordan_telemetry.id))
    db_session.add(StepCount(client_telemetry_id=maya_telemetry.id, step_count=4000))
    db_session.add(StepCount(client_telemetry_id=jordan_telemetry.id, step_count=12000))
    db_session.add(ClientTelemetry(client_id=maya.id, telemetry_type="body_metrics", date=datetime.utcnow()))
    db_session.commit()

    burn_response = test_client.get("/public/leaderboards/clients/man-of-burn")
    steps_response = test_client.get("/public/leaderboards/clients/cardi-athletes")
    consistency_response = test_client.get("/public/leaderboards/clients/consistency-kings")

    assert burn_response.status_code == 200
    assert burn_response.json()["entries"][0]["name"] == "Maya Stone"
    assert burn_response.json()["entries"][0]["score"] == 900

    assert steps_response.status_code == 200
    assert steps_response.json()["entries"][0]["name"] == "Jordan Vale"
    assert steps_response.json()["entries"][0]["score"] == 12000

    assert consistency_response.status_code == 200
    assert consistency_response.json()["entries"][0]["name"] == "Maya Stone"
    assert consistency_response.json()["entries"][0]["score"] == 2


def test_public_coach_leaderboards_use_reviews_pricing_and_relationships(test_client, db_session):
    client_one, _ = _seed_client_with_account(db_session, "Client One", "client-one@example.com")
    client_two, _ = _seed_client_with_account(db_session, "Client Two", "client-two@example.com")
    client_three, _ = _seed_client_with_account(db_session, "Client Three", "client-three@example.com")

    value_coach, _ = _seed_verified_coach_with_account(
        db_session,
        "Value Coach",
        "value-coach@example.com",
        specialties="Strength",
        created_at=datetime.utcnow() - timedelta(days=100),
    )
    popular_coach, _ = _seed_verified_coach_with_account(
        db_session,
        "Popular Coach",
        "popular-coach@example.com",
        specialties="Powerlifting",
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    wise_coach, _ = _seed_verified_coach_with_account(
        db_session,
        "Wise Coach",
        "wise-coach@example.com",
        specialties="Endurance",
        created_at=datetime.utcnow() - timedelta(days=500),
    )

    db_session.add(PricingPlan(coach_id=value_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=5000))
    db_session.add(PricingPlan(coach_id=popular_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=20000))
    db_session.add(PricingPlan(coach_id=wise_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=10000))

    db_session.add(CoachReviews(coach_id=value_coach.id, client_id=client_one.id, rating=5.0, review_text="Great value"))
    db_session.add(CoachReviews(coach_id=popular_coach.id, client_id=client_one.id, rating=5.0, review_text="Great"))
    db_session.add(CoachReviews(coach_id=popular_coach.id, client_id=client_two.id, rating=5.0, review_text="Great"))
    db_session.add(CoachReviews(coach_id=popular_coach.id, client_id=client_three.id, rating=4.0, review_text="Good"))
    db_session.add(CoachReviews(coach_id=wise_coach.id, client_id=client_one.id, rating=4.0, review_text="Solid"))

    for client in [client_one, client_two]:
        request = ClientCoachRequest(client_id=client.id, coach_id=wise_coach.id, is_accepted=True)
        db_session.add(request)
        db_session.commit()
        db_session.refresh(request)
        db_session.add(
            ClientCoachRelationship(
                request_id=request.id,
                created_at=datetime.utcnow() - timedelta(days=25),
                is_active=True,
                coach_blocked=False,
                client_blocked=False,
            )
        )
    db_session.commit()

    mvp_response = test_client.get("/public/leaderboards/coaches/mvp")
    liked_response = test_client.get("/public/leaderboards/coaches/most-liked")
    wisest_response = test_client.get("/public/leaderboards/coaches/wisest")

    assert mvp_response.status_code == 200
    assert mvp_response.json()["entries"][0]["name"] == "Value Coach"

    assert liked_response.status_code == 200
    assert liked_response.json()["entries"][0]["display_score"] == "5.0"

    assert wisest_response.status_code == 200
    assert wisest_response.json()["entries"][0]["name"] == "Wise Coach"
    assert wisest_response.json()["entries"][0]["detail"] == "2 users, 25d avg retention"


def test_public_mvp_includes_rated_coaches_with_zero_monthly_rate(test_client, db_session):
    client, _ = _seed_client_with_account(db_session, "Client Four", "client-four@example.com")
    free_coach, _ = _seed_verified_coach_with_account(
        db_session,
        "Free Coach",
        "free-coach@example.com",
        specialties="Starter plans",
    )
    db_session.add(PricingPlan(coach_id=free_coach.id, payment_interval=PricingInterval.MONTHLY, price_cents=0))
    db_session.add(CoachReviews(coach_id=free_coach.id, client_id=client.id, rating=5.0, review_text="Helpful"))
    db_session.commit()

    response = test_client.get("/public/leaderboards/coaches/mvp")

    assert response.status_code == 200
    assert response.json()["entries"][0]["name"] == "Free Coach"
    assert response.json()["entries"][0]["display_score"] == "5.0"
    assert response.json()["entries"][0]["detail"] == "5.0 avg rating at $0/mo"
