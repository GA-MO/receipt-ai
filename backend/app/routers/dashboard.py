import csv
import io
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from google.genai import types
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Document, DocumentItem
from ..schemas import DashboardStats

logger = logging.getLogger(__name__)

router = APIRouter()


def _period_bounds(period: str) -> tuple[str, str, str, str]:
    """Return (this_start, this_end, prev_start, prev_end) as yyyy-mm-dd strings.

    Period values:
        - ``"7d"``  — last 7 days vs prior 7 days
        - ``"30d"`` — last 30 days vs prior 30 days
        - ``"month"`` — this calendar month vs last calendar month
        - ``"year"``  — this year vs last year
    """
    today = datetime.now(UTC).date()
    if period == "month":
        this_start = today.replace(day=1)
        # Last day of previous month
        prev_end = this_start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        this_end = today
    elif period == "year":
        this_start = today.replace(month=1, day=1)
        prev_start = this_start.replace(year=this_start.year - 1)
        prev_end = this_start - timedelta(days=1)
        this_end = today
    else:
        # 7d / 30d / generic N-day window
        n_days = 30 if period == "30d" else 7
        this_start = today - timedelta(days=n_days - 1)
        this_end = today
        prev_end = this_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=n_days - 1)

    return (
        this_start.isoformat(),
        this_end.isoformat(),
        prev_start.isoformat(),
        prev_end.isoformat(),
    )


def _aggregate_period(
    db: Session,
    start: str,
    end: str,
) -> dict[str, float | int]:
    """Sum grand_total + count documents in [start, end] inclusive."""
    q = db.query(
        func.coalesce(func.sum(Document.grand_total), 0).label("total"),
        func.count(Document.id).label("count"),
    ).filter(
        Document.document_date.isnot(None),
        Document.document_date >= start,
        Document.document_date <= end,
    )
    row = q.one()
    return {"total": round(float(row.total or 0), 2), "count": int(row.count or 0)}


@router.get("/period-comparison")
def period_comparison(
    period: str = Query("month", pattern="^(7d|30d|month|year)$"),
    db: Session = Depends(get_db),
):
    """Compare the current period vs the previous one.

    Returns totals, counts, and deltas so the dashboard can render a clean
    "this month vs last month" card without extra math on the client.
    """
    this_start, this_end, prev_start, prev_end = _period_bounds(period)
    this_bucket = _aggregate_period(db, this_start, this_end)
    prev_bucket = _aggregate_period(db, prev_start, prev_end)

    def _pct(new: float, old: float) -> float | None:
        if old == 0:
            return None
        return round((new - old) / old * 100, 1)

    return {
        "period": period,
        "current": {"start": this_start, "end": this_end, **this_bucket},
        "previous": {"start": prev_start, "end": prev_end, **prev_bucket},
        "delta": {
            "total_abs": round(this_bucket["total"] - prev_bucket["total"], 2),
            "total_pct": _pct(this_bucket["total"], prev_bucket["total"]),
            "count_abs": this_bucket["count"] - prev_bucket["count"],
            "count_pct": _pct(this_bucket["count"], prev_bucket["count"]),
        },
    }


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


