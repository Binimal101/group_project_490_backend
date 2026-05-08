"""Block + universal-DM behavior tests."""
from datetime import datetime, timezone

from sqlmodel import select

from src.api.dependencies import create_jwt_token
from src.database.account.models import Account, AccountBlock
from src.database.coach.models import Coach
from src.database.coach_client_relationship.models import (
    AccountChat,
    Chat,
    ClientCoachRelationship,
    ClientCoachRequest,
)
from tests.payload_tools.auth import build_login_payload, build_signup_payload
from tests.payload_tools.client import build_client_init_payload
from tests.payload_tools.coach import build_coach_request_payload


def _signup_client(test_client, prefix):
    payload = build_signup_payload(email_prefix=prefix)
    test_client.post("/auth/signup", json=payload)
    login = test_client.post("/auth/login", json=build_login_payload(payload["email"], payload["password"]))
    header = {"Authorization": f"Bearer {login.json()['access_token']}"}
    test_client.post("/roles/client/initial_survey", json=build_client_init_payload(), headers=header)
    me = test_client.get("/me", headers=header).json()
    return header, me


def _promote_to_coach(test_client, header, db_session):
    res = test_client.post("/roles/coach/request_coach_creation", json=build_coach_request_payload(), headers=header)
    assert res.status_code == 200, res.text
    coach_id = res.json()["coach_id"]
    coach = db_session.get(Coach, coach_id)
    coach.verified = True
    db_session.add(coach)
    db_session.commit()
    return coach_id


def _force_active_relationship(db_session, client_acc, coach_acc):
    """Insert an accepted request + active relationship directly, bypassing
    /accept_client to avoid generating invoices that pollute global admin
    totals other tests rely on."""
    request = ClientCoachRequest(
        client_id=client_acc.client_id,
        coach_id=coach_acc.coach_id,
        is_accepted=True,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)
    rel = ClientCoachRelationship(
        request_id=request.id,
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db_session.add(rel)
    db_session.commit()
    db_session.refresh(rel)
    return request, rel


# ─── DM tests ────────────────────────────────────────────────────────────────
def test_two_clients_with_no_relationship_can_dm(test_client):
    a_header, a_me = _signup_client(test_client, "blocka_a")
    b_header, b_me = _signup_client(test_client, "blocka_b")

    res = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header)
    assert res.status_code == 200, res.text
    chat_id = res.json()["chat_id"]
    assert isinstance(chat_id, int)

    send = test_client.post(
        f"/roles/shared/chat/messages/{chat_id}?message_text=hello%20stranger",
        headers=a_header,
    )
    assert send.status_code == 200

    inbox = test_client.get(f"/roles/shared/chat/messages/{chat_id}", headers=b_header)
    assert inbox.status_code == 200
    msgs = inbox.json()["messages"]
    assert any(m["message_text"] == "hello stranger" for m in msgs)


def test_coach_can_dm_pending_requester_before_accepting(test_client, db_session):
    coach_header, coach_me = _signup_client(test_client, "block_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    client_header, client_me = _signup_client(test_client, "block_pendclient")
    req = test_client.post(f"/roles/client/request_coach/{coach_acc.coach_id}", headers=client_header)
    assert req.status_code == 200

    # Coach DMs the requester before accepting/denying.
    res = test_client.get(f"/roles/shared/chat/by-account/{client_me['id']}", headers=coach_header)
    assert res.status_code == 200, res.text


def test_self_chat_rejected(test_client):
    header, me = _signup_client(test_client, "block_self")
    res = test_client.get(f"/roles/shared/chat/by-account/{me['id']}", headers=header)
    assert res.status_code == 400


# ─── Block tests ─────────────────────────────────────────────────────────────
def test_block_prevents_new_sends_but_keeps_history(test_client):
    a_header, a_me = _signup_client(test_client, "blockh_a")
    b_header, b_me = _signup_client(test_client, "blockh_b")

    chat = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header).json()
    chat_id = chat["chat_id"]
    test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=before%20block", headers=a_header)

    block = test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)
    assert block.status_code == 200, block.text

    # Sends rejected in either direction…
    s1 = test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=after", headers=a_header)
    s2 = test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=after", headers=b_header)
    assert s1.status_code == 403
    assert s2.status_code == 403

    # …but reads of history still work for both.
    r1 = test_client.get(f"/roles/shared/chat/messages/{chat_id}", headers=a_header)
    r2 = test_client.get(f"/roles/shared/chat/messages/{chat_id}", headers=b_header)
    assert r1.status_code == 200 and r2.status_code == 200
    assert any(m["message_text"] == "before block" for m in r1.json()["messages"])
    assert any(m["message_text"] == "before block" for m in r2.json()["messages"])


