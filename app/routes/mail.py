# app/routes/mail.py
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session

from app.config import ADMIN_KEY
from app.database import get_db
from app.models.mail_message import MailMessage
from app.routes.auth import get_current_user

router = APIRouter(prefix="/mail", tags=["mail"])


def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and (x_admin_key == ADMIN_KEY)


def _safe_json_loads(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None

def _augment_from_payload(d: dict) -> dict:
    """
    Adds convenience fields for the "temporary UI" (Swagger).
    If payload contains raid_id, add raid_id + report_url.
    """
    payload = d.get("payload")
    if isinstance(payload, dict):
        raid_id = payload.get("raid_id")
        if isinstance(raid_id, int) and raid_id > 0:
            d["raid_id"] = raid_id
            d["report_url"] = f"/raids/{raid_id}/report.html"
            d["report_json_url"] = f"/raids/{raid_id}/report"
    return d

def _to_dict(m: MailMessage) -> dict:
    d = {
        "id": int(m.id),
        "user_id": int(m.user_id),
        "kind": m.kind,
        "subject": m.subject,
        "body": m.body,
        "payload": _safe_json_loads(getattr(m, "payload_json", None)),
        "is_read": bool(int(getattr(m, "is_read", 0) or 0)),
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "read_at": m.read_at.isoformat() if m.read_at else None,
    }
    return _augment_from_payload(d)

def _resolve_target_user_id(
    *,
    current_user_id: int,
    requested_user_id: int | None,
    x_admin_key: str | None,
) -> int:
    """
    Normal users: always their own user_id.
    Admin: can request another inbox via ?user_id=...
    """
    if requested_user_id is None:
        return int(current_user_id)

    if not _is_admin(x_admin_key):
        # don't leak whether user_id exists
        return int(current_user_id)

    return int(requested_user_id)

@router.get("/inbox")
def inbox(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    limit: int = Query(50, ge=1, le=500),
    unread_only: bool = Query(False),
    kind: Optional[str] = Query(None),
    before_id: Optional[int] = Query(None, ge=1),
    user_id: Optional[int] = Query(
        None,
        description="Admin only: view another user's inbox",
        ge=1,
    ),
) -> dict:
    """
    Returns the current user's inbox (newest first).
    Admin can pass ?user_id=... to view other inboxes.
    Supports pagination via ?before_id=...
    """
    target_user_id = _resolve_target_user_id(
        current_user_id=int(current_user.id),
        requested_user_id=user_id,
        x_admin_key=x_admin_key,
    )

    q = db.query(MailMessage).filter(MailMessage.user_id == int(target_user_id))

    if unread_only:
        q = q.filter(MailMessage.is_read == 0)

    if kind:
        q = q.filter(MailMessage.kind == kind)

    if before_id is not None:
        q = q.filter(MailMessage.id < int(before_id))

    msgs = q.order_by(MailMessage.id.desc()).limit(limit).all()

    return {
        "messages": [_to_dict(m) for m in msgs],
        "count": len(msgs),
        "next_before_id": (int(msgs[-1].id) if msgs else None),
        "user_id": int(target_user_id),
    }


@router.get("/unread_count")
def unread_count(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    kind: Optional[str] = Query(None),
    user_id: Optional[int] = Query(
        None,
        description="Admin only: view another user's unread count",
        ge=1,
    ),
) -> dict:
    """
    Returns unread count for the current user.
    Admin can pass ?user_id=... to view other users.
    """
    target_user_id = _resolve_target_user_id(
        current_user_id=int(current_user.id),
        requested_user_id=user_id,
        x_admin_key=x_admin_key,
    )

    q = (
        db.query(MailMessage)
        .filter(MailMessage.user_id == int(target_user_id))
        .filter(MailMessage.is_read == 0)
    )

    if kind:
        q = q.filter(MailMessage.kind == kind)

    # count() is fine for sqlite here
    return {
        "user_id": int(target_user_id),
        "kind": kind,
        "unread": int(q.count()),
    }

@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    user_id: Optional[int] = Query(None, ge=1, description="Admin only: view another user's mail summary"),
    kind: Optional[str] = Query(None, description="Optional: scope latest to this kind"),
) -> dict:
    target_user_id = _resolve_target_user_id(
        current_user_id=int(current_user.id),
        requested_user_id=user_id,
        x_admin_key=x_admin_key,
    )

    # unread total
    q_unread = db.query(MailMessage).filter(
        MailMessage.user_id == int(target_user_id),
        MailMessage.is_read == 0,
    )
    unread_total = int(q_unread.count())

    # latest (optionally by kind)
    q_latest = db.query(MailMessage).filter(MailMessage.user_id == int(target_user_id))
    if kind:
        q_latest = q_latest.filter(MailMessage.kind == kind)
    latest = q_latest.order_by(MailMessage.id.desc()).first()

    return {
        "user_id": int(target_user_id),
        "unread_total": unread_total,
        "latest": (_to_dict(latest) if latest else None),
    }

@router.get("/latest")
def latest(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    kind: Optional[str] = Query(None),
) -> dict:
    q = db.query(MailMessage).filter(MailMessage.user_id == int(current_user.id))
    if kind:
        q = q.filter(MailMessage.kind == kind)

    msg = q.order_by(MailMessage.id.desc()).first()
    if not msg:
        raise HTTPException(status_code=404, detail="No messages")

    return _to_dict(msg)

@router.get("/{message_id}")
def read_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    msg = db.query(MailMessage).filter(MailMessage.id == int(message_id)).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Ownership gate (admin can bypass)
    if (not _is_admin(x_admin_key)) and int(msg.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Message not found")

    return _to_dict(msg)


@router.post("/{message_id}/read")
def mark_read(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    msg = db.query(MailMessage).filter(MailMessage.id == int(message_id)).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if (not _is_admin(x_admin_key)) and int(msg.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Message not found")

    if int(getattr(msg, "is_read", 0) or 0) == 0:
        msg.is_read = 1
        msg.read_at = datetime.utcnow()
        db.commit()
        db.refresh(msg)

    return {"ok": True, "message": _to_dict(msg)}

@router.post("/{message_id}/unread")
def mark_unread(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    msg = db.query(MailMessage).filter(MailMessage.id == int(message_id)).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if (not _is_admin(x_admin_key)) and int(msg.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Message not found")

    msg.is_read = 0
    msg.read_at = None

    db.commit()
    db.refresh(msg)
    return {"ok": True, "message": _to_dict(msg)}

@router.delete("/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    msg = db.query(MailMessage).filter(MailMessage.id == int(message_id)).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if (not _is_admin(x_admin_key)) and int(msg.user_id) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Message not found")

    db.delete(msg)
    db.commit()
    return {"ok": True, "deleted_id": int(message_id)}

@router.post("/read_all")
def read_all(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    kind: Optional[str] = Query(None),
) -> dict:

    q = db.query(MailMessage).filter(
        MailMessage.user_id == int(current_user.id),
        MailMessage.is_read == 0,
    )
    if kind:
        q = q.filter(MailMessage.kind == kind)

    # SQLite-friendly bulk update
    n = 0
    for msg in q.all():
        msg.is_read = 1
        msg.read_at = datetime.utcnow()
        n += 1

    db.commit()
    return {"ok": True, "marked_read": n}
