# app/models/mail_message.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, Text, DateTime
from app.database import Base


class MailMessage(Base):
    __tablename__ = "mail_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)

    kind = Column(Text, nullable=False)        # e.g. "raid_report"
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=True) # optional JSON string

    is_read = Column(Integer, nullable=False, default=0)  # 0/1 for sqlite
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
