from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ---------- Items ----------


class DocumentItemBase(BaseModel):
    product_name_raw: Optional[str] = None
    product_name_normalized: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None


class DocumentItemResponse(DocumentItemBase):
    id: str
    document_id: str
    confidence: Optional[float] = None
    needs_review: bool = False

    model_config = {"from_attributes": True}


class DocumentItemUpdate(BaseModel):
    product_name_raw: Optional[str] = None
    product_name_normalized: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    needs_review: Optional[bool] = None


# ---------- Documents ----------


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_type: str = "image"
    status: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    confidence: Optional[float] = None
    needs_review: bool = True
    error_message: Optional[str] = None
    merchant_name: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    vat: Optional[float] = None
    grand_total: Optional[float] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    fraud_flags: Optional[str] = None
    items: list[DocumentItemResponse] = []

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    merchant_name: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    vat: Optional[float] = None
    grand_total: Optional[float] = None
    category: Optional[str] = None
    notes: Optional[str] = None


class DocumentListItem(BaseModel):
    id: str
    filename: str
    status: str
    uploaded_at: datetime
    merchant_name: Optional[str] = None
    grand_total: Optional[float] = None
    category: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = True
    item_count: int = 0
    fraud_flags: Optional[str] = None

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
    merchant_name: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    category: Optional[str] = None
    items: list[DocumentItemBase] = []
    subtotal: Optional[float] = None
    discount: Optional[float] = None
    vat: Optional[float] = None
    grand_total: Optional[float] = None
    confidence: float = 0.0
    notes: Optional[str] = None
    needs_review_fields: list[str] = []
