import csv
import io
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import cast, func, String
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..schemas import DashboardStats

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Document.id)).scalar() or 0
    pending = (
        db.query(func.count(Document.id))
        .filter(Document.needs_review.is_(True))
        .scalar()
        or 0
    )
    reviewed = (
        db.query(func.count(Document.id))
        .filter(Document.status == "reviewed")
        .scalar()
        or 0
    )
    total_sales = (
        db.query(func.sum(Document.grand_total))
        .filter(Document.status == "reviewed")
        .scalar()
        or 0.0
    )
    avg_conf = (
        db.query(func.avg(Document.confidence))
        .filter(Document.confidence.isnot(None))
        .scalar()
        or 0.0
    )

    today = datetime.now(UTC).date()
    today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    docs_today = (
        db.query(func.count(Document.id))
        .filter(Document.uploaded_at >= today_start)
        .scalar()
        or 0
    )

    return DashboardStats(
        total_documents=total,
        pending_review=pending,
        reviewed=reviewed,
        total_sales=round(float(total_sales), 2),
        avg_confidence=round(float(avg_conf), 4),
        documents_today=docs_today,
    )


@router.get("/daily-sales")
def daily_sales(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Sales aggregated by document_date for the last N days."""
    rows = (
        db.query(
            Document.document_date,
            func.sum(Document.grand_total).label("total"),
            func.count(Document.id).label("count"),
        )
        .filter(
            Document.status == "reviewed",
            Document.document_date.isnot(None),
        )
        .group_by(Document.document_date)
        .order_by(Document.document_date.desc())
        .limit(days)
        .all()
    )
    return [
        {"date": r.document_date, "total": round(float(r.total), 2), "count": r.count}
        for r in reversed(rows)
    ]


@router.get("/top-merchants")
def top_merchants(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Top merchants by total sales amount."""
    rows = (
        db.query(
            Document.merchant_name,
            func.sum(Document.grand_total).label("total"),
            func.count(Document.id).label("count"),
        )
        .filter(
            Document.status == "reviewed",
            Document.merchant_name.isnot(None),
        )
        .group_by(Document.merchant_name)
        .order_by(func.sum(Document.grand_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {"merchant": r.merchant_name, "total": round(float(r.total), 2), "count": r.count}
        for r in rows
    ]


@router.get("/category-breakdown")
def category_breakdown(db: Session = Depends(get_db)):
    """Spending breakdown by category."""
    rows = (
        db.query(
            Document.category,
            func.sum(Document.grand_total).label("total"),
            func.count(Document.id).label("count"),
        )
        .filter(
            Document.status == "reviewed",
            Document.category.isnot(None),
        )
        .group_by(Document.category)
        .order_by(func.sum(Document.grand_total).desc())
        .all()
    )
    return [
        {"category": r.category, "total": round(float(r.total), 2), "count": r.count}
        for r in rows
    ]


@router.get("/vat-summary")
def vat_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    """VAT summary aggregated by month."""
    query = db.query(
        func.substr(Document.document_date, 1, 7).label("month"),
        func.sum(Document.subtotal).label("subtotal"),
        func.sum(Document.vat).label("vat"),
        func.sum(Document.grand_total).label("grand_total"),
        func.count(Document.id).label("count"),
    ).filter(
        Document.status == "reviewed",
        Document.document_date.isnot(None),
        Document.vat.isnot(None),
    )

    if date_from:
        query = query.filter(Document.document_date >= date_from)
    if date_to:
        query = query.filter(Document.document_date <= date_to)

    rows = (
        query
        .group_by(func.substr(Document.document_date, 1, 7))
        .order_by(func.substr(Document.document_date, 1, 7).desc())
        .all()
    )

    total_vat = sum(float(r.vat or 0) for r in rows)
    total_subtotal = sum(float(r.subtotal or 0) for r in rows)
    total_grand = sum(float(r.grand_total or 0) for r in rows)
    total_count = sum(r.count for r in rows)

    return {
        "months": [
            {
                "month": r.month,
                "subtotal": round(float(r.subtotal or 0), 2),
                "vat": round(float(r.vat or 0), 2),
                "grand_total": round(float(r.grand_total or 0), 2),
                "count": r.count,
            }
            for r in rows
        ],
        "totals": {
            "subtotal": round(total_subtotal, 2),
            "vat": round(total_vat, 2),
            "grand_total": round(total_grand, 2),
            "count": total_count,
        },
    }


@router.get("/fraud-summary")
def fraud_summary(db: Session = Depends(get_db)):
    """Summary of fraud-flagged documents."""
    flagged_docs = (
        db.query(Document)
        .filter(
            Document.fraud_flags.isnot(None),
            Document.fraud_flags != "null",
            Document.fraud_flags != "[]",
        )
        .all()
    )

    total_flagged = len(flagged_docs)
    by_severity = {"high": 0, "medium": 0, "low": 0}
    by_type: dict[str, int] = {}
    flagged_items = []

    for doc in flagged_docs:
        try:
            raw = json.loads(doc.fraud_flags)
        except (json.JSONDecodeError, TypeError):
            continue

        # Support both old (list) and new ({flags, ai_analysis}) formats
        if isinstance(raw, list):
            flags = raw
            ai_analysis = None
        else:
            flags = raw.get("flags", [])
            ai_analysis = raw.get("ai_analysis")

        if not flags and not ai_analysis:
            continue

        max_severity = "low"
        flag_labels = []
        for flag in flags:
            sev = flag.get("severity", "low")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            ftype = flag.get("type", "unknown")
            by_type[ftype] = by_type.get(ftype, 0) + 1
            flag_labels.append(flag.get("label", ftype))
            if sev == "high":
                max_severity = "high"
            elif sev == "medium" and max_severity != "high":
                max_severity = "medium"

        if ai_analysis and ai_analysis.get("risk_level") == "high":
            max_severity = "high"
        elif ai_analysis and ai_analysis.get("risk_level") == "medium" and max_severity != "high":
            max_severity = "medium"

        flagged_items.append({
            "id": doc.id,
            "filename": doc.filename,
            "merchant_name": doc.merchant_name,
            "grand_total": float(doc.grand_total) if doc.grand_total else None,
            "document_date": doc.document_date,
            "severity": max_severity,
            "flags": flag_labels,
            "flag_count": len(flags),
            "risk_score": ai_analysis.get("risk_score") if ai_analysis else None,
            "ai_summary": ai_analysis.get("summary") if ai_analysis else None,
        })

    # Sort by severity (high first)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    flagged_items.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return {
        "total_flagged": total_flagged,
        "by_severity": by_severity,
        "by_type": [
            {"type": k, "count": v}
            for k, v in sorted(by_type.items(), key=lambda x: -x[1])
        ],
        "documents": flagged_items[:20],
    }


@router.get("/spending-heatmap")
def spending_heatmap(
    days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
):
    """Daily spending amounts for heatmap visualization."""
    rows = (
        db.query(
            Document.document_date,
            func.sum(Document.grand_total).label("total"),
            func.count(Document.id).label("count"),
        )
        .filter(
            Document.document_date.isnot(None),
            Document.grand_total.isnot(None),
            Document.status.in_(["extracted", "reviewed"]),
        )
        .group_by(Document.document_date)
        .order_by(Document.document_date)
        .all()
    )

    # Build a map of all dates with data
    data = {}
    for r in rows:
        if r.document_date:
            data[r.document_date] = {
                "date": r.document_date,
                "total": round(float(r.total), 2),
                "count": r.count,
            }

    # Fill in missing dates with zeros for the requested range
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days)
    result = []
    current = start
    while current <= today:
        date_str = current.strftime("%Y-%m-%d")
        if date_str in data:
            result.append(data[date_str])
        else:
            result.append({"date": date_str, "total": 0, "count": 0})
        current += timedelta(days=1)

    return result


@router.get("/export")
def export_csv(
    date_from: str | None = None,
    date_to: str | None = None,
    merchant: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Document).filter(Document.status == "reviewed")

    if date_from:
        query = query.filter(Document.document_date >= date_from)
    if date_to:
        query = query.filter(Document.document_date <= date_to)
    if merchant:
        query = query.filter(Document.merchant_name.ilike(f"%{merchant}%"))

    docs = query.order_by(Document.document_date).all()

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM for Excel Thai support
    writer = csv.writer(buf)
    writer.writerow(
        [
            "เลขที่เอกสาร",
            "วันที่",
            "ร้านค้า",
            "หมวดหมู่",
            "ชื่อสินค้า",
            "จำนวน",
            "หน่วย",
            "ราคาต่อหน่วย",
            "ยอดรายการ",
            "ยอดรวมก่อนภาษี",
            "ส่วนลด",
            "VAT",
            "ยอดสุทธิ",
        ]
    )

    for doc in docs:
        for item in doc.items:
            writer.writerow(
                [
                    doc.document_number or "",
                    doc.document_date or "",
                    doc.merchant_name or "",
                    doc.category or "",
                    item.product_name_raw or "",
                    item.quantity or "",
                    item.unit or "",
                    item.unit_price or "",
                    item.line_total or "",
                    doc.subtotal or "",
                    doc.discount or "",
                    doc.vat or "",
                    doc.grand_total or "",
                ]
            )

    buf.seek(0)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales_export.csv"},
    )
