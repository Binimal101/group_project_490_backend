"""Full demo-data seeder for the Fit app.

Creates:
- one admin account
- approved and pending coach accounts
- client accounts with onboarding-style profile details
- coach/client relationships, subscriptions, billing cycles, invoices
- coach-authored workout plans and meal prescriptions
- daily telemetry across the last 14 days
- reviews, reports, pending coach approvals, and chat history

Run from the repo root with:
    python -m src.scripts.seed.full_app_seed
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlmodel import Session, create_engine, select

from src.api.auth.services import hash_password
from src.database.account.models import Account, Availability
from src.database.admin.models import Admin
from src.database.client.models import Client, ClientAvailability, ClientWorkoutPlan, FitnessGoalEnum, FitnessGoals
from src.database.coach.models import (
    Coach,
    CoachAvailability,
    CoachCertifications,
    CoachExperience,
    Certifications,
    Experience,
)
from src.database.coach_client_relationship.models import (
    AccountChat,
    Chat,
    ChatMessage,
    ClientCoachRelationship,
    ClientCoachRequest,
)
from src.database.meal.models import ClientPrescribedMeal, Food, Meal, MealFood
from src.database.payment.models import (
    BillingCycle,
    PaymentInformation,
    PricingInterval,
    PricingPlan,
    Invoice,
    Subscription,
    SubscriptionStatus,
)
from src.database.reports.models import AccountReport, CoachReport, CoachReviews
from src.database.role_management.models import CoachRequest, RolePromotionResolution, Roles
from src.database.telemetry.models import (
    ClientTelemetry,
    CompletedMealActivity,
    CompletedSurvey,
    CompletedWorkout,
    CompletedWorkoutActivity,
    DailyBodyMetricsSurvey,
    DailyMealSurvey,
    DailyMoodSurvey,
    DailyProgressPicture,
    DailyStepsSurvey,
    DailyWorkoutSurvey,
    HealthMetrics,
    StepCount,
)
from src.database.workouts_and_activities.models import (
    PlanLibraryEntry,
    PlanLibrarySource,
    Workout,
    WorkoutActivity,
    WorkoutPlan,
    WorkoutPlanActivity,
    WorkoutType,
)


SEED_DOMAIN = "fitseed.local"
DEFAULT_PASSWORD = "SeedPass123!"
CARD_NUMBER = "5555555555554444"
UTC = timezone.utc


@dataclass(frozen=True)
class PersonSeed:
    slug: str
    name: str
    age: int
    gender: str
    bio: str
    pfp_url: str


def stable_int(value: str) -> int:
    return sum((idx + 1) * ord(ch) for idx, ch in enumerate(value))


COACHS: list[PersonSeed] = [
    PersonSeed(
        "morgan-lee",
        "Morgan Lee",
        34,
        "non-binary",
        "Strength and habit coach focused on sustainable training for busy professionals.",
        "https://i.pravatar.cc/300?img=12",
    ),
    PersonSeed(
        "daniela-rivera",
        "Daniela Rivera",
        38,
        "female",
        "Performance coach blending lifting, mobility, and nutrition for long-term progress.",
        "https://i.pravatar.cc/300?img=32",
    ),
    PersonSeed(
        "marcus-bennett",
        "Marcus Bennett",
        41,
        "male",
        "Former collegiate trainer specializing in fat loss, accountability, and athletic fundamentals.",
        "https://i.pravatar.cc/300?img=53",
    ),
    PersonSeed(
        "alina-patel",
        "Alina Patel",
        29,
        "female",
        "Online coach for beginners who want confidence in the gym and realistic meal structure.",
        "https://i.pravatar.cc/300?img=47",
    ),
    PersonSeed(
        "jonah-kim",
        "Jonah Kim",
        36,
        "male",
        "Hybrid training coach helping runners keep strength, structure, and recovery on track.",
        "https://i.pravatar.cc/300?img=19",
    ),
]

PENDING_COACHS: list[PersonSeed] = [
    PersonSeed(
        "sophia-carter",
        "Sophia Carter",
        31,
        "female",
        "New coach applicant with a background in community wellness and beginner programming.",
        "https://i.pravatar.cc/300?img=41",
    ),
    PersonSeed(
        "isaac-foster",
        "Isaac Foster",
        27,
        "male",
        "Aspiring coach focused on functional training and injury-aware programming.",
        "https://i.pravatar.cc/300?img=58",
    ),
    PersonSeed(
        "nina-brooks",
        "Nina Brooks",
        33,
        "female",
        "Coach applicant who works with postpartum recovery and foundational strength routines.",
        "https://i.pravatar.cc/300?img=25",
    ),
]

CLIENTS: list[PersonSeed] = [
    PersonSeed("maya-thompson", "Maya Thompson", 28, "female", "Training for energy, consistency, and feeling strong after work.", "https://i.pravatar.cc/300?img=4"),
    PersonSeed("owen-reed", "Owen Reed", 35, "male", "Wants to lose weight, stay active, and build a routine that lasts.", "https://i.pravatar.cc/300?img=16"),
    PersonSeed("hazel-nguyen", "Hazel Nguyen", 24, "female", "Focused on confidence, healthy habits, and getting stronger week by week.", "https://i.pravatar.cc/300?img=7"),
    PersonSeed("eli-watson", "Eli Watson", 43, "male", "Looking for structured coaching after years of inconsistent workouts.", "https://i.pravatar.cc/300?img=20"),
    PersonSeed("zoe-hughes", "Zoe Hughes", 30, "female", "Wants visible progress, meal structure, and guidance on recovery.", "https://i.pravatar.cc/300?img=29"),
    PersonSeed("caleb-ross", "Caleb Ross", 39, "male", "Balancing parenthood, work, and a goal to rebuild strength safely.", "https://i.pravatar.cc/300?img=14"),
    PersonSeed("lena-morris", "Lena Morris", 26, "female", "Training for body confidence and better day-to-day energy.", "https://i.pravatar.cc/300?img=45"),
    PersonSeed("devon-price", "Devon Price", 32, "non-binary", "Interested in mobility, posture, and a plan they can stick with.", "https://i.pravatar.cc/300?img=49"),
    PersonSeed("aria-mitchell", "Aria Mitchell", 37, "female", "Returning to fitness with a goal of fat loss and better endurance.", "https://i.pravatar.cc/300?img=35"),
    PersonSeed("noah-sullivan", "Noah Sullivan", 29, "male", "Trying to gain muscle while keeping food choices simple and repeatable.", "https://i.pravatar.cc/300?img=9"),
]


def choose_env() -> None:
    print("Choose target environment:")
    print("1) Testing (uses TESTING_DATABASE_URL)")
    print("2) Production (uses DATABASE_URL)")
    choice = input("Enter 1 or 2: ").strip()
    while choice not in ("1", "2"):
        choice = input("Please enter 1 or 2: ").strip()
    if choice == "1":
        os.environ["IS_TESTING"] = "true"
    else:
        os.environ.pop("IS_TESTING", None)


def seed_email(slug: str) -> str:
    return f"{slug}@{SEED_DOMAIN}"


def aware_dt(base_day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(base_day, time(hour=hour, minute=minute), tzinfo=UTC)


def ensure_admin_account(session: Session) -> Account:
    email = seed_email("platform-admin")
    account = session.exec(select(Account).where(Account.email == email)).first()
    if account is None:
        account = Account(
            name="Platform Admin",
            email=email,
            hashed_password=hash_password(DEFAULT_PASSWORD),
            age=42,
            gender="female",
            bio="Operations admin account seeded for moderation and approval flows.",
            pfp_url="https://i.pravatar.cc/300?img=63",
            created_at=datetime.utcnow() - timedelta(days=180),
        )
        session.add(account)
        session.flush()

    if account.admin_id is None:
        admin = Admin()
        session.add(admin)
        session.flush()
        account.admin_id = admin.id
        session.add(account)
        session.flush()

    return account


def ensure_payment_information(session: Session, slug: str) -> PaymentInformation:
    exp = date.today().replace(year=date.today().year + 4, month=12, day=31)
    cv = f"{(stable_int(slug) % 900) + 100}"
    existing = session.exec(
        select(PaymentInformation).where(
            PaymentInformation.ccnum == CARD_NUMBER,
            PaymentInformation.cv == cv,
        )
    ).first()
    if existing:
        return existing

    row = PaymentInformation(
        ccnum=CARD_NUMBER,
        cv=cv,
        exp_date=exp,
    )
    session.add(row)
    session.flush()
    return row


def ensure_client_role(
    session: Session,
    account: Account,
    slug: str,
    goal: FitnessGoalEnum,
    created_days_ago: int,
) -> Client:
    client = session.get(Client, account.client_id) if account.client_id is not None else None
    if client is None:
        client_availability = ClientAvailability()
        session.add(client_availability)
        session.flush()

        payment_info = ensure_payment_information(session, slug)
        client = Client(
            payment_information_id=payment_info.id,
            client_availability_id=client_availability.id,
            daily_step_goal=9000 + (stable_int(slug) % 3000),
            daily_calorie_goal=1900 + (stable_int(slug) % 500),
        )
        session.add(client)
        session.flush()
        account.client_id = client.id
        if account.created_at is None:
            account.created_at = datetime.utcnow() - timedelta(days=created_days_ago)
        session.add(account)
        session.flush()

    goal_row = session.exec(select(FitnessGoals).where(FitnessGoals.client_id == client.id)).first()
    if goal_row is None:
        session.add(FitnessGoals(client_id=client.id, goal_enum=goal))
        session.flush()

    return client


def ensure_account(
    session: Session,
    person: PersonSeed,
    created_days_ago: int,
    client_goal: FitnessGoalEnum,
) -> Account:
    account = session.exec(select(Account).where(Account.email == seed_email(person.slug))).first()
    if account is None:
        account = Account(
            name=person.name,
            email=seed_email(person.slug),
            hashed_password=hash_password(DEFAULT_PASSWORD),
            age=person.age,
            gender=person.gender,
            bio=person.bio,
            pfp_url=person.pfp_url,
            created_at=datetime.utcnow() - timedelta(days=created_days_ago),
        )
        session.add(account)
        session.flush()
    else:
        account.name = person.name
        account.age = person.age
        account.gender = person.gender
        account.bio = person.bio
        account.pfp_url = person.pfp_url
        session.add(account)

    ensure_client_role(session, account, person.slug, client_goal, created_days_ago)
    ensure_base_availability(session, account, person.slug)
    return account


def ensure_base_availability(session: Session, account: Account, slug: str) -> None:
    existing = session.exec(select(Availability).where(Availability.account_id == account.id)).all()
    if existing:
        return

    base = date.today() + timedelta(days=1)
    slots = [
        (base + timedelta(days=(stable_int(slug) % 3)), 6 + (stable_int(slug) % 3), 8 + (stable_int(slug) % 3)),
        (base + timedelta(days=3 + (stable_int(slug) % 2)), 17, 19),
    ]
    for day, start_hour, end_hour in slots:
        session.add(
            Availability(
                account_id=account.id,
                start_dt=aware_dt(day, start_hour),
                end_dt=aware_dt(day, end_hour),
                repeats_weekly=True,
                recurrence_end_dt=aware_dt(day + timedelta(weeks=10), end_hour),
                max_time_commitment_seconds=Decimal("7200.00"),
            )
        )
    session.flush()


def ensure_coach_profile(
    session: Session,
    account: Account,
    specialties: list[str],
    monthly_price_cents: int,
    created_days_ago: int,
    verified: bool,
    pending_only: bool,
    admin_account: Account,
) -> Coach:
    coach = session.get(Coach, account.coach_id) if account.coach_id is not None else None
    if coach is None:
        coach_availability = CoachAvailability()
        session.add(coach_availability)
        session.flush()

        coach = Coach(
            verified=verified,
            specialties=", ".join(specialties),
            coach_availability=coach_availability.id,
        )
        session.add(coach)
        session.flush()
        account.coach_id = coach.id
        session.add(account)
        session.flush()
    else:
        coach.specialties = ", ".join(specialties)
        coach.verified = verified
        session.add(coach)

    ensure_coach_credentials(session, coach, account.name, created_days_ago)
    ensure_pricing_plan(session, coach, PricingInterval.MONTHLY, monthly_price_cents, open_to_entry=True)
    ensure_pricing_plan(session, coach, PricingInterval.YEARLY, monthly_price_cents * 10, open_to_entry=False)
    ensure_coach_request(session, coach, account, verified, pending_only, admin_account)
    return coach


def ensure_coach_credentials(session: Session, coach: Coach, base_name: str, created_days_ago: int) -> None:
    existing_links = session.exec(select(CoachCertifications).where(CoachCertifications.coach_id == coach.id)).all()
    if not existing_links:
        certs = [
            Certifications(
                certification_name=f"{base_name} NASM CPT",
                certification_date=date.today() - timedelta(days=900 + created_days_ago),
                certification_score="Pass",
                certification_organization="NASM",
            ),
            Certifications(
                certification_name=f"{base_name} Nutrition Coaching",
                certification_date=date.today() - timedelta(days=500 + created_days_ago),
                certification_score="A",
                certification_organization="Precision Nutrition",
            ),
        ]
        for cert in certs:
            session.add(cert)
        session.flush()
        for cert in certs:
            session.add(CoachCertifications(coach_id=coach.id, certification_id=cert.id))

    existing_exp = session.exec(select(CoachExperience).where(CoachExperience.coach_id == coach.id)).all()
    if not existing_exp:
        experiences = [
            Experience(
                experience_name=f"{base_name} Coaching Studio",
                experience_title="Online Coach",
                experience_description="Guided adults through strength training, nutrition structure, and weekly accountability.",
                experience_start=date.today() - timedelta(days=1500 + created_days_ago),
                experience_end=None,
            ),
            Experience(
                experience_name="Peak Motion Athletics",
                experience_title="Assistant Performance Coach",
                experience_description="Built personalized strength progressions and recovery check-ins for mixed-level clients.",
                experience_start=date.today() - timedelta(days=2300 + created_days_ago),
                experience_end=date.today() - timedelta(days=1200 + created_days_ago),
            ),
        ]
        for exp in experiences:
            session.add(exp)
        session.flush()
        for exp in experiences:
            session.add(CoachExperience(coach_id=coach.id, experience_id=exp.id))
    session.flush()


def ensure_pricing_plan(
    session: Session,
    coach: Coach,
    interval: PricingInterval,
    price_cents: int,
    open_to_entry: bool,
) -> PricingPlan:
    row = session.exec(
        select(PricingPlan).where(
            PricingPlan.coach_id == coach.id,
            PricingPlan.payment_interval == interval,
            PricingPlan.price_cents == price_cents,
        )
    ).first()
    if row is None:
        row = PricingPlan(
            coach_id=coach.id,
            payment_interval=interval,
            price_cents=price_cents,
            open_to_entry=open_to_entry,
        )
        session.add(row)
        session.flush()
    else:
        row.open_to_entry = open_to_entry
        session.add(row)
    return row


def ensure_coach_request(
    session: Session,
    coach: Coach,
    account: Account,
    verified: bool,
    pending_only: bool,
    admin_account: Account,
) -> CoachRequest:
    row = session.exec(select(CoachRequest).where(CoachRequest.coach_id == coach.id)).first()
    if row is None:
        row = CoachRequest(coach_id=coach.id, created_on=datetime.utcnow() - timedelta(days=20))
        session.add(row)
        session.flush()

    if pending_only:
        row.role_promotion_resolution_id = None
        coach.verified = False
        session.add(row)
        session.add(coach)
        session.flush()
        return row

    if row.role_promotion_resolution_id is None:
        resolution = RolePromotionResolution(
            role=Roles.COACH,
            admin_id=admin_account.admin_id,
            account_id=account.id,
            is_approved=verified,
        )
        session.add(resolution)
        session.flush()
        row.role_promotion_resolution_id = resolution.id

    coach.verified = verified
    session.add(row)
    session.add(coach)
    session.flush()
    return row


def ensure_food(session: Session, name: str, calories: float, protein: float, carbs: float, fat: float) -> Food:
    row = session.exec(select(Food).where(Food.name == name)).first()
    if row is None:
        row = Food(
            name=name,
            calories_per_100g=calories,
            protein_g_per_100g=protein,
            carbs_g_per_100g=carbs,
            fat_g_per_100g=fat,
        )
        session.add(row)
        session.flush()
    return row


def ensure_meal(session: Session, coach_account: Account, meal_name: str, ingredients: list[tuple[Food, float]]) -> Meal:
    row = session.exec(
        select(Meal).where(
            Meal.created_by_account_id == coach_account.id,
            Meal.meal_name == meal_name,
        )
    ).first()
    if row is None:
        row = Meal(created_by_account_id=coach_account.id, meal_name=meal_name)
        session.add(row)
        session.flush()
        for food, grams in ingredients:
            session.add(MealFood(meal_id=row.id, food_id=food.id, grams=grams))
        session.flush()
    return row


def ensure_workout(session: Session, name: str, description: str, instructions: str) -> Workout:
    row = session.exec(select(Workout).where(Workout.name == name)).first()
    if row is None:
        row = Workout(
            name=name,
            description=description,
            instructions=instructions,
            workout_type=WorkoutType.REPETITION_BASED,
        )
        session.add(row)
        session.flush()
    return row


def ensure_workout_activity(session: Session, workout: Workout, intensity_value: int, calories: str) -> WorkoutActivity:
    row = session.exec(
        select(WorkoutActivity).where(
            WorkoutActivity.workout_id == workout.id,
            WorkoutActivity.intensity_measure == "difficulty",
            WorkoutActivity.intensity_value == intensity_value,
        )
    ).first()
    if row is None:
        row = WorkoutActivity(
            workout_id=workout.id,
            intensity_measure="difficulty",
            intensity_value=intensity_value,
            estimated_calories_per_unit_frequency=Decimal(calories),
        )
        session.add(row)
        session.flush()
    return row


def ensure_workout_plan(
    session: Session,
    coach_account: Account,
    plan_name: str,
    activities: Iterable[WorkoutActivity],
) -> WorkoutPlan:
    row = session.exec(
        select(WorkoutPlan).where(
            WorkoutPlan.created_by_account_id == coach_account.id,
            WorkoutPlan.strata_name == plan_name,
            WorkoutPlan.is_hidden == False,  # noqa: E712
        )
    ).first()
    if row is None:
        row = WorkoutPlan(
            strata_name=plan_name,
            is_public=False,
            created_by_account_id=coach_account.id,
            is_forked=False,
        )
        session.add(row)
        session.flush()
        for idx, activity in enumerate(activities, start=1):
            session.add(
                WorkoutPlanActivity(
                    workout_plan_id=row.id,
                    workout_activity_id=activity.id,
                    estimated_calories=Decimal("85.00") + Decimal(idx * 10),
                    modified_by_account_id=coach_account.id,
                    planned_reps=8 + idx * 2,
                    planned_sets=3,
                )
            )
        session.flush()
    return row


def ensure_relationship(
    session: Session,
    client_account: Account,
    coach_account: Account,
    accepted_days_ago: int,
) -> tuple[ClientCoachRequest, ClientCoachRelationship]:
    request = session.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_account.client_id,
            ClientCoachRequest.coach_id == coach_account.coach_id,
        )
    ).first()
    if request is None:
        request = ClientCoachRequest(
            client_id=client_account.client_id,
            coach_id=coach_account.coach_id,
            is_accepted=True,
            created_at=datetime.utcnow() - timedelta(days=accepted_days_ago),
        )
        session.add(request)
        session.flush()
    else:
        request.is_accepted = True
        session.add(request)

    relationship = session.exec(
        select(ClientCoachRelationship).where(ClientCoachRelationship.request_id == request.id)
    ).first()
    if relationship is None:
        relationship = ClientCoachRelationship(
            request_id=request.id,
            created_at=datetime.utcnow() - timedelta(days=accepted_days_ago),
            is_active=True,
        )
        session.add(relationship)
        session.flush()
    else:
        relationship.is_active = True
        session.add(relationship)

    ensure_chat_thread(session, client_account, coach_account)
    return request, relationship


def ensure_pending_relationship_request(session: Session, client_account: Account, coach_account: Account) -> None:
    row = session.exec(
        select(ClientCoachRequest).where(
            ClientCoachRequest.client_id == client_account.client_id,
            ClientCoachRequest.coach_id == coach_account.coach_id,
            ClientCoachRequest.is_accepted.is_(None),
        )
    ).first()
    if row is None:
        session.add(
            ClientCoachRequest(
                client_id=client_account.client_id,
                coach_id=coach_account.coach_id,
                is_accepted=None,
                created_at=datetime.utcnow() - timedelta(days=3),
            )
        )
        session.flush()


def ensure_chat_thread(session: Session, client_account: Account, coach_account: Account) -> None:
    existing = session.exec(
        select(AccountChat)
        .where(AccountChat.account_id == client_account.id)
    ).all()
    for join_row in existing:
        other = session.exec(
            select(AccountChat).where(
                AccountChat.chat_id == join_row.chat_id,
                AccountChat.account_id == coach_account.id,
            )
        ).first()
        if other:
            chat_id = join_row.chat_id
            if not session.exec(select(ChatMessage).where(ChatMessage.chat_id == chat_id)).first():
                seed_chat_messages(session, chat_id, client_account, coach_account)
            return

    chat = Chat()
    session.add(chat)
    session.flush()
    session.add(AccountChat(account_id=client_account.id, chat_id=chat.id))
    session.add(AccountChat(account_id=coach_account.id, chat_id=chat.id))
    session.flush()
    seed_chat_messages(session, chat.id, client_account, coach_account)


def seed_chat_messages(session: Session, chat_id: int, client_account: Account, coach_account: Account) -> None:
    messages = [
        (client_account.id, "I logged my meals and steps for today."),
        (coach_account.id, "Perfect. Your consistency is improving a lot this week."),
        (client_account.id, "Can we bump my squat volume next week?"),
        (coach_account.id, "Yes. I already adjusted your next plan block and recovery target."),
    ]
    for from_account_id, text in messages:
        session.add(
            ChatMessage(
                chat_id=chat_id,
                from_account_id=from_account_id,
                message_text=text,
                is_read=True,
            )
        )
    session.flush()


def ensure_subscription_bundle(
    session: Session,
    client_account: Account,
    coach_account: Account,
    monthly_price_cents: int,
) -> None:
    monthly_plan = session.exec(
        select(PricingPlan).where(
            PricingPlan.coach_id == coach_account.coach_id,
            PricingPlan.payment_interval == PricingInterval.MONTHLY,
            PricingPlan.open_to_entry == True,  # noqa: E712
        )
    ).first()
    if monthly_plan is None:
        monthly_plan = ensure_pricing_plan(
            session,
            session.get(Coach, coach_account.coach_id),
            PricingInterval.MONTHLY,
            monthly_price_cents,
            open_to_entry=True,
        )

    subscription = session.exec(
        select(Subscription).where(
            Subscription.client_id == client_account.client_id,
            Subscription.pricing_plan_id == monthly_plan.id,
        )
    ).first()
    if subscription is None:
        subscription = Subscription(
            client_id=client_account.client_id,
            pricing_plan_id=monthly_plan.id,
            status=SubscriptionStatus.ACTIVE,
            start_date=date.today() - timedelta(days=30),
        )
        session.add(subscription)
        session.flush()

    cycles = session.exec(
        select(BillingCycle).where(BillingCycle.subscription_id == subscription.id)
    ).all()
    if cycles:
        return

    previous_cycle = BillingCycle(
        active=False,
        entry_date=date.today() - timedelta(days=60),
        end_date=date.today() - timedelta(days=31),
        subscription_id=subscription.id,
        pricing_plan_id=monthly_plan.id,
    )
    current_cycle = BillingCycle(
        active=True,
        entry_date=date.today() - timedelta(days=30),
        end_date=date.today() + timedelta(days=1),
        subscription_id=subscription.id,
        pricing_plan_id=monthly_plan.id,
    )
    session.add(previous_cycle)
    session.add(current_cycle)
    session.flush()

    amount = float(monthly_plan.price_cents) / 100.0
    session.add(Invoice(billing_cycle_id=previous_cycle.id, client_id=client_account.client_id, amount=amount, outstanding_balance=0.0))
    session.add(Invoice(billing_cycle_id=current_cycle.id, client_id=client_account.client_id, amount=amount, outstanding_balance=0.0))
    session.flush()


def ensure_plan_library_entry(session: Session, client_account: Account, plan: WorkoutPlan, coach_account: Account) -> None:
    row = session.exec(
        select(PlanLibraryEntry).where(
            PlanLibraryEntry.account_id == client_account.id,
            PlanLibraryEntry.workout_plan_id == plan.id,
            PlanLibraryEntry.source == PlanLibrarySource.PRESCRIBED,
        )
    ).first()
    if row is None:
        session.add(
            PlanLibraryEntry(
                account_id=client_account.id,
                workout_plan_id=plan.id,
                source=PlanLibrarySource.PRESCRIBED,
                source_coach_account_id=coach_account.id,
            )
        )
        session.flush()


def ensure_client_workout_assignment(
    session: Session,
    client_account: Account,
    coach_account: Account,
    plan: WorkoutPlan,
    start_day_offset: int,
) -> None:
    start_day = date.today() + timedelta(days=start_day_offset)
    start_dt = aware_dt(start_day, 7)
    end_dt = aware_dt(start_day, 8)
    row = session.exec(
        select(ClientWorkoutPlan).where(
            ClientWorkoutPlan.client_id == client_account.client_id,
            ClientWorkoutPlan.workout_plan_id == plan.id,
            ClientWorkoutPlan.start_time == start_dt,
        )
    ).first()
    if row is None:
        session.add(
            ClientWorkoutPlan(
                client_id=client_account.client_id,
                workout_plan_id=plan.id,
                start_time=start_dt,
                end_time=end_dt,
                repeats_weekly=True,
                recurrence_end_dt=start_dt + timedelta(weeks=6),
            )
        )
        session.flush()
    ensure_plan_library_entry(session, client_account, plan, coach_account)


def ensure_prescribed_meals(
    session: Session,
    client_account: Account,
    coach_account: Account,
    meals: list[Meal],
) -> list[ClientPrescribedMeal]:
    scheduled: list[ClientPrescribedMeal] = []
    meal_kinds = ["breakfast", "lunch", "dinner"]
    for idx, meal in enumerate(meals):
        scheduled_date = date.today() + timedelta(days=idx)
        row = session.exec(
            select(ClientPrescribedMeal).where(
                ClientPrescribedMeal.client_id == client_account.client_id,
                ClientPrescribedMeal.prescribed_by_account_id == coach_account.id,
                ClientPrescribedMeal.meal_id == meal.id,
                ClientPrescribedMeal.scheduled_date == scheduled_date,
                ClientPrescribedMeal.meal_kind == meal_kinds[idx % len(meal_kinds)],
            )
        ).first()
        if row is None:
            row = ClientPrescribedMeal(
                meal_id=meal.id,
                client_id=client_account.client_id,
                prescribed_by_account_id=coach_account.id,
                scheduled_date=scheduled_date,
                meal_kind=meal_kinds[idx % len(meal_kinds)],
            )
            session.add(row)
            session.flush()
        scheduled.append(row)
    return scheduled


def ensure_daily_telemetry(
    session: Session,
    client_account: Account,
    workout_plan: WorkoutPlan,
    prescribed_meals: list[ClientPrescribedMeal],
) -> None:
    plan_activity = session.exec(
        select(WorkoutPlanActivity).where(WorkoutPlanActivity.workout_plan_id == workout_plan.id)
    ).first()
    if plan_activity is None:
        return

    for day_offset in range(14):
        day = date.today() - timedelta(days=day_offset)
        day_dt = aware_dt(day, 7 + (day_offset % 3))
        ensure_mood_telemetry(session, client_account, day_dt, day_offset)
        ensure_body_metrics_telemetry(session, client_account, day_dt + timedelta(minutes=15), day_offset)
        ensure_steps_telemetry(session, client_account, day_dt + timedelta(minutes=30), day_offset)
        ensure_progress_picture_telemetry(session, client_account, day_dt + timedelta(minutes=45), day_offset)
        if day_offset % 2 == 0:
            ensure_workout_telemetry(session, client_account, day_dt + timedelta(hours=1), day_offset, plan_activity)
            meal = prescribed_meals[day_offset % len(prescribed_meals)]
            ensure_meal_telemetry(session, client_account, day_dt + timedelta(hours=2), meal)


def telemetry_lookup(session: Session, client_id: int, telemetry_type: str, when: datetime) -> ClientTelemetry | None:
    return session.exec(
        select(ClientTelemetry).where(
            ClientTelemetry.client_id == client_id,
            ClientTelemetry.telemetry_type == telemetry_type,
            ClientTelemetry.date == when,
        )
    ).first()


def ensure_mood_telemetry(session: Session, client_account: Account, when: datetime, day_offset: int) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "mood", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="mood", date=when)
        session.add(telemetry)
        session.flush()
    survey = session.exec(select(DailyMoodSurvey).where(DailyMoodSurvey.client_telemetry_id == telemetry.id)).first()
    if survey is None:
        completed = CompletedSurvey(
            happiness_meter=max(4, 9 - (day_offset % 4)),
            alertness=max(4, 8 - (day_offset % 3)),
            healthiness=max(4, 9 - (day_offset % 5)),
            todays_goals=f"Stay on plan, finish my walk, and hit my protein target for day {14 - day_offset}.",
            todays_appreciation=f"Grateful for steady progress, supportive coaching, and better energy on day {14 - day_offset}.",
        )
        session.add(completed)
        session.flush()
        session.add(
            DailyMoodSurvey(
                is_seen=True,
                is_started=True,
                is_finished=True,
                completed_survey_id=completed.id,
                client_telemetry_id=telemetry.id,
            )
        )
        session.flush()


def ensure_body_metrics_telemetry(session: Session, client_account: Account, when: datetime, day_offset: int) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "body_metrics", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="body_metrics", date=when)
        session.add(telemetry)
        session.flush()
    survey = session.exec(select(DailyBodyMetricsSurvey).where(DailyBodyMetricsSurvey.client_telemetry_id == telemetry.id)).first()
    if survey is None:
        metrics = HealthMetrics(weight=max(125, 190 - day_offset), client_telemetry_id=telemetry.id)
        session.add(metrics)
        session.flush()
        session.add(
            DailyBodyMetricsSurvey(
                is_seen=True,
                is_started=True,
                is_finished=True,
                completed_health_metrics_id=metrics.id,
                client_telemetry_id=telemetry.id,
            )
        )
        session.flush()


def ensure_steps_telemetry(session: Session, client_account: Account, when: datetime, day_offset: int) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "steps", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="steps", date=when)
        session.add(telemetry)
        session.flush()
    survey = session.exec(select(DailyStepsSurvey).where(DailyStepsSurvey.client_telemetry_id == telemetry.id)).first()
    if survey is None:
        steps = StepCount(client_telemetry_id=telemetry.id, step_count=7200 + day_offset * 380)
        session.add(steps)
        session.flush()
        session.add(
            DailyStepsSurvey(
                is_seen=True,
                is_started=True,
                is_finished=True,
                step_count_id=steps.id,
                client_telemetry_id=telemetry.id,
            )
        )
        session.flush()


def ensure_progress_picture_telemetry(session: Session, client_account: Account, when: datetime, day_offset: int) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "progress_picture", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="progress_picture", date=when)
        session.add(telemetry)
        session.flush()
    picture = session.exec(select(DailyProgressPicture).where(DailyProgressPicture.client_telemetry_id == telemetry.id)).first()
    if picture is None:
        session.add(
            DailyProgressPicture(
                client_telemetry_id=telemetry.id,
                url=f"https://picsum.photos/seed/{client_account.id}-{day_offset}/600/800",
            )
        )
        session.flush()


def ensure_workout_telemetry(
    session: Session,
    client_account: Account,
    when: datetime,
    day_offset: int,
    plan_activity: WorkoutPlanActivity,
) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "workout", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="workout", date=when)
        session.add(telemetry)
        session.flush()
    survey = session.exec(select(DailyWorkoutSurvey).where(DailyWorkoutSurvey.client_telemetry_id == telemetry.id)).first()
    if survey is None:
        details = CompletedWorkoutActivity(
            completed_reps=plan_activity.planned_reps,
            completed_sets=plan_activity.planned_sets,
            estimated_calories=260 + day_offset * 5,
        )
        session.add(details)
        session.flush()
        completed = CompletedWorkout(
            workout_plan_activity_id=plan_activity.id,
            completed_workout_details_id=details.id,
            client_telemetry_id=telemetry.id,
        )
        session.add(completed)
        session.flush()
        session.add(
            DailyWorkoutSurvey(
                is_seen=True,
                is_started=True,
                is_finished=True,
                completed_workout_id=completed.id,
                client_telemetry_id=telemetry.id,
            )
        )
        session.flush()


def ensure_meal_telemetry(session: Session, client_account: Account, when: datetime, prescribed_meal: ClientPrescribedMeal) -> None:
    telemetry = telemetry_lookup(session, client_account.client_id, "meal", when)
    if telemetry is None:
        telemetry = ClientTelemetry(client_id=client_account.client_id, telemetry_type="meal", date=when)
        session.add(telemetry)
        session.flush()
    survey = session.exec(select(DailyMealSurvey).where(DailyMealSurvey.client_telemetry_id == telemetry.id)).first()
    if survey is None:
        completed = CompletedMealActivity(
            client_prescribed_meal_id=prescribed_meal.id,
            client_telemetry_id=telemetry.id,
            meal_kind=prescribed_meal.meal_kind,
        )
        session.add(completed)
        session.flush()
        session.add(
            DailyMealSurvey(
                is_seen=True,
                is_started=True,
                is_finished=True,
                completed_meal_activity_id=completed.id,
                client_telemetry_id=telemetry.id,
            )
        )
        session.flush()


def ensure_review(session: Session, client_account: Account, coach_account: Account, rating: float, review_text: str) -> None:
    row = session.exec(
        select(CoachReviews).where(
            CoachReviews.client_id == client_account.client_id,
            CoachReviews.coach_id == coach_account.coach_id,
            CoachReviews.review_text == review_text,
        )
    ).first()
    if row is None:
        session.add(
            CoachReviews(
                client_id=client_account.client_id,
                coach_id=coach_account.coach_id,
                rating=rating,
                review_text=review_text,
            )
        )
        session.flush()


def ensure_report(session: Session, client_account: Account, coach_account: Account, reason: str) -> None:
    row = session.exec(
        select(AccountReport).where(
            AccountReport.reporter_id == client_account.id,
            AccountReport.reportee_id == coach_account.id,
            AccountReport.reason == reason,
        )
    ).first()
    if row is None:
        session.add(AccountReport(reporter_id=client_account.id, reportee_id=coach_account.id, reason=reason))
        session.flush()

    legacy = session.exec(
        select(CoachReport).where(
            CoachReport.client_id == client_account.client_id,
            CoachReport.coach_id == coach_account.coach_id,
            CoachReport.report_summary == reason,
        )
    ).first()
    if legacy is None:
        session.add(CoachReport(client_id=client_account.client_id, coach_id=coach_account.coach_id, report_summary=reason))
        session.flush()


def seed_demo_data(session: Session) -> None:
    admin_account = ensure_admin_account(session)

    coach_accounts: dict[str, Account] = {}
    monthly_prices = [14900, 17900, 15900, 12900, 18900]
    specialties = [
        ["strength training", "habit coaching"],
        ["nutrition", "body recomposition"],
        ["athletic performance", "fat loss"],
        ["beginner training", "mobility"],
        ["hybrid conditioning", "recovery"],
    ]
    goals = [
        FitnessGoalEnum.MUSCLE_GAIN,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.MAINTENENCE,
        FitnessGoalEnum.MUSCLE_GAIN,
    ]

    for idx, person in enumerate(COACHS):
        account = ensure_account(session, person, created_days_ago=160 - idx * 11, client_goal=goals[idx])
        ensure_coach_profile(
            session,
            account,
            specialties=specialties[idx],
            monthly_price_cents=monthly_prices[idx],
            created_days_ago=150 - idx * 10,
            verified=True,
            pending_only=False,
            admin_account=admin_account,
        )
        coach_accounts[person.slug] = account

    for idx, person in enumerate(PENDING_COACHS):
        account = ensure_account(session, person, created_days_ago=40 - idx * 5, client_goal=FitnessGoalEnum.MAINTENENCE)
        ensure_coach_profile(
            session,
            account,
            specialties=["beginner coaching", "online accountability"],
            monthly_price_cents=11900 + idx * 1000,
            created_days_ago=30 - idx * 4,
            verified=False,
            pending_only=True,
            admin_account=admin_account,
        )

    client_accounts: dict[str, Account] = {}
    client_goals = [
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.MUSCLE_GAIN,
        FitnessGoalEnum.MAINTENENCE,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.MUSCLE_GAIN,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.MAINTENENCE,
        FitnessGoalEnum.WEIGHT_LOSS,
        FitnessGoalEnum.MUSCLE_GAIN,
    ]
    for idx, person in enumerate(CLIENTS):
        client_accounts[person.slug] = ensure_account(
            session,
            person,
            created_days_ago=110 - idx * 7,
            client_goal=client_goals[idx],
        )

    chicken = ensure_food(session, "Chicken Breast", 165.0, 31.0, 0.0, 3.6)
    rice = ensure_food(session, "Cooked Jasmine Rice", 130.0, 2.7, 28.0, 0.3)
    broccoli = ensure_food(session, "Broccoli", 35.0, 2.4, 7.0, 0.4)
    greek_yogurt = ensure_food(session, "Greek Yogurt", 97.0, 9.0, 3.9, 5.0)
    berries = ensure_food(session, "Mixed Berries", 57.0, 0.7, 14.0, 0.3)
    oats = ensure_food(session, "Rolled Oats", 389.0, 17.0, 66.0, 7.0)

    squat = ensure_workout(session, "Goblet Squat", "Lower-body strength builder.", "Keep chest tall, brace, and drive through mid-foot.")
    pushup = ensure_workout(session, "Incline Push-Up", "Upper-body pressing movement for strength and control.", "Keep ribs tucked and move in one line.")
    deadbug = ensure_workout(session, "Dead Bug", "Core stability drill for control and breathing.", "Move slowly and keep low back planted.")

    squat_activity = ensure_workout_activity(session, squat, 2, "9.500000")
    pushup_activity = ensure_workout_activity(session, pushup, 2, "7.250000")
    deadbug_activity = ensure_workout_activity(session, deadbug, 1, "4.500000")

    assignments = [
        ("maya-thompson", "morgan-lee"),
        ("owen-reed", "daniela-rivera"),
        ("hazel-nguyen", "alina-patel"),
        ("eli-watson", "marcus-bennett"),
        ("zoe-hughes", "morgan-lee"),
        ("caleb-ross", "jonah-kim"),
        ("lena-morris", "daniela-rivera"),
        ("devon-price", "alina-patel"),
    ]

    for idx, (client_slug, coach_slug) in enumerate(assignments):
        client_account = client_accounts[client_slug]
        coach_account = coach_accounts[coach_slug]
        ensure_relationship(session, client_account, coach_account, accepted_days_ago=28 - idx)

        monthly_plan = session.exec(
            select(PricingPlan).where(
                PricingPlan.coach_id == coach_account.coach_id,
                PricingPlan.payment_interval == PricingInterval.MONTHLY,
                PricingPlan.open_to_entry == True,  # noqa: E712
            )
        ).first()
        ensure_subscription_bundle(session, client_account, coach_account, monthly_plan.price_cents if monthly_plan else 14900)

        workout_plan = ensure_workout_plan(
            session,
            coach_account,
            f"{coach_account.name.split()[0]} Momentum Plan",
            [squat_activity, pushup_activity, deadbug_activity],
        )
        ensure_client_workout_assignment(session, client_account, coach_account, workout_plan, start_day_offset=(idx % 4) + 1)

        breakfast = ensure_meal(session, coach_account, f"{coach_account.name.split()[0]} Protein Oats", [(oats, 60.0), (greek_yogurt, 150.0), (berries, 80.0)])
        lunch = ensure_meal(session, coach_account, f"{coach_account.name.split()[0]} Chicken Bowl", [(chicken, 170.0), (rice, 180.0), (broccoli, 120.0)])
        dinner = ensure_meal(session, coach_account, f"{coach_account.name.split()[0]} Recovery Plate", [(chicken, 150.0), (rice, 140.0), (broccoli, 140.0)])
        prescribed_meals = ensure_prescribed_meals(session, client_account, coach_account, [breakfast, lunch, dinner])

        ensure_daily_telemetry(session, client_account, workout_plan, prescribed_meals)

    pending_pairs = [
        ("aria-mitchell", "jonah-kim"),
        ("noah-sullivan", "marcus-bennett"),
    ]
    for client_slug, coach_slug in pending_pairs:
        ensure_pending_relationship_request(session, client_accounts[client_slug], coach_accounts[coach_slug])

    reviews = [
        ("maya-thompson", "morgan-lee", 5.0, "Morgan keeps the plan realistic and actually checks in."),
        ("zoe-hughes", "morgan-lee", 4.5, "Strong communication and great adjustments around travel."),
        ("owen-reed", "daniela-rivera", 5.0, "Daniela made nutrition feel manageable instead of overwhelming."),
        ("lena-morris", "daniela-rivera", 4.8, "I feel more confident in the gym after every check-in."),
        ("hazel-nguyen", "alina-patel", 4.7, "The workouts fit my schedule and still feel challenging."),
        ("devon-price", "alina-patel", 4.9, "Thoughtful coaching and clear weekly feedback."),
        ("eli-watson", "marcus-bennett", 4.6, "Marcus is direct, helpful, and keeps me consistent."),
        ("caleb-ross", "jonah-kim", 4.8, "Jonah balances structure and flexibility really well."),
    ]
    for client_slug, coach_slug, rating, text in reviews:
        ensure_review(session, client_accounts[client_slug], coach_accounts[coach_slug], rating, text)

    reports = [
        ("maya-thompson", "marcus-bennett", "Coach missed two agreed check-ins and the client wanted admin review."),
        ("owen-reed", "jonah-kim", "Client reported delayed responses during an active billing cycle."),
        ("hazel-nguyen", "morgan-lee", "Client reported confusion around a plan update and wanted moderation visibility."),
        ("lena-morris", "daniela-rivera", "Client flagged an overly abrupt tone in weekly feedback."),
        ("devon-price", "alina-patel", "Client requested admin review of a scheduling dispute."),
    ]
    for client_slug, coach_slug, reason in reports:
        ensure_report(session, client_accounts[client_slug], coach_accounts[coach_slug], reason)


def summarize(session: Session) -> None:
    account_count = session.exec(select(Account)).all()
    coach_request_count = session.exec(select(CoachRequest).where(CoachRequest.role_promotion_resolution_id == None)).all()
    invoice_count = session.exec(select(Invoice)).all()
    telemetry_count = session.exec(select(ClientTelemetry)).all()
    review_count = session.exec(select(CoachReviews)).all()
    report_count = session.exec(select(AccountReport)).all()
    relationship_count = session.exec(select(ClientCoachRelationship).where(ClientCoachRelationship.is_active == True)).all()  # noqa: E712
    print(
        "Seed complete: "
        f"{len(account_count)} accounts, "
        f"{len(relationship_count)} active relationships, "
        f"{len(invoice_count)} invoices, "
        f"{len(telemetry_count)} telemetry rows, "
        f"{len(review_count)} reviews, "
        f"{len(report_count)} account reports, "
        f"{len(coach_request_count)} pending coach approvals."
    )


def main() -> None:
    choose_env()
    from src import config

    engine = create_engine(config.DATABASE_URL, echo=False)
    with Session(engine) as session:
        seed_demo_data(session)
        session.commit()
        summarize(session)


if __name__ == "__main__":
    main()
