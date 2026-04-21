"""Remap legacy 8-category taxonomy to singhaonline.com 4-category taxonomy.

Old → new:
    เบียร์ / น้ำดื่ม / โซดาและน้ำอัดลม / น้ำแร่ / สุรา / เครื่องดื่มอื่นๆ  →  เครื่องดื่ม
    อาหาร                                                                →  อาหาร และของว่าง
    อื่นๆ                                                                 →  สินค้าอื่นๆ

Applies to both ``documents.category`` and ``document_items.category``.
``merchant_aliases.category`` and ``product_aliases.category`` are also updated
so future alias applies write the new taxonomy.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BEVERAGE_OLD = ("เบียร์", "น้ำดื่ม", "โซดาและน้ำอัดลม", "น้ำแร่", "สุรา", "เครื่องดื่มอื่นๆ")


def _update(table: str) -> None:
    placeholders = ",".join([f"'{v}'" for v in _BEVERAGE_OLD])
    op.execute(
        f"UPDATE {table} SET category = 'เครื่องดื่ม' WHERE category IN ({placeholders})"
    )
    op.execute(
        f"UPDATE {table} SET category = 'อาหาร และของว่าง' WHERE category = 'อาหาร'"
    )
    op.execute(
        f"UPDATE {table} SET category = 'สินค้าอื่นๆ' WHERE category = 'อื่นๆ'"
    )


def upgrade() -> None:
    for tbl in ("documents", "document_items", "merchant_aliases", "product_aliases"):
        _update(tbl)


def downgrade() -> None:
    # Non-reversible without extra metadata — we can't tell, for a
    # document now tagged "เครื่องดื่ม", whether it was originally
    # "เบียร์" or "น้ำดื่ม". Leave as a no-op.
    pass
