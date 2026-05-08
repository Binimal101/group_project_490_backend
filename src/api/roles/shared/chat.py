from sqlmodel import select, or_
from typing import cast

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_active_account, PaginationParams
from src.database.session import get_session

from src.database.account.models import Account, AccountBlock
from src.database.coach_client_relationship.models import (
    AccountChat,
    Chat,
    ChatMessage,
)

from src.api.roles.shared.domain import (
    SendMessageResponse,
    GetMessagesResponse,
    ChatWithAccountResponse,
    ConversationListResponse,
    ConversationSummary,
    PublicAccountSummary,
)


router = APIRouter(prefix="/roles/shared/chat", tags=["shared", "chat"])


# ─── helpers ────────────────────────────────────────────────────────────────
def _block_exists_either_direction(db, account_a: int, account_b: int) -> bool:
    return db.exec(
        select(AccountBlock).where(
            or_(
                (AccountBlock.blocker_id == account_a) & (AccountBlock.blockee_id == account_b),
                (AccountBlock.blocker_id == account_b) & (AccountBlock.blockee_id == account_a),
            )
        )
    ).first() is not None


def _ensure_participant(db, chat_id: int, account_id: int) -> AccountChat:
    """403 unless the account is one of the two participants in the chat."""
    row = db.exec(
        select(AccountChat).where(
            AccountChat.chat_id == chat_id,
            AccountChat.account_id == account_id,
        )
    ).first()
    if row is None:
        raise HTTPException(403, detail="You are not a participant in this chat")
    return row


def _other_participant(db, chat_id: int, sender_id: int) -> AccountChat:
    """Find the recipient row for a chat (the AccountChat entry that isn't the sender)."""
    other = db.exec(
        select(AccountChat).where(
            AccountChat.chat_id == chat_id,
            AccountChat.account_id != sender_id,
        )
    ).first()
    if other is None:
        raise HTTPException(404, detail="Chat has no recipient")
    return other


def _public_summary(db, acc: Account) -> PublicAccountSummary:
    is_verified = False
    if acc.coach_id is not None:
        from src.database.coach.models import Coach
        coach = db.get(Coach, acc.coach_id)
        if coach is not None and getattr(coach, "verified", False):
            is_verified = True
    return PublicAccountSummary(
        id=acc.id,  # type: ignore
        name=acc.name,
        pfp_url=acc.pfp_url,
        age=acc.age,
        gender=acc.gender,
        is_coach=acc.coach_id is not None,
        is_verified_coach=is_verified,
        is_client=acc.client_id is not None,
        is_admin=acc.admin_id is not None,
    )


# ─── endpoints ──────────────────────────────────────────────────────────────
@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(db = Depends(get_session), acc: Account = Depends(get_active_account)):
    """All chats the caller participates in, with the other participant's public profile attached."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")

    # Chat ids that belong to the caller.
    my_chat_ids = [
        row.chat_id for row in db.exec(
            select(AccountChat).where(AccountChat.account_id == acc.id)
        ).all()
    ]
    if not my_chat_ids:
        return ConversationListResponse(conversations=[])

    # All participants of those chats (we'll filter out the caller below).
    participants = db.exec(
        select(AccountChat, Account)
        .join(Account, Account.id == AccountChat.account_id)
        .where(AccountChat.chat_id.in_(my_chat_ids))
    ).all()

    partners_by_chat: dict[int, Account] = {}
    for ac, account in participants:
        if account.id == acc.id:
            continue
        partners_by_chat[ac.chat_id] = account

    # Latest message per chat.
    latest_messages = db.exec(
        select(ChatMessage).where(ChatMessage.chat_id.in_(my_chat_ids))
    ).all()
    latest_by_chat: dict[int, ChatMessage] = {}
    for msg in latest_messages:
        prev = latest_by_chat.get(msg.chat_id)
        if prev is None or (msg.id or 0) > (prev.id or 0):
            latest_by_chat[msg.chat_id] = msg

    # Unread = messages from the partner that aren't yet read by us.
    unread_rows = db.exec(
        select(ChatMessage).where(
            ChatMessage.chat_id.in_(my_chat_ids),
            ChatMessage.from_account_id != acc.id,
            ChatMessage.is_read == False,
        )
    ).all()
    unread_by_chat: dict[int, int] = {}
    for msg in unread_rows:
        unread_by_chat[msg.chat_id] = unread_by_chat.get(msg.chat_id, 0) + 1

    summaries: list[ConversationSummary] = []
    for chat_id, partner in partners_by_chat.items():
        latest = latest_by_chat.get(chat_id)
        summaries.append(
            ConversationSummary(
                chat_id=chat_id,
                partner=_public_summary(db, partner),
                last_message=latest.message_text if latest else None,
                last_message_at=latest.last_updated if latest else None,
                unread_count=unread_by_chat.get(chat_id, 0),
            )
        )

    summaries.sort(
        key=lambda s: (s.last_message_at or 0).timestamp() if s.last_message_at else 0,
        reverse=True,
    )

    return ConversationListResponse(conversations=summaries)


@router.get("/partner/{chat_id}", response_model=PublicAccountSummary)
def get_chat_partner(chat_id: int, db = Depends(get_session), acc: Account = Depends(get_active_account)):
    """The other participant's public profile for a chat the caller is in."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")
    _ensure_participant(db, chat_id, acc.id)
    other_row = _other_participant(db, chat_id, acc.id)
    partner = db.get(Account, other_row.account_id)
    if partner is None:
        raise HTTPException(404, detail="Partner account not found")
    return _public_summary(db, partner)


