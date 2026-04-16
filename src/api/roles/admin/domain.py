from pydantic import BaseModel

class ResolveCoachRequestInput(BaseModel):
    coach_request_id: int
    is_approved: bool