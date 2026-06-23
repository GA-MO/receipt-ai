"""Demo: per-line confidence separates proven shorthand from a misread,
and sharpens as the dictionary learns. No model self-grading involved.

    cd backend && .venv/bin/python ../scripts/demo_confidence_loop.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.services.line_confidence import build_known_forms, score_line  # noqa: E402

db = SessionLocal()
known = build_known_forms(db)

CASES = [
    ("บส.ญ", "INT-BEER-SINGHA-L", "ตัวย่อสากล (ถูก)"),
    ("เบียร์สิงห์", "INT-BEER-SINGHA-CAN", "ย่อปานกลาง (ถูก)"),
    ("สัวเล็ก", "INT-BEER-LEO-S", "อ่านผิด/scribble"),
]


def show(label, dictionary):
    print(f"\n{label}")
    print(f"  {'raw':<14}{'→ SKU':<26}{'conf':>6}  flag  เหตุผล")
    for raw, code, note in CASES:
        s = score_line(raw, code, dictionary)
        flag = "⚠ REVIEW" if s.needs_review else "✓ trust "
        print(f"  {raw:<14}{code:<26}{s.confidence:>6.2f}  {flag}  {s.reason}  [{note}]")


show("ก่อนยืนยัน (cold-start) — ทุกตัวย่อยังไม่พิสูจน์", known)

# Simulate the dictionary warming up: the two CORRECT shorthands get confirmed
# (via curated catalog shorthand column OR reviewer confirmation). The misread
# is never confirmed because it isn't what the rep meant.
warmed = {k: set(v) for k, v in known.items()}
from app.services.catalog import _norm  # noqa: E402
warmed.setdefault("INT-BEER-SINGHA-L", set()).add(_norm("บส.ญ"))
warmed.setdefault("INT-BEER-SINGHA-CAN", set()).add(_norm("เบียร์สิงห์"))

show("หลังยืนยันตัวย่อที่ถูก 2 ตัว — สัวเล็ก ไม่ถูกยืนยัน", warmed)

print("\n→ จุดสำคัญ: สัวเล็ก ยังถูก flag เพราะไม่มีใครยืนยันว่า 'สัวเล็ก = ลีโอเล็ก'")
print("  ส่วนตัวย่อที่ถูกกลายเป็น trusted — แยกกันได้ด้วย 'การยืนยัน' ไม่ใช่ 'หน้าตา'")
db.close()
