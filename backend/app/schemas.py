from datetime import datetime

from pydantic import BaseModel

# ---------- Items ----------


class DocumentItemBase(BaseModel):
    product_name_raw: str | None = None
    product_name_normalized: str | None = None
    product_code: str | None = None  # Singha Online SKU when name matches catalog
    category: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    line_total: float | None = None


class DocumentItemResponse(DocumentItemBase):
    id: str
    document_id: str
    confidence: float | None = None
    needs_review: bool = False

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
    unit_price: float | None = None
    line_total: float | None = None
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
    unit_price: float | None = None
    line_total: float | None = None


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
    subtotal: float | None = None
    discount: float | None = None
    vat: float | None = None
    grand_total: float | None = None
    category: str | None = None
    notes: str | None = None
    fraud_flags: str | None = None
    items: list[DocumentItemResponse] = []

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    subtotal: float | None = None
    discount: float | None = None
    vat: float | None = None
    grand_total: float | None = None
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
    grand_total: float | None = None
    category: str | None = None
    confidence: float | None = None
    needs_review: bool = True
    item_count: int = 0
    fraud_flags: str | None = None

    model_config = {"from_attributes": True}


# ---------- Dashboard ----------


class DashboardStats(BaseModel):
    total_documents: int
    pending_review: int
    reviewed: int
    total_sales: float
    avg_confidence: float
    documents_today: int


# ---------- Extraction ----------


class ExtractionResult(BaseModel):
    merchant_name: str | None = None
    merchant_normalized: str | None = None
    document_number: str | None = None
    document_date: str | None = None
    category: str | None = None
    items: list[DocumentItemBase] = []
    subtotal: float | None = None
    discount: float | None = None
    vat: float | None = None
    grand_total: float | None = None
    confidence: float = 0.0
    notes: str | None = None
    needs_review_fields: list[str] = []
