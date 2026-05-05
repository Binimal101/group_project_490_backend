#imports and dependencies
from sqlmodel import select

from fastapi import APIRouter, Depends, HTTPException
from src.api.dependencies import get_account_from_bearer, PaginationParams, get_client_account
from src.database.session import get_session

#models
from src.database.account.models import Account
from src.database.coach_client_relationship.models import Chat, ChatMessage, ClientCoachRelationship, ClientCoachRequest

#domains
from src.api.roles.shared.domain import CreateNewChatInput, NewChatResponse, SendMessageResponse, GetMessagesResponse, ChatWithAccountResponse

router = APIRouter(prefix="/roles/shared/chat", tags=["shared", "chat"])

@router.post("/new_chat", response_model=NewChatResponse)
def create_new_chat(
    payload: CreateNewChatInput,
    db = Depends(get_session),
    acc: Account = Depends(get_account_from_bearer)
):
    #checking if relationship is valid
    relationship = db.get(ClientCoachRelationship, payload.relationship_id)
    
    if relationship is None:
        raise HTTPException(404, detail="Relationship not found")
    
    if relationship.is_active == False:
        raise HTTPException(400, detail="Relationship is not active")
    
    chat = Chat(client_coach_relationship_id=payload.relationship_id)
    db.add(chat)
    db.flush()
    db.commit()

    if chat.id is None:
        raise HTTPException(500, detail="Chat creation failed")
    
    return NewChatResponse(chat_id=chat.id)

@router.get("/chat_with_account/{account_id}", response_model=ChatWithAccountResponse)
def new_chat_with_account(account_id: int, db = Depends(get_session), from_acc: Account = Depends(get_account_from_bearer)):
    """
    Gets chat with a specific account
    """
    if from_acc is None:
        raise HTTPException(404, detail="Account not found")
    
        
    to_acc = db.query(Account).filter(id == account_id).first()
    
    if to_acc is None:
        raise HTTPException(404, detail="The account you are trying to chat with is not found")
    
    if from_acc.coach_id is None:    
        request = db.query(ClientCoachRequest).filter(ClientCoachRequest.client_id == from_acc.client_id).first()
    else:
        request = db.query(ClientCoachRequest).filter(ClientCoachRequest.client_id == to_acc.client_id).first()

    if request is None:
        raise HTTPException(404, detail="No Relationship Found")

    relationship = db.query(ClientCoachRelationship).filter(ClientCoachRelationship.request_id == request.id).first()

    if relationship is None:
        raise HTTPException(404, detail="No Relationship Found")

    chat = db.query(Chat).filter(Chat.client_coach_relationship_id == relationship.id).first()

    if chat is None:
        raise HTTPException(404, detail="Chat not found")
    
    messages = db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).all()

    return ChatWithAccountResponse(messages = messages)


    

@router.post("/send_message/{chat_id}", response_model=SendMessageResponse)
def send_message(chat_id: int, message_text: str, db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Adds a message to the database and returns it for confirmation and display
    """

    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, detail="Chat not found")
    
    new_message = ChatMessage(chat_id=chat_id, from_account_id=acc.id, message_text=message_text, is_read=False)
    db.add(new_message)
    db.flush()
    db.commit()

    if new_message.id is None:
        raise HTTPException(500, detail="Message creation failed")

    return SendMessageResponse(message_id=new_message.id, message_text=new_message.message_text, from_account_id=new_message.from_account_id)

@router.get("/get_messages/{chat_id}", response_model=GetMessagesResponse)
def get_messages(chat_id: int, pagination: PaginationParams = Depends(PaginationParams), db = Depends(get_session), acc: Account = Depends(get_client_account)):
    """
    Gets messages for a chat with pagination
    """
    if acc.id is None:
        raise HTTPException(404, detail="Account not found")
    
    chat = db.get(Chat, chat_id)

    if chat is None:
        raise HTTPException(404, detail="Chat not found")
    
    query = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
    
    messages = db.exec(query.offset(pagination.skip).limit(pagination.limit)).all()
    
    return GetMessagesResponse(messages=messages)
    