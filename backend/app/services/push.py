"""Web Push notification service.

Sends push notifications to all enabled `PushSubscription` rows. Subscriptions
that return 404/410 from the push service are auto-disabled (endpoint expired).
Failures for other reasons are logged but do not raise — we never want a fraud
flag to fail because a push service was flaky.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PushSubscription

logger = logging.getLogger(__name__)


@dataclass
class PushPayload:
    title: str
    body: str
    url: str = "/"
    tag: str | None = None
    icon: str | None = None
    badge: str | None = None


def _vapid_claims() -> dict[str, str]:
    return {"sub": settings.vapid_subject}


def _is_configured() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def send_to_all(db: Session, payload: PushPayload) -> int:
    """Send a notification to every enabled subscription. Returns count delivered."""
    if not _is_configured():
        logger.debug("VAPID not configured — skipping push send")
        return 0

    subs = db.query(PushSubscription).filter(PushSubscription.enabled.is_(True)).all()
    if not subs:
        return 0

    body = json.dumps(
        {
            "title": payload.title,
            "body": payload.body,
            "url": payload.url,
            "tag": payload.tag,
            "icon": payload.icon,
            "badge": payload.badge,
        },
        ensure_ascii=False,
    )

    delivered = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=body,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims=_vapid_claims(),
            )
            sub.last_used_at = datetime.now(UTC)
            delivered += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response is not None else None
            if status in (404, 410):
                logger.info("Disabling expired push subscription %s (status=%s)", sub.id, status)
                sub.enabled = False
            else:
                logger.warning("Push send failed for %s: %s (status=%s)", sub.id, exc, status)
        except Exception as exc:  # noqa: BLE001 — never let push kill the caller
            logger.warning("Unexpected push error for %s: %s", sub.id, exc)

    db.commit()
    return delivered
