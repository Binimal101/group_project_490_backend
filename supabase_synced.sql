CREATE SCHEMA IF NOT EXISTS "public";

CREATE TABLE "public"."billing_cycle" (
    "id" bigint NOT NULL,
    "active" boolean NOT NULL,
    "entry_date" date NOT NULL,
    "pricing_plan_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_23_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."pricing_plan" (
    "id" bigint NOT NULL,
    "payment_interval" text NOT NULL,
    "payment_amount" decimal(5, 2) NOT NULL,
    "open_to_entry" boolean NOT NULL,
    "coach_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_24_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_coach_relationship" (
    "id" bigint NOT NULL,
    "request_id" bigint NOT NULL,
    "created_at" timestamptz NOT NULL,
    "is_active" boolean NOT NULL,
    "coach_blocked" boolean NOT NULL,
    "client_blocked" boolean NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_19_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_report" (
    "id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "report_summary" text NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_17_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."admin" (
    "id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_admin_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."role_promotion_resolution" (
    "id" bigint NOT NULL,
    "admin_id" bigint NOT NULL,
    "account_id" bigint NOT NULL,
    "role" TEXT NOT NULL,
    "is_approved" boolean NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_role_promotion_resolution_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."invoice" (
    "id" bigint NOT NULL,
    "amount" decimal(5, 2) NOT NULL,
    "billing_cycle_id" bigint NOT NULL,
    "outstanding_balance" decimal(5, 2) NOT NULL,
    "client_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_22_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach" (
    "id" bigint NOT NULL,
    "verified" boolean NOT NULL,
    "coach_availability" bigint,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_coach_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."chat_message" (
    "id" bigint NOT NULL,
    "chat_id" bigint NOT NULL,
    "from_account_id" bigint NOT NULL,
    "is_read" boolean NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_21_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."experience" (
    "id" bigint NOT NULL,
    "experience_name" text NOT NULL,
    "experience_title" varchar(255) NOT NULL,
    "experience_description" text NOT NULL,
    "experience_start" date NOT NULL,
    "experience_end" date,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_experience_id" PRIMARY KEY ("id")
);
-- Indexes
CREATE INDEX "experience_experience_id_index" ON "public"."experience" ("id");

CREATE TABLE "public"."coach_certifications" (
    "id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "certification_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_coach_certifications_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach_experience" (
    "id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "experience_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_coach_experience_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."certifications" (
    "id" bigint NOT NULL,
    "certification_name" text NOT NULL,
    "certification_date" date NOT NULL,
    "certification_score" text,
    "certification_organization" text NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_certifications_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach_report" (
    "id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "report_summary" text NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_16_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_coach_request" (
    "id" bigint NOT NULL,
    "created_at" timestamptz NOT NULL,
    "is_accepted" boolean,
    "client_id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_18_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client" (
    "id" bigint NOT NULL,
    "payment_information_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    "client_availability_id" bigint NOT NULL,
    CONSTRAINT "pk_client_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."account" (
    "id" bigint NOT NULL,
    "coach_id" bigint,
    "client_id" bigint,
    "admin_id" bigint,
    "pfp_url" text,
    "bio" text,
    "age" int NOT NULL,
    "gender" text NOT NULL,
    "name" text NOT NULL,
    "email" text NOT NULL,
    "hashed_password" text,
    "gcp_user_id" text,
    "created_at" timestamptz NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_account_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."chat" (
    "id" bigint NOT NULL,
    "client_coach_relationship_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_20_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach_request" (
    "id" bigint NOT NULL,
    "coach_id" bigint NOT NULL,
    "created_on" timestamptz NOT NULL,
    "role_promotion_resolution_id" bigint,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_coach_request_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."payment_information" (
    "id" bigint NOT NULL,
    "ccnum" text NOT NULL,
    "cv" varchar(16) NOT NULL,
    "exp_date" date NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_payment_information_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach_reviews" (
    "id" bigint NOT NULL,
    "rating" float NOT NULL,
    "review_text" text NOT NULL,
    "coach_id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_coach_reviews_id" PRIMARY KEY ("id")
);
-- Indexes
CREATE INDEX "coach_reviews_coach_reviews_coach_id_index" ON "public"."coach_reviews" ("coach_id");
CREATE INDEX "coach_reviews_coach_reviews_client_id_index" ON "public"."coach_reviews" ("client_id");
CREATE INDEX "coach_reviews_coach_reviews_coach_id_client_id_index" ON "public"."coach_reviews" ("coach_id", "client_id");

CREATE TABLE "public"."fitness_goals" (
    "id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "goal_enum" varchar(255) NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_fitness_goals_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."workout" (
    "id" bigint NOT NULL,
    "name" text NOT NULL,
    "description" text NOT NULL,
    "instructions" text NOT NULL,
    "workout_type" text NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_26_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."workout_activity" (
    "id" bigint NOT NULL,
    "workout_id" bigint NOT NULL,
    "intensity_measure" TEXT,
    "intensity_value" bigint,
    "estimated_calories_per_unit_frequency" decimal(10, 6) NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_27_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."workout_plan" (
    "id" bigint NOT NULL,
    "strata_name" text NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_30_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."workout_plan_activity" (
    "id" bigint NOT NULL,
    "workout_plan_id" bigint NOT NULL,
    "workout_activity_id" bigint NOT NULL,
    "estimated_calories" decimal(4, 2) NOT NULL,
    "modified_by_account_id" bigint NOT NULL,
    "planned_duration" bigint,
    "planned_reps" bigint,
    "planned_sets" bigint,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_31_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_availability" (
    "id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_32_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."availability" (
    "id" bigint NOT NULL,
    "weekday" TEXT NOT NULL,
    "start_time" timetz NOT NULL,
    "end_time" timetz NOT NULL,
    "max_time_commitment_seconds" decimal(8, 2),
    "client_availability_id" bigint,
    "coach_availability_id" bigint,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_33_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."coach_availability" (
    "id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_34_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_workout_plan" (
    "id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "workout_plan_id" bigint NOT NULL,
    "start_time" timestamptz NOT NULL,
    "end_time" timestamptz NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_35_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."step_count" (
    "id" bigint NOT NULL,
    "client_telemetry_id" bigint NOT NULL,
    "step_count" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_36_step_count_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_telemetry" (
    "id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "date" date NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_36_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."completed_workout_activity" (
    "id" bigint NOT NULL,
    "completed_reps" bigint,
    "completed_sets" bigint,
    "completed_duration" bigint,
    "estimated_calories" int,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_37_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."daily_mood_survey" (
    "id" bigint NOT NULL,
    "is_seen" boolean NOT NULL,
    "is_started" boolean NOT NULL,
    "is_finished" boolean NOT NULL,
    "completed_survey_id" bigint,
    "client_telemetry_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_38_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."completed_survey" (
    "id" bigint NOT NULL,
    "happiness_meter" smallint,
    "alertness" smallint,
    "healthiness" smallint,
    "todays_goals" text,
    "todays_appreciation" text,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_39_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."health_metrics" (
    "id" bigint NOT NULL,
    "weight" smallint NOT NULL,
    "client_telemetry_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_40_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."completed_meal_activity" (
    "id" bigint NOT NULL,
    "client_prescribed_meal_id" bigint,
    "on_demand_meal_id" bigint,
    "client_telemetry_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_41_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."client_prescribed_meal" (
    "id" bigint NOT NULL,
    "meal_id" bigint NOT NULL,
    "client_id" bigint NOT NULL,
    "prescribed_by_account_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_42_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."meal" (
    "id" bigint NOT NULL,
    "created_by_account_id" bigint NOT NULL,
    "meal_name" text NOT NULL,
    "calories" smallint NOT NULL,
    "portion_size_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_43_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."portion_size" (
    "id" bigint NOT NULL,
    "unit_id" bigint NOT NULL,
    "count" int NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_44_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."unit" (
    "id" bigint NOT NULL,
    "unit_name" text NOT NULL,
    "is_imperial" boolean NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_45_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."workout_equiptment" (
    "id" bigint NOT NULL,
    "equiptment_id" bigint NOT NULL,
    "is_required" boolean NOT NULL,
    "is_recommended" boolean NOT NULL,
    "workout_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_46_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."completed_workout" (
    "id" bigint NOT NULL,
    "workout_plan_activity_id" bigint,
    "workout_activity_id" bigint,
    "completed_workout_details_id" bigint,
    "client_telemetry_id" bigint NOT NULL,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_47_id" PRIMARY KEY ("id")
);

CREATE TABLE "public"."equiptment" (
    "id" bigint NOT NULL,
    "name" text NOT NULL,
    "description" text,
    "last_updated" timestamptz NOT NULL,
    CONSTRAINT "pk_table_48_id" PRIMARY KEY ("id")
);

-- Foreign key constraints
-- Schema: public
ALTER TABLE "public"."account" ADD CONSTRAINT "fk_account_admin_id_admin_id" FOREIGN KEY("admin_id") REFERENCES "public"."admin"("id");
ALTER TABLE "public"."account" ADD CONSTRAINT "fk_account_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."account" ADD CONSTRAINT "fk_account_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."invoice" ADD CONSTRAINT "fk_invoice_billing_cycle_id_billing_cycle_id" FOREIGN KEY("billing_cycle_id") REFERENCES "public"."billing_cycle"("id");
ALTER TABLE "public"."coach_certifications" ADD CONSTRAINT "fk_coach_certifications_certification_id_certifications_id" FOREIGN KEY("certification_id") REFERENCES "public"."certifications"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."chat" ADD CONSTRAINT "fk_chat_client_coach_relationship_id_client_coach_relationsh" FOREIGN KEY("client_coach_relationship_id") REFERENCES "public"."client_coach_relationship"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."chat_message" ADD CONSTRAINT "fk_chat_message_chat_id_chat_id" FOREIGN KEY("chat_id") REFERENCES "public"."chat"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."chat_message" ADD CONSTRAINT "fk_chat_message_from_account_id_account_id" FOREIGN KEY("from_account_id") REFERENCES "public"."account"("id");
ALTER TABLE "public"."client_coach_relationship" ADD CONSTRAINT "fk_client_coach_relationship_request_id_client_coach_request" FOREIGN KEY("request_id") REFERENCES "public"."client_coach_request"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_coach_request" ADD CONSTRAINT "fk_client_coach_request_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."client" ADD CONSTRAINT "fk_client_payment_information_id_payment_information_id" FOREIGN KEY("payment_information_id") REFERENCES "public"."payment_information"("id");
ALTER TABLE "public"."client_report" ADD CONSTRAINT "fk_client_report_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."client_report" ADD CONSTRAINT "fk_client_report_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."coach_certifications" ADD CONSTRAINT "fk_coach_certifications_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."coach_experience" ADD CONSTRAINT "fk_coach_experience_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_coach_request" ADD CONSTRAINT "fk_client_coach_request_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."coach_report" ADD CONSTRAINT "fk_coach_report_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."coach_report" ADD CONSTRAINT "fk_coach_report_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."coach_request" ADD CONSTRAINT "fk_coach_request_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."coach_request" ADD CONSTRAINT "fk_coach_request_role_promotion_resolution_id_role_promotion" FOREIGN KEY("role_promotion_resolution_id") REFERENCES "public"."role_promotion_resolution"("id");
ALTER TABLE "public"."coach_reviews" ADD CONSTRAINT "fk_coach_reviews_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."coach_reviews" ADD CONSTRAINT "fk_coach_reviews_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."coach_experience" ADD CONSTRAINT "fk_coach_experience_experience_id_experience_id" FOREIGN KEY("experience_id") REFERENCES "public"."experience"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."fitness_goals" ADD CONSTRAINT "fk_fitness_goals_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."invoice" ADD CONSTRAINT "fk_invoice_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id");
ALTER TABLE "public"."pricing_plan" ADD CONSTRAINT "fk_pricing_plan_coach_id_coach_id" FOREIGN KEY("coach_id") REFERENCES "public"."coach"("id");
ALTER TABLE "public"."billing_cycle" ADD CONSTRAINT "fk_billing_cycle_pricing_plan_id_pricing_plan_id" FOREIGN KEY("pricing_plan_id") REFERENCES "public"."pricing_plan"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."role_promotion_resolution" ADD CONSTRAINT "fk_role_promotion_resolution_admin_id_admin_id" FOREIGN KEY("admin_id") REFERENCES "public"."admin"("id");
ALTER TABLE "public"."role_promotion_resolution" ADD CONSTRAINT "fk_role_promotion_resolution_account_id_account_id" FOREIGN KEY("account_id") REFERENCES "public"."account"("id");
ALTER TABLE "public"."workout_activity" ADD CONSTRAINT "fk_workout_activity_workout_id_workout_id" FOREIGN KEY("workout_id") REFERENCES "public"."workout"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."workout_plan_activity" ADD CONSTRAINT "fk_workout_plan_activity_workout_activity_id_workout_activit" FOREIGN KEY("workout_activity_id") REFERENCES "public"."workout_activity"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."workout_plan_activity" ADD CONSTRAINT "fk_workout_plan_activity_workout_plan_id_workout_plan_id" FOREIGN KEY("workout_plan_id") REFERENCES "public"."workout_plan"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."workout_plan_activity" ADD CONSTRAINT "fk_workout_plan_activity_modified_by_account_id_account_id" FOREIGN KEY("modified_by_account_id") REFERENCES "public"."account"("id");
ALTER TABLE "public"."client" ADD CONSTRAINT "fk_client_client_availability_id_client_availability_id" FOREIGN KEY("client_availability_id") REFERENCES "public"."client_availability"("id");
ALTER TABLE "public"."availability" ADD CONSTRAINT "fk_availability_client_availability_id_client_availability_i" FOREIGN KEY("client_availability_id") REFERENCES "public"."client_availability"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."coach" ADD CONSTRAINT "fk_coach_coach_availability_coach_availability_id" FOREIGN KEY("coach_availability") REFERENCES "public"."coach_availability"("id");
ALTER TABLE "public"."availability" ADD CONSTRAINT "fk_availability_coach_availability_id_coach_availability_id" FOREIGN KEY("coach_availability_id") REFERENCES "public"."coach_availability"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_workout_plan" ADD CONSTRAINT "fk_client_workout_plan_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_workout_plan" ADD CONSTRAINT "fk_client_workout_plan_workout_plan_id_workout_plan_id" FOREIGN KEY("workout_plan_id") REFERENCES "public"."workout_plan"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_telemetry" ADD CONSTRAINT "fk_client_telemetry_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."step_count" ADD CONSTRAINT "fk_step_count_client_telemetry_id_client_telemetry_id" FOREIGN KEY("client_telemetry_id") REFERENCES "public"."client_telemetry"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."daily_mood_survey" ADD CONSTRAINT "fk_daily_mood_survey_client_telemetry_id_client_telemetry_id" FOREIGN KEY("client_telemetry_id") REFERENCES "public"."client_telemetry"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."daily_mood_survey" ADD CONSTRAINT "fk_daily_mood_survey_completed_survey_id_completed_survey_id" FOREIGN KEY("completed_survey_id") REFERENCES "public"."completed_survey"("id");
ALTER TABLE "public"."health_metrics" ADD CONSTRAINT "fk_health_metrics_client_telemetry_id_client_telemetry_id" FOREIGN KEY("client_telemetry_id") REFERENCES "public"."client_telemetry"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_prescribed_meal" ADD CONSTRAINT "fk_client_prescribed_meal_meal_id_meal_id" FOREIGN KEY("meal_id") REFERENCES "public"."meal"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."meal" ADD CONSTRAINT "fk_meal_created_by_account_id_account_id" FOREIGN KEY("created_by_account_id") REFERENCES "public"."account"("id");
ALTER TABLE "public"."meal" ADD CONSTRAINT "fk_meal_portion_size_id_portion_size_id" FOREIGN KEY("portion_size_id") REFERENCES "public"."portion_size"("id");
ALTER TABLE "public"."portion_size" ADD CONSTRAINT "fk_portion_size_unit_id_unit_id" FOREIGN KEY("unit_id") REFERENCES "public"."unit"("id");
ALTER TABLE "public"."client_prescribed_meal" ADD CONSTRAINT "fk_client_prescribed_meal_client_id_client_id" FOREIGN KEY("client_id") REFERENCES "public"."client"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."client_prescribed_meal" ADD CONSTRAINT "fk_client_prescribed_meal_prescribed_by_account_id_account_i" FOREIGN KEY("prescribed_by_account_id") REFERENCES "public"."account"("id");
ALTER TABLE "public"."completed_meal_activity" ADD CONSTRAINT "fk_completed_meal_activity_on_demand_meal_id_meal_id" FOREIGN KEY("on_demand_meal_id") REFERENCES "public"."meal"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_meal_activity" ADD CONSTRAINT "fk_completed_meal_activity_client_prescribed_meal_id_client_" FOREIGN KEY("client_prescribed_meal_id") REFERENCES "public"."client_prescribed_meal"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_meal_activity" ADD CONSTRAINT "fk_completed_meal_activity_client_telemetry_id_client_teleme" FOREIGN KEY("client_telemetry_id") REFERENCES "public"."client_telemetry"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_workout" ADD CONSTRAINT "fk_completed_workout_details_id_completed_workout_activity_id" FOREIGN KEY("completed_workout_details_id") REFERENCES "public"."completed_workout_activity"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_workout" ADD CONSTRAINT "fk_completed_workout_workout_activity_id_workout_activity_id" FOREIGN KEY("workout_activity_id") REFERENCES "public"."workout_activity"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_workout" ADD CONSTRAINT "fk_completed_workout_workout_plan_activity_id_workout_plan_a" FOREIGN KEY("workout_plan_activity_id") REFERENCES "public"."workout_plan_activity"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."completed_workout" ADD CONSTRAINT "fk_completed_workout_client_telemetry_id_client_telemetry_id" FOREIGN KEY("client_telemetry_id") REFERENCES "public"."client_telemetry"("id") ON DELETE NO ACTION;
ALTER TABLE "public"."workout_equiptment" ADD CONSTRAINT "fk_workout_equiptment_equiptment_id_equiptment_id" FOREIGN KEY("equiptment_id") REFERENCES "public"."equiptment"("id");
ALTER TABLE "public"."workout_equiptment" ADD CONSTRAINT "fk_workout_equiptment_workout_id_workout_id" FOREIGN KEY("workout_id") REFERENCES "public"."workout"("id");

CREATE INDEX idx_invoice_billing_cycle_id ON "public"."invoice"("billing_cycle_id");
CREATE INDEX idx_invoice_client_id ON "public"."invoice"("client_id");
CREATE INDEX idx_coach_certifications_certification_id ON "public"."coach_certifications"("certification_id");
CREATE INDEX idx_chat_client_coach_relationship_id ON "public"."chat"("client_coach_relationship_id");
CREATE INDEX idx_chat_message_chat_id ON "public"."chat_message"("chat_id");
CREATE INDEX idx_chat_message_from_account_id ON "public"."chat_message"("from_account_id");
CREATE INDEX idx_client_coach_relationship_request_id ON "public"."client_coach_relationship"("request_id");
CREATE INDEX idx_client_coach_request_client_id ON "public"."client_coach_request"("client_id");
CREATE INDEX idx_client_coach_request_coach_id ON "public"."client_coach_request"("coach_id");
CREATE INDEX idx_client_payment_information_id ON "public"."client"("payment_information_id");
CREATE INDEX idx_client_report_client_id ON "public"."client_report"("client_id");
CREATE INDEX idx_client_report_coach_id ON "public"."client_report"("coach_id");
CREATE INDEX idx_coach_certifications_coach_id ON "public"."coach_certifications"("coach_id");
CREATE INDEX idx_pricing_plan_coach_id ON "public"."pricing_plan"("coach_id");
CREATE INDEX idx_role_promotion_resolution_admin_id ON "public"."role_promotion_resolution"("admin_id");
CREATE INDEX idx_role_promotion_resolution_role_id ON "public"."role_promotion_resolution"("role_id");
CREATE INDEX idx_role_promotion_resolution_account_id ON "public"."role_promotion_resolution"("account_id");
CREATE INDEX idx_account_admin_id ON "public"."account"("admin_id");
CREATE INDEX idx_account_client_id ON "public"."account"("client_id");
CREATE INDEX idx_account_coach_id ON "public"."account"("coach_id");
CREATE INDEX idx_coach_report_client_id ON "public"."coach_report"("client_id");
CREATE INDEX idx_coach_report_coach_id ON "public"."coach_report"("coach_id");
CREATE INDEX idx_coach_request_coach_id ON "public"."coach_request"("coach_id");
CREATE INDEX idx_coach_request_role_promotion_resolution_id ON "public"."coach_request"("role_promotion_resolution_id");
CREATE INDEX idx_coach_experience_coach_id ON "public"."coach_experience"("coach_id");
CREATE INDEX idx_coach_experience_experience_id ON "public"."coach_experience"("experience_id");
CREATE INDEX idx_fitness_goals_client_id ON "public"."fitness_goals"("client_id");
CREATE INDEX idx_billing_cycle_pricing_plan_id ON "public"."billing_cycle"("pricing_plan_id");
CREATE INDEX idx_workout_activity_workout_id ON "public"."workout_activity"("workout_id");
CREATE INDEX idx_workout_plan_activity_workout_activity_id ON "public"."workout_plan_activity"("workout_activity_id");
CREATE INDEX idx_workout_plan_activity_workout_plan_id ON "public"."workout_plan_activity"("workout_plan_id");
CREATE INDEX idx_workout_plan_activity_modified_by_account_id ON "public"."workout_plan_activity"("modified_by_account_id");
CREATE INDEX idx_client_client_availability_id ON "public"."client"("client_availability_id");
CREATE INDEX idx_availability_client_availability_id ON "public"."availability"("client_availability_id");
CREATE INDEX idx_availability_coach_availability_id ON "public"."availability"("coach_availability_id");
CREATE INDEX idx_coach_coach_availability ON "public"."coach"("coach_availability");
CREATE INDEX idx_client_workout_plan_client_id ON "public"."client_workout_plan"("client_id");
CREATE INDEX idx_client_workout_plan_workout_plan_id ON "public"."client_workout_plan"("workout_plan_id");
CREATE INDEX idx_client_telemetry_client_id ON "public"."client_telemetry"("client_id");
CREATE INDEX idx_step_count_client_telemetry_id ON "public"."step_count"("client_telemetry_id");
CREATE INDEX idx_daily_mood_survey_client_telemetry_id ON "public"."daily_mood_survey"("client_telemetry_id");
CREATE INDEX idx_daily_mood_survey_completed_survey_id ON "public"."daily_mood_survey"("completed_survey_id");
CREATE INDEX idx_health_metrics_client_telemetry_id ON "public"."health_metrics"("client_telemetry_id");
CREATE INDEX idx_client_prescribed_meal_meal_id ON "public"."client_prescribed_meal"("meal_id");
CREATE INDEX idx_client_prescribed_meal_client_id ON "public"."client_prescribed_meal"("client_id");
CREATE INDEX idx_client_prescribed_meal_prescribed_by_account_id ON "public"."client_prescribed_meal"("prescribed_by_account_id");
CREATE INDEX idx_meal_created_by_account_id ON "public"."meal"("created_by_account_id");
CREATE INDEX idx_meal_portion_size_id ON "public"."meal"("portion_size_id");
CREATE INDEX idx_portion_size_unit_id ON "public"."portion_size"("unit_id");
CREATE INDEX idx_completed_meal_activity_on_demand_meal_id ON "public"."completed_meal_activity"("on_demand_meal_id");
CREATE INDEX idx_completed_meal_activity_client_prescribed_meal_id ON "public"."completed_meal_activity"("client_prescribed_meal_id");
CREATE INDEX idx_completed_meal_activity_client_telemetry_id ON "public"."completed_meal_activity"("client_telemetry_id");
CREATE INDEX idx_completed_workout_details_id ON "public"."completed_workout"("completed_workout_details_id");
CREATE INDEX idx_completed_workout_workout_activity_id ON "public"."completed_workout"("workout_activity_id");
CREATE INDEX idx_completed_workout_workout_plan_activity_id ON "public"."completed_workout"("workout_plan_activity_id");
CREATE INDEX idx_completed_workout_client_telemetry_id ON "public"."completed_workout"("client_telemetry_id");
CREATE INDEX idx_workout_equiptment_equiptment_id ON "public"."workout_equiptment"("equiptment_id");
CREATE INDEX idx_workout_equiptment_workout_id ON "public"."workout_equiptment"("workout_id");

