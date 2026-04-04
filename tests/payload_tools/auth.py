import datetime as dt

def build_signup_payload(email_prefix="testuser", password="StrongPass123", name="Test User", age=30, gender="non-binary"):
    """Builds a mock user signup payload."""
    timestamp = dt.datetime.now().timestamp()
    return {
        "email": f"{email_prefix}_{timestamp}@example.com",
        "password": password,
        "name": name,
        "age": age,
        "gender": gender,
    }

def build_login_payload(email, password="StrongPass123"):
    """Builds a mock user login payload."""
    return {
        "email": email,
        "password": password
    }
