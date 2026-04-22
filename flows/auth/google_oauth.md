**Google OAuth — /auth/google (FastAPI)**

**Line labels:**
- `GET_AUTH` — GET /auth/google
- `REDIRECT_GOOGLE` — Google consent URL
- `CALLBACK` — /auth/google callback (code,state)
- `VERIFY_STATE` — verify state cookie
- `EXCHANGE_TOKEN` — POST to Google token endpoint
- `VALIDATE_IDTOKEN` — validate id_token
- `LINK_CREATE` — find/link/create Account
- `ISSUE_JWT` — create local JWT
- `SET_JWT_COOKIE` — set readable `jwt` cookie on .till-failure.us
- `REDIRECT_ONBOARD` — redirect to /onboarding
- `ERROR` — failure

```mermaid
stateDiagram-v2
    [*] --> GET_AUTH
    GET_AUTH --> REDIRECT_GOOGLE
    REDIRECT_GOOGLE --> GOOGLE_CONSENT
    GOOGLE_CONSENT --> CALLBACK
    CALLBACK --> VERIFY_STATE
    VERIFY_STATE --> EXCHANGE_TOKEN
    EXCHANGE_TOKEN --> VALIDATE_IDTOKEN
    VALIDATE_IDTOKEN --> LINK_CREATE
    LINK_CREATE --> ISSUE_JWT
    ISSUE_JWT --> SET_JWT_COOKIE
    SET_JWT_COOKIE --> REDIRECT_ONBOARD
    REDIRECT_ONBOARD --> [*]
    VERIFY_STATE --> ERROR
    EXCHANGE_TOKEN --> ERROR
    VALIDATE_IDTOKEN --> ERROR
    ERROR --> [*]
```
File created: [flows/auth/google_oauth.md](flows/auth/google_oauth.md)
