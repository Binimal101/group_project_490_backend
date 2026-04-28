from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.dependencies import get_account_from_bearer
from src.api.auth.services import serialize_account

#Routers

from src.api.auth.auth import router as auth_router

#Role CRUD
from src.api.roles.coach.coach import router as coach_router
from src.api.roles.client.client import router as client_router
from src.api.roles.shared.fitness import router as shared_fitness_router
from src.api.roles.shared.account import router as shared_account_router
from src.api.roles.shared.chat import router as shared_chat_router
from src.api.roles.shared.client_coach_relationship import router as shared_client_coach_relationship_router
from src.api.roles.client.fitness import router as client_fitness_router
from src.api.roles.client.telemetry import router as client_telemetry_router
from src.api.roles.coach.fitness import router as coach_fitness_router
from src.api.roles.admin.admin import router as admin_router

app = FastAPI(title="Group 6 490 Project API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)  # includes login, signup, and token routes
app.include_router(coach_router)
app.include_router(client_router)
app.include_router(shared_fitness_router)
app.include_router(shared_account_router)
app.include_router(shared_chat_router)
app.include_router(shared_client_coach_relationship_router)
app.include_router(client_fitness_router)
app.include_router(client_telemetry_router)
app.include_router(coach_fitness_router)
app.include_router(admin_router)

@app.get("/me")  # get_current_account assumes they pass a valid jwt as bearer
def read_current_account(user = Depends(get_account_from_bearer)):
    return serialize_account(user)

@app.get("/")
def health():
    return

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)    
