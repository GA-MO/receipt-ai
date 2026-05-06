"""
Check whether different models correctly identify บรั่นดีรีเจนซี่ on dataTest/demo/06.jpeg
(โจวบุ่งใช้, handwritten brandy receipt).
Calls extract_with_fraud directly per model and prints item names.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import llm_client as _llm  # noqa: E402
from app.services.extraction_combined import extract_with_fraud  # noqa: E402

MODELS = [
    ("2.5_flash", "google/gemini-2.5-flash"),
    ("3_flash_preview", "google/gemini-3-flash-preview"),
    ("3.1_flash_lite", "google/gemini-3.1-flash-lite-preview"),
    ("3.1_pro", "google/gemini-3.1-pro-preview"),
]

FILE = ROOT / "dataTest" / "demo" / "06.jpeg"


def main() -> int:
    print(f"\n=== {FILE.name} — บรั่นดีรีเจนซี่ check ===\n")
    for label, model_id in MODELS:
        settings.openrouter_model = model_id
        _llm._openai_client = None
        t0 = time.time()
        try:
            out = extract_with_fraud(str(FILE))
            ext = out.extraction
            elapsed = time.time() - t0
            print(f"--- {label}  ({model_id})  ⏱ {elapsed:.1f}s")
            for it in ext.items:
                got_brandy = "บรั่นดี" in (it.product_name_raw or "") or "รีเจนซี่" in (it.product_name_raw or "")
                marker = "  ✅" if got_brandy else "    "
                print(
                    f"  {marker} {it.product_name_raw[:35]:35s}  "
                    f"qty={it.quantity}  unit={it.unit_price}  "
                    f"line={it.line_total}  cat={it.category}"
                )
            print()
        except Exception as e:
            print(f"--- {label}: ERROR {str(e)[:120]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
