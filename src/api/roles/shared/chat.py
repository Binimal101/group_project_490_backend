#imports and dependencies
from sqlmodel import select

from fastapi import APIRouter, Depends, HTTPException
from src.api.dependencies import get_active_account, PaginationParams, get_client_account
from src.database.session import get_session
from typing import cast

#models
from src.database.account.models import Account, Notification
from src.database.coach_client_relationship.models import Chat, ChatMessage, ClientCoachRelationship, ClientCoachRequest

#domains
from src.api.roles.shared.domain import SendMessageResponse, GetMessagesResponse, ChatWithAccountResponse

router = APIRouter(prefix="/roles/shared/chat", tags=["shared", "chat"])

@router.get("/by-account/{account_id}", response_model=ChatWithAccountResponse)
def get_or_create_chat_with_account(account_id: int, db = Depends(get_session), from_acc: Account = Depends(get_active_account)):
    """
    Gets or creates a chat with a specific account.
    Automatically creates the chat and relationship if they don't exist.
    Returns the chat ID and existing messages.
    """
    if from_acc is None:
        raise HTTPException(404, detail="Account not found")

    to_acc = db.query(Account).filter(Account.id == account_id).first()
    if to_acc is None:
        raise HTTPException(404, detail="Account not found")

    # A coach is also a client by default, so either account could be on either
    # side of a ClientCoachRequest. Build whichever direction(s) apply, then
    # pick the most recent ACTIVE, non-blocked relationship — re-hires after a
    # termination leave a stale request/relationship pair that would otherwise
    # win an unordered .first() lookup.
    direction_filters = []
    if from_acc.client_id is not None and to_acc.coach_id is not None:
        direction_filters.append(
            (ClientCoachRequest.client_id == from_acc.client_id)
            & (ClientCoachRequest.coach_id == to_acc.coach_id)
        )
    if from_acc.coach_id is not None and to_acc.client_id is not None:
        direction_filters.append(
            (ClientCoachRequest.client_id == to_acc.client_id)
            & (ClientCoachRequest.coach_id == from_acc.coach_id)
        )

    if not direction_filters:
        raise HTTPException(404, detail="No relationship exists between these accounts, didn't pass direction filter")

    direction_predicate = direction_filters[0]
    for extra in direction_filters[1:]:
        direction_predicate = direction_predicate | extra

    row = db.exec(
        select(ClientCoachRequest, ClientCoachRelationship)
        .join(
            ClientCoachRelationship,
            ClientCoachRelationship.request_id == ClientCoachRequest.id,
        )
        .where(
            direction_predicate,
            ClientCoachRequest.is_accepted.is_(True),
            ClientCoachRelationship.is_active.is_(True),
            ClientCoachRelationship.client_blocked.is_(False),
            ClientCoachRelationship.coach_blocked.is_(False),
        )
        .order_by(ClientCoachRequest.last_updated.desc(), ClientCoachRequest.id.desc())
    ).first()

    if row is None:
        raise HTTPException(404, detail="No active relationship between these accounts")

    request, relationship = row

    # Find or create chat
    chat = db.query(Chat).filter(Chat.client_coach_relationship_id == relationship.id).first()

    if chat is None:
        chat = Chat(client_coach_relationship_id=relationship.id)
        db.add(chat)
        db.flush()
        db.commit()

    # Get all messages for this chat
    messages = db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).all()

    chat_id = cast(int, chat.id)
    return ChatWithAccountResponse(messages=messages, chat_id=chat_id)


def _resolve_chat_recipient_account(db, chat: Chat, sender: Account) -> Account:
    relationship = db.get(ClientCoachRelationship, chat.client_coach_relationship_id)
    if relationship is None:
        raise HTTPException(404, detail="Relationship not found")
    if not relationship.is_active:
        raise HTTPException(403, detail="Relationship is no longer active")

    request = db.get(ClientCoachRequest, relationship.request_id)
    if request is None:
        raise HTTPException(404, detail="Relationship request not found")

    if sender.client_id == request.client_id:
        recipient = db.exec(select(Account).where(Account.coach_id == request.coach_id)).first()
    elif sender.coach_id == request.coach_id:
        recipient = db.exec(select(Account).where(Account.client_id == request.client_id)).first()
    else:
        raise HTTPException(403, detail="Not authorized to send messages in this chat")

    if recipient is None or recipient.id is None:
        raise HTTPException(404, detail="Recipient account not found")

    return recipient


    

@router.post("/messages/{chat_id}", response_model=SendMessageResponse)
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

    recipient_account = _resolve_chat_recipient_account(db, chat, acc)
    if recipient_account.id != acc.id:
        db.add(
            Notification(
                account_id=recipient_account.id,
                fav_category="chat_message",
                message=f"New message from {acc.name}",
                details=message_text,
            )
        )

    db.commit()

    if new_message.id is None:
        raise HTTPException(500, detail="Message creation failed")

    return SendMessageResponse(message_id=new_message.id, message_text=new_message.message_text, from_account_id=new_message.from_account_id)

@router.get("/messages/{chat_id}", response_model=GetMessagesResponse)
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
    