def test_unblock_restores_send_but_not_relationship(test_client, db_session):
    a_header, a_me = _signup_client(test_client, "ublock_a")
    b_header, b_me = _signup_client(test_client, "ublock_b")
    test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header)

    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)
    test_client.delete(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)

    chat_id = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header).json()["chat_id"]
    sent = test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=postunblock", headers=a_header)
    assert sent.status_code == 200


def test_client_block_terminates_active_relationship(test_client, db_session):
    coach_header, coach_me = _signup_client(test_client, "clb_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    client_header, client_me = _signup_client(test_client, "clb_client")
    client_acc = db_session.exec(select(Account).where(Account.id == client_me["id"])).first()
    request, rel = _force_active_relationship(db_session, client_acc, coach_acc)

    my_coach_before = test_client.get("/roles/client/my_coach", headers=client_header)
    assert my_coach_before.status_code == 200

    block = test_client.post(f"/roles/shared/blocks/{coach_me['id']}", headers=client_header)
    assert block.status_code == 200, block.text
    assert block.json()["cancelled_relationships"] >= 1

    db_session.refresh(rel)
    assert rel.is_active is False

    my_coach_after = test_client.get("/roles/client/my_coach", headers=client_header)
    assert my_coach_after.status_code == 404


def test_coach_cannot_block_active_client(test_client, db_session):
    coach_header, coach_me = _signup_client(test_client, "cnb_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    _, client_me = _signup_client(test_client, "cnb_client")
    client_acc = db_session.exec(select(Account).where(Account.id == client_me["id"])).first()
    _force_active_relationship(db_session, client_acc, coach_acc)

    block = test_client.post(f"/roles/shared/blocks/{client_me['id']}", headers=coach_header)
    assert block.status_code == 403, block.text


def test_coach_can_block_after_relationship_terminates(test_client, db_session):
    coach_header, coach_me = _signup_client(test_client, "cba_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    _, client_me = _signup_client(test_client, "cba_client")
    client_acc = db_session.exec(select(Account).where(Account.id == client_me["id"])).first()
    _, rel = _force_active_relationship(db_session, client_acc, coach_acc)

    rel.is_active = False
    db_session.add(rel)
    db_session.commit()

    block = test_client.post(f"/roles/shared/blocks/{client_me['id']}", headers=coach_header)
    assert block.status_code == 200


def test_list_blocks_returns_blocked_accounts(test_client):
    a_header, _ = _signup_client(test_client, "lb_a")
    _, b_me = _signup_client(test_client, "lb_b")
    _, c_me = _signup_client(test_client, "lb_c")

    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)
    test_client.post(f"/roles/shared/blocks/{c_me['id']}", headers=a_header)

    res = test_client.get("/roles/shared/blocks", headers=a_header)
    assert res.status_code == 200
    blocked_ids = {entry["account_id"] for entry in res.json()["blocked"]}
    assert {b_me["id"], c_me["id"]} <= blocked_ids


def test_block_idempotent_no_duplicate_rows(test_client, db_session):
    a_header, a_me = _signup_client(test_client, "idem_a")
    _, b_me = _signup_client(test_client, "idem_b")

    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)
    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)

    rows = db_session.exec(
        select(AccountBlock).where(
            AccountBlock.blocker_id == a_me["id"],
            AccountBlock.blockee_id == b_me["id"],
        )
    ).all()
    assert len(rows) == 1


def test_cannot_hire_self_as_coach(test_client, db_session):
    """A user who is also a coach can't hire themselves."""
    header, me = _signup_client(test_client, "selfhire")
    _promote_to_coach(test_client, header, db_session)

    me_acc = db_session.exec(select(Account).where(Account.id == me["id"])).first()
    db_session.refresh(me_acc)

    res = test_client.post(f"/roles/client/request_coach/{me_acc.coach_id}", headers=header)
    assert res.status_code == 400, res.text


