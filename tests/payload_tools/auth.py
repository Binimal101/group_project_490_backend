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


def build_update_account_payload(age=35, email_prefix="updated", bio="Updated bio", pfp_url=None, gender="non-binary"):
    """Builds a payload for updating account fields: age, email, bio, pfp_url, gender."""
    import datetime as dt
    timestamp = dt.datetime.now().timestamp()
    if pfp_url is None:
        pfp_url = f"https://example.com/pfp_{int(timestamp)}.png"
    return {
        "age": age,
        "email": f"{email_prefix}_{timestamp}@example.com",
        "bio": bio,
        "pfp_url": pfp_url,
        "gender": gender,
    }