@router.get("/by-account/{account_id}", response_model=ChatWithAccountResponse)
def get_or_create_chat_with_account(
    account_id: int,
    db = Depends(get_session),
    from_acc: Account = Depends(get_active_account),
):
    """
    Universal DM: any two accounts may chat unless one has blocked the other.
    No client/coach relationship is required.

    Existing chat is always returned (so historical messages remain readable
    even after a block — sends are gated separately by send_message).
    A new chat is only created when none exists; if a block exists at that
    moment, creation is denied.
    """
    if from_acc is None or from_acc.id is None:
        raise HTTPException(404, detail="Account not found")
    if from_acc.id == account_id:
        raise HTTPException(400, detail="Cannot start a chat with yourself")

    to_acc = db.get(Account, account_id)
    if to_acc is None or to_acc.id is None:
        raise HTTPException(404, detail="Account not found")

    # Find any existing chat where both accounts are participants.
    chat = db.exec(
        select(Chat)
        .join(AccountChat, AccountChat.chat_id == Chat.id)
        .where(AccountChat.account_id.in_([from_acc.id, to_acc.id]))
        .group_by(Chat.id)
        .having(_pg_count_distinct(AccountChat.account_id) == 2)
    ).first()

    if chat is None:
        # Block check: don't spawn an empty thread if either side has blocked.
        if _block_exists_either_direction(db, from_acc.id, to_acc.id):
            raise HTTPException(403, detail="Cannot start a chat with this account")

        chat = Chat()
        db.add(chat)
        db.flush()
        db.add(AccountChat(account_id=from_acc.id, chat_id=cast(int, chat.id)))
        db.add(AccountChat(account_id=to_acc.id, chat_id=cast(int, chat.id)))
        db.commit()
        db.refresh(chat)

    messages = db.exec(
        select(ChatMessage).where(ChatMessage.chat_id == chat.id)
    ).all()

    return ChatWithAccountResponse(messages=messages, chat_id=cast(int, chat.id))


@router.post("/messages/{chat_id}", response_model=SendMessageResponse)
def send_message(
    chat_id: int,
    message_text: str,
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Send a message. Read-only-on-block policy: sending is rejected if either side has blocked the other."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")

    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, detail="Chat not found")

    _ensure_participant(db, chat_id, acc.id)
    recipient_row = _other_participant(db, chat_id, acc.id)

    if _block_exists_either_direction(db, acc.id, recipient_row.account_id):
        raise HTTPException(403, detail="You cannot send messages in this chat")

    new_message = ChatMessage(
        chat_id=chat_id,
        from_account_id=acc.id,
        message_text=message_text,
        is_read=False,
    )
    db.add(new_message)
    db.flush()

    db.commit()

    if new_message.id is None:
        raise HTTPException(500, detail="Message creation failed")

    return SendMessageResponse(
        message_id=new_message.id,
        message_text=new_message.message_text,
        from_account_id=new_message.from_account_id,
    )


@router.get("/messages/{chat_id}", response_model=GetMessagesResponse)
def get_messages(
    chat_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Read messages. Available to chat participants regardless of block state (history is read-only on block)."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")

    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(404, detail="Chat not found")

    _ensure_participant(db, chat_id, acc.id)

    messages = db.exec(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat_id)
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()

    return GetMessagesResponse(messages=messages)


@router.post("/messages/{chat_id}/read")
def mark_messages_read(
    chat_id: int,
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Mark all messages in a chat as read for the calling account."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")
    _ensure_participant(db, chat_id, acc.id)
    unread = db.exec(
        select(ChatMessage).where(
            ChatMessage.chat_id == chat_id,
            ChatMessage.from_account_id != acc.id,
            ChatMessage.is_read == False,
        )
    ).all()
    for msg in unread:
        msg.is_read = True
    db.commit()
    return {"marked_read": len(unread)}


@router.get("/unread_count")
def get_unread_count(
    db = Depends(get_session),
    acc: Account = Depends(get_active_account),
):
    """Total number of unread messages across all chats the caller participates in."""
    if acc is None or acc.id is None:
        raise HTTPException(404, detail="Account not found")
    my_chat_ids = [
        row.chat_id for row in db.exec(
            select(AccountChat).where(AccountChat.account_id == acc.id)
        ).all()
    ]
    if not my_chat_ids:
        return {"total_unread": 0}
    count = len(db.exec(
        select(ChatMessage).where(
            ChatMessage.chat_id.in_(my_chat_ids),
            ChatMessage.from_account_id != acc.id,
            ChatMessage.is_read == False,
        )
    ).all())
    return {"total_unread": count}


# Lazy import to avoid sqlalchemy func import at module top.
def _pg_count_distinct(col):
    from sqlalchemy import func
    return func.count(func.distinct(col))
