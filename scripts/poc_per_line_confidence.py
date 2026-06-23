"""PoC: can the model give a real PER-LINE confidence rate?

We ask the extractor to score every line it reads with two 0-1 numbers:
  * legibility       — how clearly the source text/handwriting reads
  * match_confidence — how sure it is the product identity is correct
then check whether the lines we KNOW were wrong (from human review) actually
got the lowest scores. If they do, per-line accuracy is not just measurable —
the system can flag the risky lines before a human looks.

Does NOT touch production code: builds its own prompt and parses raw JSON.

    cd backend && .venv/bin/python ../scripts/poc_per_line_confidence.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import llm_client  # noqa: E402
from app.services.extraction import build_system_instruction  # noqa: E402

# (file, label, set of raw names the human review proved WRONG / removed)
TESTS = [
    ("uploads/83a03855-55ba-4df5-ba35-05be80bf2383.jpeg", "Image.jpeg (handwritten)", {"สัวเล็ก"}),
    ("uploads/b40d41bb-ac97-4c12-ac63-76ebbd15fbec.jpg", "IMG_9327 (Singha Sparking)", {"singha sparking"}),
    ("uploads/63ded22b-1dd7-448a-b9e4-ae14ddb59ab1.jpg", "IMG_9340 (13 lines)", {"เป๊ปซี่"}),
    ("uploads/7d16e5d1-9aaa-4a0b-877b-fb9b98b5fddd.jpg", "IMG_9321 (clean)", set()),
]

CONF_OVERRIDE = """
## งานพิเศษ (PoC): ให้คะแนนความมั่นใจราย "บรรทัด"
นอกจาก field เดิมของแต่ละ item ให้เพิ่ม 2 field นี้ในทุก item:
  "legibility": ตัวเลข 0.0-1.0 — ต้นฉบับ/ลายมือของบรรทัดนี้อ่านชัดแค่ไหน (1.0 = พิมพ์ชัด, ต่ำ = ลายมือกำกวม/เลือน)
  "match_confidence": ตัวเลข 0.0-1.0 — มั่นใจแค่ไหนว่า product_code/ชื่อสินค้าที่เลือก "ตรง" กับที่เขียนจริง
ให้คะแนนตามจริงและกล้าให้ต่ำเมื่อไม่ชัด — อย่าให้ 0.95 ทุกบรรทัด
ตอบ JSON ตาม schema เดิม (เพิ่ม 2 field ข้างต้นในแต่ละ item เท่านั้น)
"""


def run(path: str):
    data = (ROOT / "backend" / path).read_bytes()
    raw = llm_client.generate_json(
        system_instruction=build_system_instruction() + CONF_OVERRIDE,
        prompt="ดึงรายการสินค้า + ให้คะแนน legibility และ match_confidence ทุกบรรทัด",
        file_bytes=data,
        mime_type="image/jpeg",
        temperature=0.1,
    )
    return json.loads(raw).get("items", [])


def main() -> None:
    print(f"{'':2}{'product (raw → name)':<40}{'qty':>5}{'legib':>7}{'match':>7}  flag")
    all_wrong, all_right = [], []
    for path, label, wrong in TESTS:
        print(f"\n■ {label}")
        for it in run(path):
            rawn = (it.get("product_name_raw") or "").strip()
            name = it.get("product_name_normalized") or ""
            lg = it.get("legibility")
            mc = it.get("match_confidence")
            is_wrong = rawn.lower() in {w.lower() for w in wrong}
            mark = "  ⚠ WRONG (per human review)" if is_wrong else ""
            disp = f"{rawn} → {name}"[:38]
            lg_s = f"{lg:.2f}" if isinstance(lg, (int, float)) else "—"
            mc_s = f"{mc:.2f}" if isinstance(mc, (int, float)) else "—"
            print(f"  {disp:<40}{it.get('quantity'):>5}{lg_s:>7}{mc_s:>7}{mark}")
            score = min([v for v in (lg, mc) if isinstance(v, (int, float))], default=None)
            if score is not None:
                (all_wrong if is_wrong else all_right).append(score)

    print("\n" + "=" * 60)
    if all_wrong and all_right:
        import statistics
        print("Does per-line confidence separate wrong from right?")
        print(f"  wrong lines  min(legib,match): avg {statistics.mean(all_wrong):.2f}  "
              f"(values: {[round(x,2) for x in all_wrong]})")
        print(f"  correct lines min(legib,match): avg {statistics.mean(all_right):.2f}")
        thr = max(all_wrong) + 0.001
        caught = sum(1 for x in all_wrong if x <= max(all_wrong))
        below = sum(1 for x in all_right if x <= max(all_wrong))
        print(f"  → a threshold at {max(all_wrong):.2f} flags all {len(all_wrong)} wrong "
              f"line(s) and only {below}/{len(all_right)} correct lines")


if __name__ == "__main__":
    main()
