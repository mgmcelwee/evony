# app/game/mailbox.py
from __future__ import annotations

import json
from sqlalchemy.orm import Session
from app.models.mail_message import MailMessage


def send_mail(
    db: Session,
    *,
    user_id: int,
    kind: str,
    subject: str,
    body: str,
    payload: dict | None = None,
) -> MailMessage:
    msg = MailMessage(
        user_id=int(user_id),
        kind=str(kind),
        subject=str(subject),
        body=str(body),
        payload_json=(json.dumps(payload) if payload is not None else None),
        is_read=0,
    )
    db.add(msg)
    db.flush()
    return msg
