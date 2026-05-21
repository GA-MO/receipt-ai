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

    return warnings
