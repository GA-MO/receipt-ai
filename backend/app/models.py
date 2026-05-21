import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


def _gen_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_gen_id)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, default="image")
    file_hash = Column(String, nullable=True, index=True)
    status = Column(String, default="pending", index=True)
    uploaded_at = Column(DateTime, default=_utcnow)
    processed_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    ocr_text = Column(Text, nullable=True)
    raw_extraction = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    merchant_name = Column(String, nullable=True)
    merchant_normalized = Column(String, nullable=True, index=True)
    document_number = Column(String, nullable=True, index=True)
    document_date = Column(String, nullable=True)
    subtotal = Column(Numeric(12, 2), nullable=True)
    discount = Column(Numeric(12, 2), nullable=True)
    vat = Column(Numeric(12, 2), nullable=True)
    grand_total = Column(Numeric(12, 2), nullable=True)
    category = Column(String, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    fraud_flags = Column(Text, nullable=True)  # JSON array of fraud flags

    deleted_at = Column(DateTime, nullable=True, index=True)

    visit_id = Column(String, ForeignKey("visits.id"), nullable=True, index=True)

    items = relationship(
        "DocumentItem", back_populates="document", cascade="all, delete-orphan"
    )
    visit = relationship("Visit", back_populates="documents")


class DocumentItem(Base):
    __tablename__ = "document_items"

    id = Column(String, primary_key=True, default=_gen_id)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    # Singha Online SKU if the normalized name matches a catalog entry.
    # Populated automatically on extract/update; lets dashboards group by SKU
    # regardless of how the user re-wrote ``product_name_normalized``.
    product_code = Column(String, nullable=True, index=True)
    # ``product_name_raw`` = what Gemini literally read off the receipt,
    # *before* any PRODUCT_CATALOG normalization. Immutable — user edits update
    # ``product_name_normalized`` only. Used by the alias service as a stable
    # learning source so corrections don't drift across edits.
    product_name_raw = Column(String, nullable=True)
    # ``product_name_normalized`` = display name. Starts equal to raw (or the
    # catalog canonical if Gemini matched the catalog), then evolves with user
    # edits. Shown in the UI and used everywhere dashboards aggregate.
    product_name_normalized = Column(String, nullable=True)
    category = Column(String, nullable=True, index=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    unit_price = Column(Numeric(12, 2), nullable=True)
    line_total = Column(Numeric(12, 2), nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=False)

    document = relationship("Document", back_populates="items")


class DocumentEvent(Base):
    """Append-only audit trail of everything that happens to a document.

    Until auth ships, ``actor`` is ``"system"`` (background processes) or
    ``"user"`` (any human-originated API call). ``payload`` is free-form JSON
    describing what changed — diff, fraud flags, error text, etc.
    """

    __tablename__ = "document_events"

    id = Column(String, primary_key=True, default=_gen_id)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False, default="user")
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class MerchantAlias(Base):
    """Learned mapping from raw (Gemini-extracted) merchant text → canonical.

    Populated when a human corrects ``merchant_name`` or ``category`` on a
    document; consulted after future Gemini extractions so the AI "learns"
    from operator input.
    """

    __tablename__ = "merchant_aliases"

    id = Column(String, primary_key=True, default=_gen_id)
    source_text = Column(String, nullable=False, unique=True, index=True)
    canonical_name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    hit_count = Column(Numeric(10, 0), default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Product(Base):
    """Canonical catalog — seeded from singhaonline.com, extensible by admins.

    Provides the authoritative list for autocomplete suggestions and the alias
    service uses ``canonical_name`` as a poisoning-guard pool (users cannot
    overwrite a catalog SKU via alias learning).
    """

    __tablename__ = "products"

    id = Column(String, primary_key=True, default=_gen_id)
    code = Column(String, nullable=True, index=True, unique=True)
    canonical_name = Column(String, nullable=False, unique=True, index=True)
    # Human-friendly short name for UI. Computed from ``canonical_name`` by
    # ``services.catalog.build_display_name``: strips pack/volume noise and
    # only keeps size suffix when multiple SKUs share a base name.
    display_name = Column(String, nullable=True, index=True)
    name_en = Column(String, nullable=True)
    brand_th = Column(String, nullable=True, index=True)
    brand_en = Column(String, nullable=True)
    # Top-level Singha Online category: เครื่องดื่ม / อาหาร และของว่าง /
    # สินค้าพรีเมียมสิงห์ / สินค้าอื่นๆ. Copied from path_category_name_th[1].
    category = Column(String, nullable=True, index=True)
    sub_category = Column(String, nullable=True)  # e.g. "น้ำดื่มสิงห์"
    size = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    aliases = Column(Text, nullable=True)  # JSON array of search keywords
    price = Column(Numeric(12, 2), nullable=True)
    product_type = Column(String, nullable=True)  # NON_AL / AL
    # Manufacturer label for brand-share analytics — "Boonrawd" for our own
    # products (the default), or "ThaiBev", "Diageo", "Pernod Ricard", etc.
    # for competitor SKUs kept in the catalog for receipt tracking.
    manufacturer = Column(String, nullable=True, index=True)
    source = Column(String, default="singhaonline")
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class ProductAlias(Base):
    """Same idea as :class:`MerchantAlias` but for line-item product names.

    Only name + category are learned — units, quantities and prices vary per
    receipt and must never be overridden from a past correction.
    """

    __tablename__ = "product_aliases"

    id = Column(String, primary_key=True, default=_gen_id)
    source_text = Column(String, nullable=False, unique=True, index=True)
    canonical_name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    hit_count = Column(Numeric(10, 0), default=1)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class CatalogGapEvent(Base):
    """One row per Gemini-emitted ``product_code`` that didn't match the
    active products catalog (and where the name wasn't a typo recovery either).

    Surfaces real catalog completeness gaps so admins can decide whether to
    add the missing SKU. Written from
    :func:`app.routers.documents._resolve_product_code`. Auto-resolved when
    a matching SKU is later added to ``products`` (see
    :func:`app.services.catalog.invalidate_cache`).
    """

    __tablename__ = "catalog_gap_events"

    id = Column(String, primary_key=True, default=_gen_id)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    emitted_code = Column(String, nullable=False, index=True)
    product_name = Column(String, nullable=True)
    product_name_raw = Column(String, nullable=True)
    seen_at = Column(DateTime, default=_utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True, index=True)


class TypoRecoveryEvent(Base):
    """One row per smart-fallback "typo recovery" — Gemini emitted a
    product_code that didn't exist in the catalog, but the normalized name
    *was* an exact catalog match, so we trusted the name and recovered.

    Recurring patterns here mean Gemini consistently typos a specific code,
    which usually warrants a hint in SYSTEM_INSTRUCTION ("watch out for
    code X being mis-typed as Y") or — more rarely — a real bug in our
    catalog representation that confuses the model.
    """

    __tablename__ = "typo_recovery_events"

    id = Column(String, primary_key=True, default=_gen_id)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    emitted_code = Column(String, nullable=False, index=True)
    recovered_code = Column(String, nullable=False, index=True)
    product_name = Column(String, nullable=True)
    seen_at = Column(DateTime, default=_utcnow, index=True)


class Visit(Base):
    """Groups multiple receipt documents collected during one store visit.

    A Visit links to a :class:`Store` (admin-managed master) via ``store_id``.
    ``store_key`` mirrors the canonical ``merchant_normalized`` for fast joins
    with the legacy documents table; ``store_label`` keeps a friendly display
    string (snapshot from the store at the time of the visit). The Visit has
    no time scope — date range filtering is done at query time against
    ``document_date``.
    """

    __tablename__ = "visits"

    id = Column(String, primary_key=True, default=_gen_id)
    store_id = Column(String, ForeignKey("stores.id"), nullable=True, index=True)
    store_key = Column(String, nullable=True, index=True)
    store_label = Column(String, nullable=True)
    # Reporting period the visit covers, format ``YYYY-MM``. Receipts whose
    # ``document_date`` falls outside this month are flagged after extraction
    # so the reviewer can move them to a different visit or correct the date.
    report_period = Column(String, nullable=True, index=True)
    rep_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    documents = relationship("Document", back_populates="visit")
    store = relationship("Store", back_populates="visits")


class Store(Base):
    """Admin-managed master record for a retail customer site / merchant.

    A Store may have many :class:`Visit` rows over time. ``normalized_name``
    is the canonical key used to match against ``Document.merchant_normalized``
    from extracted receipts; ``code`` is an optional human-readable id
    (e.g. route number) that field reps can quote.
    """

    __tablename__ = "stores"

    id = Column(String, primary_key=True, default=_gen_id)
    code = Column(String, nullable=True, index=True, unique=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=True, index=True)
    address = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    visits = relationship("Visit", back_populates="store")


class PushSubscription(Base):
    """Web Push subscription record.

    One row per (browser, device) combo. ``endpoint`` is the push service URL
    supplied by the browser's Push API and is naturally unique.
    """

    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=_gen_id)
    endpoint = Column(String, nullable=False, unique=True, index=True)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    last_used_at = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True)