def test_cannot_hire_blocked_coach(test_client, db_session):
    """request_coach is rejected if the caller has blocked the coach (or vice versa)."""
    coach_header, coach_me = _signup_client(test_client, "bhire_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    coach_acc = db_session.exec(select(Account).where(Account.id == coach_me["id"])).first()

    client_header, client_me = _signup_client(test_client, "bhire_client")

    blk = test_client.post(f"/roles/shared/blocks/{coach_me['id']}", headers=client_header)
    assert blk.status_code == 200

    res = test_client.post(f"/roles/client/request_coach/{coach_acc.coach_id}", headers=client_header)
    assert res.status_code == 403, res.text


def test_hirable_coaches_excludes_self_and_blocked(test_client, db_session):
    """The caller's own coach role and any blocked accounts are filtered out of /query/hirable_coaches."""
    coach_header, coach_me = _signup_client(test_client, "hl_coach")
    _promote_to_coach(test_client, coach_header, db_session)

    blocked_coach_header, blocked_coach_me = _signup_client(test_client, "hl_blocked_coach")
    _promote_to_coach(test_client, blocked_coach_header, db_session)

    other_coach_header, _ = _signup_client(test_client, "hl_other_coach")
    _promote_to_coach(test_client, other_coach_header, db_session)

    # The first coach (also a client) is the caller. They've blocked blocked_coach_me.
    test_client.post(f"/roles/shared/blocks/{blocked_coach_me['id']}", headers=coach_header)

    res = test_client.get("/roles/client/query/hirable_coaches", headers=coach_header)
    assert res.status_code == 200, res.text
    returned_account_ids = {row["account_id"] for row in res.json()}

    assert coach_me["id"] not in returned_account_ids  # self filtered
    assert blocked_coach_me["id"] not in returned_account_ids  # blocked filtered


def test_conversations_endpoint_returns_partner_profile(test_client, db_session):
    """Conversation list must populate partner profile (name, pfp, age, gender, role)
    so the unified Messages page can render real partner info instead of placeholders."""
    a_header, _ = _signup_client(test_client, "convp_a")
    b_header, b_me = _signup_client(test_client, "convp_b")

    # B becomes a coach so the partner profile carries role flags.
    _promote_to_coach(test_client, b_header, db_session)

    chat = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header).json()
    chat_id = chat["chat_id"]
    test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=hi%20there", headers=a_header)

    convos_resp = test_client.get("/roles/shared/chat/conversations", headers=a_header)
    assert convos_resp.status_code == 200, convos_resp.text
    convos = convos_resp.json()["conversations"]
    target = next((c for c in convos if c["chat_id"] == chat_id), None)
    assert target is not None
    assert target["partner"]["id"] == b_me["id"]
    assert target["partner"]["name"]
    assert target["partner"]["is_coach"] is True
    assert target["last_message"] == "hi there"


def test_public_account_endpoint_returns_safe_fields(test_client):
    """/roles/shared/account/public/{id} returns name/age/gender/pfp without sensitive auth fields."""
    a_header, _ = _signup_client(test_client, "pubacc_a")
    _, b_me = _signup_client(test_client, "pubacc_b")

    res = test_client.get(f"/roles/shared/account/public/{b_me['id']}", headers=a_header)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == b_me["id"]
    assert "name" in body and "age" in body and "gender" in body and "pfp_url" in body
    # Sanity: no auth/internal fields leak.
    for forbidden in ("hashed_password", "gcp_user_id"):
        assert forbidden not in body


def test_chat_partner_endpoint_returns_other_participant(test_client):
    a_header, a_me = _signup_client(test_client, "ptn_a")
    b_header, b_me = _signup_client(test_client, "ptn_b")

    chat_id = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header).json()["chat_id"]

    a_view = test_client.get(f"/roles/shared/chat/partner/{chat_id}", headers=a_header).json()
    b_view = test_client.get(f"/roles/shared/chat/partner/{chat_id}", headers=b_header).json()
    assert a_view["id"] == b_me["id"]
    assert b_view["id"] == a_me["id"]


def test_blockee_cannot_block_blocker(test_client):
    """Block enforcement is one-way: once A blocks B, B cannot block A back."""
    a_header, a_me = _signup_client(test_client, "rev_a")
    b_header, b_me = _signup_client(test_client, "rev_b")

    ok = test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)
    assert ok.status_code == 200

    retaliate = test_client.post(f"/roles/shared/blocks/{a_me['id']}", headers=b_header)
    assert retaliate.status_code == 403, retaliate.text


