from ..schemas import ExtractionResult


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
        if item.quantity is None or item.quantity <= 0:
            warnings.append(f"รายการที่ {i}: จำนวนสินค้าไม่ถูกต้อง")

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

    return warnings
