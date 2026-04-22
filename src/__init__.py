import json
import os
from dotenv import load_dotenv
from sqlmodel import create_engine

load_dotenv(ENV_LOCATION := os.path.abspath(
    os.path.join(os.path.basename(__file__), "..", ".env")
))

print(f"Loaded dotenv @ {ENV_LOCATION}")

CORS_ALLOWED_ORIGINS = []
 
db_conn_str, testing_db_conn_str, pass_salt, jwt_secret, jwt_algorithm, gcp_client_id = [None] * 6

# Ensure these names exist regardless of runtime branch so `config` can reference them.
SUPABASE_URL = None
SUPABASE_SERVICE_KEY = None

# Interpret IS_TESTING from environment in a forgiving way
_is_testing_raw = os.getenv("IS_TESTING", "false")
is_testing = str(_is_testing_raw).strip().lower() in ("1", "true", "yes")

if not is_testing:
    # production / normal runtime: require DATABASE_URL and other secrets
    try:
        cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip().strip("'\"")
        if cors_raw:
            if cors_raw.startswith("["):
                CORS_ALLOWED_ORIGINS = json.loads(cors_raw)
                if not isinstance(CORS_ALLOWED_ORIGINS, list):
                    raise ValueError("CORS_ALLOWED_ORIGINS must be a JSON array")
            else:
                CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]
    except json.JSONDecodeError:
        raise Exception("CORS_ALLOWED_ORIGINS not proper JSON")

    db_conn_str = os.getenv("DATABASE_URL", None)
    if db_conn_str is None:
        raise Exception("Error, no DATABASE_URL environment variable found for production runtime")

    jwt_secret = os.getenv("JWT_SECRET", None)
    if jwt_secret is None:
        raise Exception("Error, no JWT_SECRET found")

    gcp_client_id = os.getenv("GCP_CLIENT_ID", None)
    if gcp_client_id is None:
        raise Exception("Error, no GCP_CLIENT_ID found")

    pass_salt = os.getenv("PASSWORD_SALT", None)
    if pass_salt is None:
        raise Exception("Error, no PASSWORD_SALT found")

    jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")

    # Supabase storage config (optional for some runtimes, required in production)
    SUPABASE_URL = os.getenv("SUPABASE_URL", None)
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", None)

    # try to coerce into SQLAlchemy and see if it actually connects
    try:
        create_engine(db_conn_str).connect()
        print("Database connection successful")
    except Exception as e:
        print(f"Database connection failed: {e}")
else:
    # testing / GH Actions runtime: use TESTING_DATABASE_URL
    testing_db_conn_str = os.getenv("TESTING_DATABASE_URL", None)
    if testing_db_conn_str is None:
        raise Exception("Error, no TESTING_DATABASE_URL found for testing runtime")

    TESTING_SUPABASE_URL = os.getenv("TESTING_SUPABASE_URL", None)
    TESTING_SUPABASE_SERVICE_KEY = os.getenv("TESTING_SUPABASE_SERVICE_KEY", None) or os.getenv("TESTING_SUPABASE_KEY", None)

    # Use testing Supabase values if present, otherwise leave defaults (tests may monkeypatch os.env at runtime)
    if TESTING_SUPABASE_URL:
        SUPABASE_URL = TESTING_SUPABASE_URL
    if TESTING_SUPABASE_SERVICE_KEY:
        SUPABASE_SERVICE_KEY = TESTING_SUPABASE_SERVICE_KEY

    # Enforce testing Supabase config presence when running tests
    if not TESTING_SUPABASE_URL:
        raise Exception("Error, no TESTING_SUPABASE_URL found for testing runtime")
    if not TESTING_SUPABASE_SERVICE_KEY:
        raise Exception("Error, no TESTING_SUPABASE_SERVICE_KEY found for testing runtime")

class config:
    # Prefer explicit DATABASE_URL for production; fall back to testing DB when running tests
    DATABASE_URL: str = db_conn_str or testing_db_conn_str  # type: ignore

    PASSWORD_SALT: str = pass_salt or None # type: ignore
    JWT_SECRET: str = jwt_secret or "863724293gf7g2394vgf6b7h39824vbc" # type: ignore
    ALGORITHM: str = jwt_algorithm or "HS256" # type: ignore
    CORS_ALLOWED_ORIGINS: list[str] = CORS_ALLOWED_ORIGINS or None  # type: ignore
    GCP_CLIENT_ID: str = gcp_client_id or None  # type: ignore
    SUPABASE_URL: str = SUPABASE_URL or None  # type: ignore
    SUPABASE_SERVICE_KEY: str = SUPABASE_SERVICE_KEY or None  # type: ignore

if is_testing:
    print("Config loaded: running in TESTING mode using TESTING_DATABASE_URL")
else:
    print("Config loaded: running in PRODUCTION mode using DATABASE_URL")