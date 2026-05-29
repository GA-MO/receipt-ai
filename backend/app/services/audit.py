"""Append-only audit trail for documents.

Usage is intentionally dead-simple — call :func:`record` in every code path
that mutates a document. Never raises: audit failures must not break the
real operation.

Common ``event_type`` values (free-form strings):
    uploaded, extracted, extraction_failed, edited,
    item_added, item_updated, item_deleted,
    approved, reextracted, trashed, restored, purged,
    alias_learned.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import DocumentEvent

logger = logging.getLogger(__name__)


def record(
    db: Session,
    document_id: str,
    event_type: str,
    *,
    actor: str = "user",
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Append one event row. Never raises.

    Set ``commit=False`` when the caller is already in the middle of a unit
    of work and will commit later; the row is flushed but not committed.
    """
    try:
        evt = DocumentEvent(
            document_id=document_id,
            event_type=event_type,
            actor=actor,
            payload=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        )
        db.add(evt)
        if commit:
            db.commit()
    except Exception as exc:  # noqa: BLE001 — audit must never break callers
        logger.warning("Failed to record event %s for %s: %s", event_type, document_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
