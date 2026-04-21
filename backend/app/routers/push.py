"""Web Push subscription endpoints + manual trigger (for testing)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import PushSubscription
from ..services.push import PushPayload, send_to_all

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionPayload(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class TestPushPayload(BaseModel):
    title: str = "ทดสอบ"
    body: str = "ข้อความทดสอบ Web Push"
    url: str = "/"


@router.get("/public-key")
def public_key():
    if not settings.vapid_public_key:
        raise HTTPException(503, "Push service ไม่ได้ตั้งค่า")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
def subscribe(
    payload: SubscriptionPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == payload.endpoint)
        .first()
    )
    ua = request.headers.get("user-agent")
    if existing:
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        existing.user_agent = ua
        existing.enabled = True
        existing.last_used_at = datetime.now(UTC)
        db.commit()
        return {"id": existing.id, "status": "updated"}

    sub = PushSubscription(
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=ua,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    logger.info("New push subscription %s", sub.id)
    return {"id": sub.id, "status": "created"}


@router.post("/unsubscribe")
def unsubscribe(payload: dict, db: Session = Depends(get_db)):
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(400, "ต้องระบุ endpoint")
    sub = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .first()
    )
    if sub:
        db.delete(sub)
        db.commit()
    return {"status": "ok"}


@router.post("/test")
def send_test(payload: TestPushPayload, db: Session = Depends(get_db)):
    """Trigger a test notification to all subscribers. Useful for demo + debugging."""
    delivered = send_to_all(
        db,
        PushPayload(title=payload.title, body=payload.body, url=payload.url, tag="test"),
    )
    return {"delivered": delivered}
