from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    age: int
    gender: str
    pfp_url: Optional[str] = None
    bio: Optional[str] = None
    gcp_user_id: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"