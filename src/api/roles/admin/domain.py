from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import List, Optional

from src.api.roles.coach.domain import AccountPublic
from src.database.coach.models import Experience, Certifications


class AdminAccountItem(BaseModel):
    id: int
    name: str
    email: str
    role: str
    roles: List[str]
    status: str
    is_active: bool
    created_at: Optional[datetime] = None
    last_active: Optional[str] = None


class PotentialCoachItem(BaseModel):
    coach_request_id: int
    id: Optional[int] = None
    coach_id: int
    base_account: Optional[AccountPublic] = None
    experiences: Optional[List[Experience]] = None
    certifications: Optional[List[Certifications]] = None

    @model_validator(mode="after")
    def set_id(self):
        if self.id is None:
            self.id = self.coach_request_id
        return self

class AdminTransactionsResponse(BaseModel):
    total_transacted: float


class AdminAnalyticsPoint(BaseModel):
    """One bucket on the engagement bar chart."""
    label: str
    active_users: int
    new_signups: int


class AdminAnalyticsResponse(BaseModel):
    """All three rollups in one payload so the dashboard can switch period
    tabs (daily / weekly / monthly) without refetching."""
    daily: List[AdminAnalyticsPoint]
    weekly: List[AdminAnalyticsPoint]
    monthly: List[AdminAnalyticsPoint]


class AdminEngagementResponse(BaseModel):
    """Platform-wide engagement aggregates that don't fit elsewhere.
    Used by the admin dashboard to fill the slots formerly held by the fake
    'this month' / 'active subscriptions' cards."""
    active_coach_client_pairs: int
    total_messages_sent: int


class AdminReportItem(BaseModel):
    """One row in the admin "Active Reports" feed.
    `kind` distinguishes coach-on-client (filed by a coach about a client) from
    client-on-coach (filed by a client about a coach). The id alone is not
    unique across the two tables, so `kind` plus `id` is the real key the
    dashboard uses for dismiss/escalate actions.
    `reported_account_id` lets the dashboard's "Take Action" button hit
    /roles/admin/accounts/{id}/deactivate without an extra lookup."""
    id: int
    kind: str  # "coach_on_client" | "client_on_coach"
    reporter_name: str
    reported_name: str
    reported_account_id: Optional[int] = None
    reason: str
    created_at: Optional[datetime] = None


class ResolveCoachRequestInput(BaseModel):
    coach_request_id: int
    is_approved: bool
