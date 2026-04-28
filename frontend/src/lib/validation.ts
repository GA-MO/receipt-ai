/**
 * Client-side validation for receipt totals. Pure functions, no UI dependencies.
 */

export type ValidationSeverity = "info" | "warning" | "error";

export type TotalsPatch = Partial<{
  subtotal: number | null;
  discount: number | null;
  vat: number | null;
  grand_total: number | null;
}>;

export interface ValidationFix {
  label: string;
  apply: TotalsPatch;
}

export interface ValidationIssue {
  field: "totals" | "vat" | "items";
  severity: ValidationSeverity;
  message: string;
  fixes?: ValidationFix[];
}

interface ValidationInput {
  subtotal: number | null;
  discount: number | null;
  vat: number | null;
  grand_total: number | null;
  items_total?: number | null;
}

const TOTAL_TOLERANCE_BAHT = 1.0;
const VAT_TOLERANCE_BAHT = 1.0;
const THAI_VAT_RATE = 0.07;

function toNum(v: number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && !isNaN(v)) return v;
  return null;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function fmt(n: number): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function validateTotals(input: ValidationInput): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const subtotal = toNum(input.subtotal);
  const discount = toNum(input.discount) ?? 0;
  const vat = toNum(input.vat);
  const grand = toNum(input.grand_total);
  const itemsTotal = toNum(input.items_total);

  if (subtotal != null && itemsTotal != null && itemsTotal > 0) {
    const diff = Math.abs(itemsTotal - subtotal);
    if (diff > TOTAL_TOLERANCE_BAHT) {
      issues.push({
        field: "items",
        severity: "warning",
        message: `ผลรวมรายการสินค้า ฿${fmt(itemsTotal)} ไม่ตรงกับยอดก่อนภาษี ฿${fmt(subtotal)} (ต่าง ฿${fmt(diff)})`,
        fixes: [
          {
            label: `ใช้ผลรวมรายการ ฿${fmt(itemsTotal)} เป็นยอดก่อนภาษี`,
            apply: { subtotal: round2(itemsTotal) },
          },
        ],
      });
    }
  }

  if (subtotal != null && vat != null && vat > 0) {
    const expectedVat = subtotal * THAI_VAT_RATE;
    const diff = Math.abs(expectedVat - vat);
    if (diff > VAT_TOLERANCE_BAHT) {
      const actualRate = (vat / subtotal) * 100;
      issues.push({
        field: "vat",
        severity: "warning",
        message: `VAT 7% ของ ฿${fmt(subtotal)} ควรเป็น ฿${fmt(expectedVat)} (ที่กรอก: ฿${fmt(vat)} ≈ ${actualRate.toFixed(1)}%)`,
        fixes: [
          {
            label: `คำนวณ VAT 7% = ฿${fmt(expectedVat)}`,
            apply: { vat: round2(expectedVat) },
          },
        ],
      });
    }
  }

  if (subtotal != null && grand != null) {
    const expected = subtotal - discount + (vat ?? 0);
    const diff = Math.abs(expected - grand);
    if (diff > TOTAL_TOLERANCE_BAHT) {
      const fixes: ValidationFix[] = [
        {
          label: `คำนวณยอดรวมสุทธิใหม่ = ฿${fmt(expected)}`,
          apply: { grand_total: round2(expected) },
        },
      ];
      if (
        (vat == null || vat === 0) &&
        Math.abs(subtotal - grand) <= TOTAL_TOLERANCE_BAHT
      ) {
        const splitSub = round2(grand / (1 + THAI_VAT_RATE));
        const splitVat = round2(grand - splitSub);
        fixes.push({
          label: `ยอดรวม VAT แล้ว — แยกเป็น ฿${fmt(splitSub)} + VAT ฿${fmt(splitVat)}`,
          apply: { subtotal: splitSub, vat: splitVat },
        });
      }
      issues.push({
        field: "totals",
        severity: "error",
        message: `ยอดรวมไม่ตรง: ${fmt(subtotal)} − ${fmt(discount)} + ${fmt(vat ?? 0)} = ${fmt(expected)} แต่กรอก ${fmt(grand)} (ต่าง ฿${fmt(diff)})`,
        fixes,
      });
    }
  }

  return issues;
}