@router.get("/top-products")
def top_products(
    limit: int = Query(10, ge=1, le=50),
    date_from: str | None = None,
    date_to: str | None = None,
    catalog_only: bool = False,
    db: Session = Depends(get_db),
):
    """Top products by total revenue (sum of line_total).

    Groups items by ``product_code`` when present (catalog SKU) so name
    variations of the same product aggregate together; falls back to
    ``product_name_normalized`` for items not linked to any catalog entry.

    Pass ``catalog_only=true`` to exclude off-catalog items entirely.
    """
    # COALESCE(product_code, "free:" || name) gives us a stable grouping key
    # that keeps catalog SKUs crisp while still surfacing popular free-text
    # items. The ``free:`` prefix guarantees no collision with real codes.
    group_key = func.coalesce(
        DocumentItem.product_code,
        func.concat("free:", DocumentItem.product_name_normalized),
    ).label("key")

    q = (
        db.query(
            group_key,
            DocumentItem.product_code.label("product_code"),
            func.max(DocumentItem.product_name_normalized).label("product"),
            func.sum(DocumentItem.line_total).label("total"),
            func.sum(DocumentItem.quantity).label("quantity"),
            func.count(func.distinct(DocumentItem.document_id)).label("doc_count"),
        )
        .join(Document, DocumentItem.document_id == Document.id)
        .filter(
            Document.deleted_at.is_(None),
            Document.status.in_(("reviewed", "extracted")),
            DocumentItem.product_name_normalized.isnot(None),
            DocumentItem.product_name_normalized != "",
            DocumentItem.line_total.isnot(None),
        )
    )
    if date_from:
        q = q.filter(Document.document_date >= date_from)
    if date_to:
        q = q.filter(Document.document_date <= date_to)
    if catalog_only:
        q = q.filter(DocumentItem.product_code.isnot(None))

    rows = (
        q.group_by(group_key, DocumentItem.product_code)
        .order_by(func.sum(DocumentItem.line_total).desc())
        .limit(limit)
        .all()
    )

    # For rows with a product_code, replace the "whatever users saved" product
    # name with the canonical display_name from the catalog so the dashboard
    # reads cleanly even if operators entered inconsistent spellings.
    from ..models import Product  # local to avoid cycle

    codes = {r.product_code for r in rows if r.product_code}
    # {code: (display_name, manufacturer)}
    catalog_meta: dict[str, tuple[str, str | None]] = {}
    if codes:
        lookup_rows = (
            db.query(
                Product.code,
                Product.display_name,
                Product.canonical_name,
                Product.manufacturer,
            )
            .filter(Product.code.in_(codes))
            .all()
        )
        for code, display, canon, mfg in lookup_rows:
            catalog_meta[code] = (display or canon, mfg)

    return [
        {
            "product": catalog_meta.get(r.product_code, (r.product, None))[0],
            "product_code": r.product_code,
            "manufacturer": catalog_meta.get(r.product_code, (None, None))[1],
            "is_boonrawd": (catalog_meta.get(r.product_code, (None, None))[1] == "Boonrawd"),
            "in_catalog": r.product_code is not None,
            "total": round(float(r.total or 0), 2),
            "quantity": round(float(r.quantity or 0), 2),
            "doc_count": int(r.doc_count or 0),
        }
        for r in rows
    ]