def test_block_status_endpoint_reflects_directions(test_client):
    """The /status/{id} probe must report block direction without any client-side state."""
    a_header, a_me = _signup_client(test_client, "stat_a")
    b_header, b_me = _signup_client(test_client, "stat_b")

    initial_a = test_client.get(f"/roles/shared/blocks/status/{b_me['id']}", headers=a_header).json()
    assert initial_a == {"partner_id": b_me["id"], "i_blocked_them": False, "they_blocked_me": False}

    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)

    a_view = test_client.get(f"/roles/shared/blocks/status/{b_me['id']}", headers=a_header).json()
    b_view = test_client.get(f"/roles/shared/blocks/status/{a_me['id']}", headers=b_header).json()
    assert a_view["i_blocked_them"] is True and a_view["they_blocked_me"] is False
    assert b_view["i_blocked_them"] is False and b_view["they_blocked_me"] is True


def test_public_account_includes_verified_coach_flag(test_client, db_session):
    """is_verified_coach must come back true only when the target has coach_id and Coach.verified=True."""
    caller_header, _ = _signup_client(test_client, "vc_caller")

    coach_header, coach_me = _signup_client(test_client, "vc_coach")
    _promote_to_coach(test_client, coach_header, db_session)
    promoted = test_client.get(f"/roles/shared/account/public/{coach_me['id']}", headers=caller_header).json()
    assert promoted["is_coach"] is True and promoted["is_verified_coach"] is True

    # Unverified coach: build the request but don't auto-verify.
    unv_header, unv_me = _signup_client(test_client, "vc_unverified")
    res = test_client.post(
        "/roles/coach/request_coach_creation",
        json=build_coach_request_payload(),
        headers=unv_header,
    )
    assert res.status_code == 200
    unverified = test_client.get(f"/roles/shared/account/public/{unv_me['id']}", headers=caller_header).json()
    assert unverified["is_coach"] is True and unverified["is_verified_coach"] is False


def test_report_endpoint_creates_account_report(test_client, db_session):
    """Generic /roles/shared/account/report/{id} stores the report and rejects self/empty/unknown targets."""
    a_header, _ = _signup_client(test_client, "rep_a")
    _, b_me = _signup_client(test_client, "rep_b")

    ok = test_client.post(
        f"/roles/shared/account/report/{b_me['id']}?reason=spammy%20behavior",
        headers=a_header,
    )
    assert ok.status_code == 200, ok.text
    assert isinstance(ok.json()["report_id"], int)

    # Empty reason rejected.
    empty = test_client.post(
        f"/roles/shared/account/report/{b_me['id']}?reason=",
        headers=a_header,
    )
    assert empty.status_code == 422

    # Self report rejected.
    me = test_client.get("/me", headers=a_header).json()
    self_report = test_client.post(
        f"/roles/shared/account/report/{me['id']}?reason=test",
        headers=a_header,
    )
    assert self_report.status_code == 400


def test_account_deletion_cascades_chats_blocks_and_messages(test_client, db_session):
    """Repro of the recent DELETE failure: adding new tables without ON DELETE CASCADE
    used to make /roles/shared/account/delete fail with FK violations."""
    a_header, a_me = _signup_client(test_client, "delc_a")
    _, b_me = _signup_client(test_client, "delc_b")

    chat_id = test_client.get(f"/roles/shared/chat/by-account/{b_me['id']}", headers=a_header).json()["chat_id"]
    test_client.post(f"/roles/shared/chat/messages/{chat_id}?message_text=hi", headers=a_header)
    test_client.post(f"/roles/shared/blocks/{b_me['id']}", headers=a_header)

    res = test_client.delete("/roles/shared/account/delete", headers=a_header)
    assert res.status_code == 200, res.text

    assert db_session.get(Account, a_me["id"]) is None

    # Cascades through the new tables.
    remaining_account_chat = db_session.exec(
        select(AccountChat).where(AccountChat.account_id == a_me["id"])
    ).all()
    assert remaining_account_chat == []

    remaining_blocks = db_session.exec(
        select(AccountBlock).where(
            (AccountBlock.blocker_id == a_me["id"]) | (AccountBlock.blockee_id == a_me["id"])
        )
    ).all()
    assert remaining_blocks == []
