from ..schemas import ExtractionResult

# Units the shop sells in whole counts — a fractional quantity here is almost
# always a misread (e.g. a stray decimal, or two digits merged).
_DISCRETE_UNITS = {"ลัง", "ขวด", "แพ็ค", "กระป๋อง", "ถาด", "ใบ", "ตัว", "แผง", "กล่อง", "โหล"}
# A single line larger than this is implausible for one store-visit order and
# usually a digit misread (e.g. "30" for "3", "600" for "60"). Soft flag only.
_QTY_SANITY_MAX = 2000
# Allowed gap between summed line amounts and the printed total before we flag
# (covers rounding / a small unread line). 2%.
_TOTAL_TOLERANCE = 0.02


def validate_extraction(result: ExtractionResult) -> list[str]:
    """Run business-rule checks and return Thai-language warnings."""
    warnings: list[str] = []

    if result.document_date:
        try:
            year = int(result.document_date.split("-")[0])
            if year > 2500:
                warnings.append("วันที่อาจยังเป็น พ.ศ. ยังไม่ได้แปลง")
        except (ValueError, IndexError):
            warnings.append("รูปแบบวันที่อาจไม่ถูกต้อง")

    if not result.merchant_name:
        warnings.append("ไม่พบชื่อร้านค้า")
    if not result.items:
        warnings.append("ไม่พบรายการสินค้า")

    for i, item in enumerate(result.items, 1):
        if not item.product_name_normalized:
            warnings.append(f"รายการที่ {i}: ไม่มีชื่อสินค้า")
        q = item.quantity
        if q is None or q <= 0:
            warnings.append(f"รายการที่ {i}: จำนวนสินค้าไม่ถูกต้อง")
            continue
        # Quantity-plausibility (cheap, no extra LLM cost):
        if item.unit in _DISCRETE_UNITS and float(q) != int(q):
            warnings.append(
                f"รายการที่ {i}: จำนวน {q:g} {item.unit} มีเศษ — สินค้าขายเป็นจำนวนเต็ม ตรวจสอบ"
            )
        if q > _QTY_SANITY_MAX:
            warnings.append(
                f"รายการที่ {i}: จำนวน {q:g} สูงผิดปกติ — อาจอ่านเลขเกิน ตรวจสอบก่อนอนุมัติ"
            )

    # Same catalog SKU on 2+ lines of one receipt is almost always a misread
    # (the model mapped a different line to the wrong code), not a real
    # duplicate — a single receipt rarely lists the same SKU twice. Surface it
    # for human review rather than silently merging, since one of the lines is
    # likely a different product entirely.
    code_names: dict[str, str] = {}
    code_counts: dict[str, int] = {}
    for item in result.items:
        code = item.product_code
        if not code:
            continue
        code_counts[code] = code_counts.get(code, 0) + 1
        code_names.setdefault(code, item.product_name_normalized or code)
    for code, count in code_counts.items():
        if count > 1:
            warnings.append(
                f"พบ SKU ซ้ำใน {code_names[code]!r} {count} บรรทัด — "
                "อาจอ่านบางบรรทัดผิด ตรวจสอบก่อนอนุมัติ"
            )

    # Completeness cross-check (validation-only amounts, no extra LLM cost):
    # if the bill's printed total and every line amount were legible, their sum
    # should match. A gap means a line was missed, doubled, or a quantity was
    # misread — exactly the silent errors confidence can't catch.
    total = result.validation_total
    line_amounts = [it.amount for it in result.items if it.amount is not None]
    if total and total > 0 and len(line_amounts) == len(result.items) and line_amounts:
        summed = sum(line_amounts)
        diff = abs(summed - total)
        if diff / total > _TOTAL_TOLERANCE:
            warnings.append(
                f"ยอดรวมรายการ ({summed:,.0f}) ไม่ตรงยอดท้ายบิล ({total:,.0f}) — "
                "อาจมีบรรทัดขาด/เกิน หรืออ่านจำนวนผิด ตรวจสอบก่อนอนุมัติ"
            )

    return warnings