@router.get("/top-merchants")
def top_merchants(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Top merchants by total sales amount (grouped by normalized merchant name)."""
    # Use normalized name when available, falling back to the raw name so older
    # records pre-normalization still show up.
    group_name = func.coalesce(
        Document.merchant_normalized, Document.merchant_name
    ).label("merchant")

    rows = (
        db.query(
            group_name,
            func.sum(Document.grand_total).label("total"),
            func.count(Document.id).label("count"),
        )
        .filter(
            Document.status == "reviewed",
            Document.merchant_name.isnot(None),
        )
        .group_by(group_name)
        .order_by(func.sum(Document.grand_total).desc())
        .limit(limit)
        .all()
    )
    return [
        {"merchant": r.merchant, "total": round(float(r.total), 2), "count": r.count}
        for r in rows
    ]


@router.get("/category-breakdown")
def category_breakdown(
    mode: str = Query("item", pattern="^(item|document)$"),
    db: Session = Depends(get_db),
):
    """Spending breakdown by category.

    ``mode=item`` (default) aggregates ``DocumentItem.line_total`` per
    ``DocumentItem.category`` — more accurate when a single receipt mixes
    categories (e.g. beer + food).

    ``mode=document`` aggregates ``Document.grand_total`` per
    ``Document.category`` — legacy behavior, one category per receipt.
    """
    if mode == "document":
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
    else:
        rows = (
            db.query(
                DocumentItem.category,
                func.sum(DocumentItem.line_total).label("total"),
                func.count(DocumentItem.id).label("count"),
            )
            .join(Document, DocumentItem.document_id == Document.id)
            .filter(
                Document.status == "reviewed",
                DocumentItem.category.isnot(None),
                DocumentItem.line_total.isnot(None),
            )
            .group_by(DocumentItem.category)
            .order_by(func.sum(DocumentItem.line_total).desc())
            .all()
        )
    return [
        {"category": r.category, "total": round(float(r.total or 0), 2), "count": r.count}
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


AI_INSIGHT_PROMPT = """\
คุณเป็นนักวิเคราะห์ธุรกิจ วิเคราะห์ข้อมูลยอดขายต่อไปนี้และสรุปเป็นภาษาไทย:

วันที่วันนี้: {today}

## สถิติรวม
- เอกสารทั้งหมด: {total_docs} ฉบับ
- ตรวจสอบแล้ว: {reviewed} ฉบับ
- ยอดขายรวม: ฿{total_sales:,.2f}

## ยอดขายรายวัน (10 วันล่าสุด)
{daily_sales}

## ร้านค้ายอดสูงสุด
{top_merchants}

## สัดส่วนหมวดสินค้า
{categories}

## Fraud Summary
- เอกสารที่ถูก flag: {fraud_count} ฉบับ

กรุณาตอบเป็น JSON:
{{
  "headline": "สรุป 1 ประโยคสั้นๆ กระชับ ไม่เกิน 20 คำ",
  "insights": [
    "insight สั้นๆ ไม่เกิน 15 คำ",
    "insight สั้นๆ ไม่เกิน 15 คำ",
    "insight สั้นๆ ไม่เกิน 15 คำ"
  ],
  "risks": ["ความเสี่ยงสั้นๆ ไม่เกิน 10 คำ (ถ้ามี)"],
  "opportunities": ["โอกาสสั้นๆ ไม่เกิน 10 คำ (ถ้ามี)"],
  "trends": ["แนวโน้มสั้นๆ ไม่เกิน 10 คำ (ถ้ามี) — เช่น หมวดที่เพิ่ม/ลด, pattern การใช้จ่าย"]
}}

กฎสำคัญ:
- ข้อความทุกอันต้องสั้น กระชับ อ่านปั๊บเข้าใจเลย
- insights ไม่เกิน 3 ข้อ, risks ไม่เกิน 2, opportunities ไม่เกิน 2, trends ไม่เกิน 2
- risks = สิ่งที่อาจกระทบ margin/operations, opportunities = ช่องทางประหยัด/เพิ่มรายได้, trends = pattern ที่สังเกตได้ในข้อมูล
- ถ้าไม่มี risk/opportunity/trend ให้เป็น []
- เน้นตัวเลขและ % เทียบ เช่น "ยอดเบียร์คิดเป็น 60% ของยอดทั้งหมด"
- ตอบเป็น JSON เท่านั้น
"""


@router.get("/ai-insight")
def ai_insight(db: Session = Depends(get_db)):
    """Generate AI-powered business insight from current data."""
    from ..services.extraction import _get_client

    total = db.query(func.count(Document.id)).scalar() or 0
    reviewed = db.query(func.count(Document.id)).filter(Document.status == "reviewed").scalar() or 0
    total_sales = float(
        db.query(func.sum(Document.grand_total))
        .filter(Document.grand_total.isnot(None))
        .scalar() or 0
    )

    daily = (
        db.query(Document.document_date, func.sum(Document.grand_total).label("total"), func.count(Document.id).label("count"))
        .filter(Document.document_date.isnot(None), Document.grand_total.isnot(None))
        .group_by(Document.document_date)
        .order_by(Document.document_date.desc())
        .limit(10)
        .all()
    )
    daily_str = "\n".join(f"- {r.document_date}: ฿{float(r.total):,.2f} ({r.count} เอกสาร)" for r in reversed(daily)) or "ไม่มีข้อมูล"

    merchants = (
        db.query(Document.merchant_name, func.sum(Document.grand_total).label("total"), func.count(Document.id).label("count"))
        .filter(Document.merchant_name.isnot(None), Document.grand_total.isnot(None))
        .group_by(Document.merchant_name)
        .order_by(func.sum(Document.grand_total).desc())
        .limit(5)
        .all()
    )
    merchants_str = "\n".join(f"- {r.merchant_name}: ฿{float(r.total):,.2f} ({r.count} เอกสาร)" for r in merchants) or "ไม่มีข้อมูล"

    cats = (
        db.query(Document.category, func.sum(Document.grand_total).label("total"), func.count(Document.id).label("count"))
        .filter(Document.category.isnot(None), Document.grand_total.isnot(None))
        .group_by(Document.category)
        .order_by(func.sum(Document.grand_total).desc())
        .all()
    )
    cats_str = "\n".join(f"- {r.category}: ฿{float(r.total):,.2f} ({r.count} เอกสาร)" for r in cats) or "ไม่มีข้อมูล"

    fraud_count = (
        db.query(func.count(Document.id))
        .filter(Document.fraud_flags.isnot(None), Document.fraud_flags != "null", Document.fraud_flags != "[]")
        .scalar() or 0
    )

    prompt = AI_INSIGHT_PROMPT.format(
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        total_docs=total,
        reviewed=reviewed,
        total_sales=total_sales,
        daily_sales=daily_str,
        top_merchants=merchants_str,
        categories=cats_str,
        fraud_count=fraud_count,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text.strip())
        data.setdefault("trends", [])
        data["doc_count"] = total
        data["generated_at"] = datetime.now(UTC).isoformat()
        logger.info("AI insight generated successfully")
        return data
    except Exception as exc:
        logger.warning("AI insight failed: %s", exc)
        return {
            "headline": "ไม่สามารถสร้าง insight ได้ในขณะนี้",
            "insights": [],
            "risks": [],
            "opportunities": [],
            "trends": [],
            "doc_count": total,
            "generated_at": datetime.now(UTC).isoformat(),
        }


def _fmt_num(v) -> str:
    """Format Numeric/float for CSV; empty string for None."""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _write_line_items(writer: csv.writer, docs: list[Document]) -> None:
    writer.writerow(
        [
            "เลขที่เอกสาร",
            "วันที่",
            "ร้านค้า",
            "ร้านค้า (canonical)",
            "หมวดเอกสาร",
            "ชื่อสินค้า",
            "หมวดสินค้า",
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
        if not doc.items:
            writer.writerow(
                [
                    doc.document_number or "",
                    doc.document_date or "",
                    doc.merchant_name or "",
                    doc.merchant_normalized or "",
                    doc.category or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    _fmt_num(doc.subtotal),
                    _fmt_num(doc.discount),
                    _fmt_num(doc.vat),
                    _fmt_num(doc.grand_total),
                ]
            )
            continue
        for item in doc.items:
            writer.writerow(
                [
                    doc.document_number or "",
                    doc.document_date or "",
                    doc.merchant_name or "",
                    doc.merchant_normalized or "",
                    doc.category or "",
                    item.product_name_normalized or "",
                    item.category or "",
                    _fmt_num(item.quantity),
                    item.unit or "",
                    _fmt_num(item.unit_price),
                    _fmt_num(item.line_total),
                    _fmt_num(doc.subtotal),
                    _fmt_num(doc.discount),
                    _fmt_num(doc.vat),
                    _fmt_num(doc.grand_total),
                ]
            )


def _write_summary(writer: csv.writer, docs: list[Document]) -> None:
    writer.writerow(
        [
            "เลขที่เอกสาร",
            "วันที่",
            "ร้านค้า",
            "หมวดหมู่",
            "จำนวนรายการ",
            "ยอดก่อน VAT",
            "ส่วนลด",
            "VAT",
            "ยอดสุทธิ",
            "หมายเหตุ",
        ]
    )
    for doc in docs:
        writer.writerow(
            [
                doc.document_number or "",
                doc.document_date or "",
                doc.merchant_name or "",
                doc.category or "",
                len(doc.items or []),
                _fmt_num(doc.subtotal),
                _fmt_num(doc.discount),
                _fmt_num(doc.vat),
                _fmt_num(doc.grand_total),
                (doc.notes or "").replace("\n", " / "),
            ]
        )


def _write_purchase_journal(writer: csv.writer, docs: list[Document]) -> None:
    """Thai purchase journal / สมุดซื้อ — one row per document."""
    writer.writerow(
        [
            "ลำดับ",
            "วันที่",
            "เลขที่ใบกำกับ",
            "ผู้ขาย (ร้านค้า)",
            "รายการ",
            "มูลค่าสินค้า (ก่อน VAT)",
            "ภาษีซื้อ (VAT 7%)",
            "รวมทั้งสิ้น",
        ]
    )
    for idx, doc in enumerate(docs, start=1):
        description = doc.category or (
            f"{len(doc.items)} รายการ" if doc.items else "สินค้า/บริการ"
        )
        writer.writerow(
            [
                idx,
                doc.document_date or "",
                doc.document_number or "",
                doc.merchant_name or "",
                description,
                _fmt_num(doc.subtotal),
                _fmt_num(doc.vat),
                _fmt_num(doc.grand_total),
            ]
        )


def _write_journal_entries(writer: csv.writer, docs: list[Document]) -> None:
    """Double-entry bookkeeping: Dr expense / Dr VAT receivable / Cr cash."""
    writer.writerow(
        [
            "วันที่",
            "เลขที่เอกสาร",
            "คำอธิบายรายการ",
            "เดบิต (บัญชี)",
            "เดบิต (จำนวน)",
            "เครดิต (บัญชี)",
            "เครดิต (จำนวน)",
        ]
    )
    for doc in docs:
        desc_prefix = f"{doc.merchant_name or 'ผู้ขาย'} / {doc.document_number or '-'}"
        subtotal = _fmt_num(doc.subtotal)
        vat = _fmt_num(doc.vat)
        grand = _fmt_num(doc.grand_total)
        if subtotal:
            writer.writerow(
                [
                    doc.document_date or "",
                    doc.document_number or "",
                    f"{desc_prefix} — ค่าใช้จ่าย",
                    f"ค่าใช้จ่าย - {doc.category or 'สินค้าอื่นๆ'}",
                    subtotal,
                    "",
                    "",
                ]
            )
        if vat:
            writer.writerow(
                [
                    doc.document_date or "",
                    doc.document_number or "",
                    f"{desc_prefix} — ภาษีซื้อ",
                    "ภาษีซื้อ",
                    vat,
                    "",
                    "",
                ]
            )
        if grand:
            writer.writerow(
                [
                    doc.document_date or "",
                    doc.document_number or "",
                    f"{desc_prefix} — จ่ายเงิน",
                    "",
                    "",
                    "เงินสด/เงินฝากธนาคาร",
                    grand,
                ]
            )


_EXPORT_FORMATS = {
    "line_items": ("sales_line_items.csv", _write_line_items),
    "summary": ("sales_summary.csv", _write_summary),
    "purchase_journal": ("purchase_journal.csv", _write_purchase_journal),
    "journal_entries": ("journal_entries.csv", _write_journal_entries),
}


@router.get("/export")
def export_csv(
    date_from: str | None = None,
    date_to: str | None = None,
    merchant: str | None = None,
    format: str = Query("line_items", pattern="^(line_items|summary|purchase_journal|journal_entries)$"),
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

    filename, writer_fn = _EXPORT_FORMATS[format]

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM so Excel opens Thai text correctly
    writer = csv.writer(buf)
    writer_fn(writer, docs)
    buf.seek(0)

    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
