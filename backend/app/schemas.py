from datetime import datetime

from pydantic import BaseModel, Field

# ---------- Items ----------


class DocumentItemBase(BaseModel):
    product_name_raw: str | None = None
    product_name_normalized: str | None = None
    product_code: str | None = None  # Singha Online SKU when name matches catalog
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None
    # Transient, validation-ONLY: the line's printed amount. Read in the same
    # vision call (no extra cost), used to cross-check completeness, then
    # discarded — NOT a restored price feature, never persisted or shown.
    amount: float | None = None


class DocumentItemResponse(DocumentItemBase):
    id: str
    document_id: str
    confidence: float | None = None
    needs_review: bool = False
    # ``amount`` is a transient validation-only input on the base model; never
    # expose it on the API (no price fields leave the server post-pivot).
    amount: float | None = Field(default=None, exclude=True)

    model_config = {"from_attributes": True}


class DocumentItemUpdate(BaseModel):
    # ``product_name_raw`` is intentionally NOT here — raw is immutable once
    # captured from Gemini. UI edits update normalized only.
    product_name_normalized: str | None = None
    # Explicit SKU override when the UI knows which product the user picked.
    # If ``None``, the backend auto-resolves from ``product_name_normalized``.
    product_code: str | None = None
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None
    needs_review: bool | None = None


class DocumentItemCreate(BaseModel):
    # For manually-added items, the caller may set raw = whatever the user
    # typed (there is no Gemini OCR source); if omitted we copy normalized.
    product_name_raw: str | None = None
    product_name_normalized: str | None = None
    product_code: str | None = None
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None


# ---------- Documents ----------


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_type: str = "image"
    status: str
    uploaded_at: datetime
    processed_at: datetime | None = None
    reviewed_at: datetime | None = None
    confidence: float | None = None
    needs_review: bool = True
    error_message: str | None = None
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    category: str | None = None
    notes: str | None = None
    items: list[DocumentItemResponse] = []
    visit_id: str | None = None

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    category: str | None = None
    notes: str | None = None


class BulkIds(BaseModel):
    ids: list[str]


class BulkActionResult(BaseModel):
    succeeded: int
    failed: int
    failed_ids: list[str] = []


class DocumentListItem(BaseModel):
    id: str
    filename: str
    file_type: str = "image"
    status: str
    uploaded_at: datetime
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_date: str | None = None
    category: str | None = None
    confidence: float | None = None
    needs_review: bool = True
    item_count: int = 0
    visit_id: str | None = None
    period_mismatch: bool = False
    store_mismatch: bool = False

    model_config = {"from_attributes": True}


# ---------- Stores ----------


class StoreCreate(BaseModel):
    name: str
    code: str | None = None
    normalized_name: str | None = None
    address: str | None = None
    notes: str | None = None


class StoreUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    normalized_name: str | None = None
    address: str | None = None
    notes: str | None = None
    active: bool | None = None


class StoreListItem(BaseModel):
    id: str
    code: str | None = None
    name: str
    normalized_name: str | None = None
    address: str | None = None
    notes: str | None = None
    active: bool = True
    created_at: datetime
    updated_at: datetime
    visit_count: int = 0

    model_config = {"from_attributes": True}


# ---------- Visits ----------


class VisitCreate(BaseModel):
    store_id: str | None = None
    # Free-text fallback when the user types a brand-new store name and the
    # frontend hasn't promoted it to a Store row yet.
    store_label: str | None = None
    # Reporting month in ``YYYY-MM`` format. When set, receipts whose
    # ``document_date`` falls outside this month are flagged after extraction.
    report_period: str | None = None
    rep_name: str | None = None
    notes: str | None = None


class VisitUpdate(BaseModel):
    store_id: str | None = None
    store_label: str | None = None
    store_key: str | None = None
    report_period: str | None = None
    rep_name: str | None = None
    notes: str | None = None


class VisitListItem(BaseModel):
    id: str
    store_id: str | None = None
    store_key: str | None = None
    store_label: str | None = None
    report_period: str | None = None
    rep_name: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    reviewed_count: int = 0
    earliest_doc_date: str | None = None
    latest_doc_date: str | None = None

    model_config = {"from_attributes": True}


class VisitAggregateRow(BaseModel):
    product_code: str | None = None
    display_name: str
    manufacturer: str | None = None
    is_catalog_match: bool = False
    total_quantity: float = 0.0
    unit: str | None = None
    source_doc_ids: list[str] = []
    source_count: int = 0
    units_seen: list[str] = []  # >1 entry means mixed-unit warning


class VisitDetail(BaseModel):
    id: str
    store_id: str | None = None
    store_key: str | None = None
    store_label: str | None = None
    report_period: str | None = None
    rep_name: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentListItem] = []
    aggregate: list[VisitAggregateRow] = []
    reviewed_count: int = 0


# ---------- Extraction ----------


class ExtractionResult(BaseModel):
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    category: str | None = None
    items: list[DocumentItemBase] = []
    confidence: float = 0.0
    notes: str | None = None
    needs_review_fields: list[str] = []
    # Transient, validation-ONLY: the bill's printed grand total. Compared to
    # the sum of line amounts to catch missed / extra / duplicated lines. Not
    # persisted — see DocumentItemBase.amount.
    validation_total: float | None = None
