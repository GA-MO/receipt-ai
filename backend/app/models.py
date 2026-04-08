import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Numeric, String, Text
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
    document_number = Column(String, nullable=True, index=True)
    document_date = Column(String, nullable=True)
    subtotal = Column(Numeric(12, 2), nullable=True)
    discount = Column(Numeric(12, 2), nullable=True)
    vat = Column(Numeric(12, 2), nullable=True)
    grand_total = Column(Numeric(12, 2), nullable=True)
    category = Column(String, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    fraud_flags = Column(Text, nullable=True)  # JSON array of fraud flags

    items = relationship(
        "DocumentItem", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentItem(Base):
    __tablename__ = "document_items"

    id = Column(String, primary_key=True, default=_gen_id)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    product_name_raw = Column(String, nullable=True)
    product_name_normalized = Column(String, nullable=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String, nullable=True)
    unit_price = Column(Numeric(12, 2), nullable=True)
    line_total = Column(Numeric(12, 2), nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=False)

    document = relationship("Document", back_populates="items")
