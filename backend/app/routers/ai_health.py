"""AI-health observability endpoints.

Catalog gaps and typo recoveries used to live under /api/dashboard but the
dashboard was removed in the visit pivot. These two endpoints are kept
because they drive the catalog-growth workflow (which gaps and typos the
model accumulates over time).
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CatalogGapEvent, TypoRecoveryEvent

router = APIRouter()


@router.get("/catalog-gaps")
def catalog_gaps(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Top recurring catalog gaps from Gemini's product_code emissions."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    rows = (
        db.query(
            CatalogGapEvent.emitted_code,
            CatalogGapEvent.product_name,
            func.count(CatalogGapEvent.id).label("hit_count"),
            func.max(CatalogGapEvent.seen_at).label("last_seen"),
        )
        .filter(CatalogGapEvent.seen_at >= cutoff)
        .filter(CatalogGapEvent.resolved_at.is_(None))
        .group_by(CatalogGapEvent.emitted_code, CatalogGapEvent.product_name)
        .order_by(func.count(CatalogGapEvent.id).desc())
        .limit(limit)
        .all()
    )

    return {
        "window_days": days,
        "gaps": [
            {
                "emitted_code": r.emitted_code,
                "product_name": r.product_name,
                "hit_count": r.hit_count,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ],
    }


@router.get("/typo-recoveries")
def typo_recoveries(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Recurring typo recoveries — Gemini emits a wrong product_code but the
    name matches catalog so we recover."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    rows = (
        db.query(
            TypoRecoveryEvent.emitted_code,
            TypoRecoveryEvent.recovered_code,
            TypoRecoveryEvent.product_name,
            func.count(TypoRecoveryEvent.id).label("hit_count"),
            func.max(TypoRecoveryEvent.seen_at).label("last_seen"),
        )
        .filter(TypoRecoveryEvent.seen_at >= cutoff)
        .group_by(
            TypoRecoveryEvent.emitted_code,
            TypoRecoveryEvent.recovered_code,
            TypoRecoveryEvent.product_name,
        )
        .order_by(func.count(TypoRecoveryEvent.id).desc())
        .limit(limit)
        .all()
    )

    return {
        "window_days": days,
        "recoveries": [
            {
                "emitted_code": r.emitted_code,
                "recovered_code": r.recovered_code,
                "product_name": r.product_name,
                "hit_count": r.hit_count,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            }
            for r in rows
        ],
    }
