from datetime import date

from fastapi import APIRouter, HTTPException, Depends
from src.api.dependencies import get_account_from_bearer, get_client_account

#models
from src.api.roles.client.domain import InitialSurveyInput, ClientAccountResponse, CreateClientResponse, DunderResponse, UpdateClientInfoInput
 
from src.database.session import get_session
from src.database.account.models import Account
from src.database.client.models import Client, ClientAvailability
from src.database.telemetry.models import ClientTelemetry

router = APIRouter(prefix="/roles/client", tags=["client"])

@router.post("/initial_survey", response_model=CreateClientResponse)
def log_initial_survey(client_details: InitialSurveyInput, db = Depends(get_session), acc: Account = Depends(get_account_from_bearer)):
    """
    Creates a client, modifies user account to show client_id=xxx
    Attaches pmt info and fitness goal from initial survey
    Errors when a user has a client_id
    """

    if acc.client_id is not None:
        raise HTTPException(409, detail="Client profile already exists for this account")

    db.add(client_details.payment_information)
    for availability in client_details.availabilities:
        db.add(availability)
    
    db.flush()

    client_availability = ClientAvailability()
    db.add(client_availability)
    db.flush()

    for a in client_details.availabilities:
        a.client_availability_id = client_availability.id

    client = Client(
        payment_information_id=client_details.payment_information.id,
        client_availability_id=client_availability.id,
    )

    db.add(client)
    db.flush()

    telem = ClientTelemetry(client_id=client.id, date=date.today())
    db.add(telem)
    
    client_details.fitness_goals.client_id = client.id  # type: ignore
    db.add(client_details.fitness_goals)

    acc.client_id = client.id
    
    db.flush()

    client_details.initial_health_metric.client_telemetry_id = telem.id

    db.add(client_details.initial_health_metric)
    
    db.commit()

    return CreateClientResponse(client_id=client.id) # type: ignore

@router.post("/update_client_information", response_model=DunderResponse)
def update_client_information(payload: UpdateClientInfoInput, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Availabilities: providing availabilities will ADD availability, should REMOVE exisiting availability BEFORE calling this method if batch updating
    Fitness goals will override current reading
    Health metrics appends new record as client_telemetry
    Payment information is overridden

    Will merge timelines for multiple availabilities mapping to the client if new addition intersects
    """
    if payload.availabilities: 
        pass
    if payload.fitness_goals:
        pass
    if payload.health_metrics:
        pass
    if payload.payment_information:
        pass

    return DunderResponse()

@router.post("/me", response_model=ClientAccountResponse)
def me(db = Depends(get_session), acc: Account = Depends(get_client_account)):
    return ClientAccountResponse(
        base_account=acc,
        client_account=db.get(Client, acc.client_id)
    )