import { Tooltip } from "@mantine/core";

/**
 * Per-line confidence indicator. The score is computed server-side from
 * verifiable signals (does the read text match a confirmed catalog
 * name/shorthand for the picked SKU) — NOT the model grading itself. See
 * backend/app/services/line_confidence.py.
 *
 * Shown inline, in document order, so a reviewer can read it line-by-line
 * against the receipt image. It never reorders rows.
 */

export interface ConfidenceItem {
  confidence: number | null;
  needs_review: boolean;
  product_code: string | null;
  review_reason?: string | null;
}

export interface ConfidenceMeta {
  pct: number | null;
  color: string;
  /** subtle row tint for flagged lines */
  tint: string;
  label: string;
  flag: boolean;
}

const GREEN = "#15803d";
const AMBER = "#b45309";
const RED = "#b91c1c";

// The score is NOT "probability of being correct" and NOT the model grading
// itself — it is how well the text the AI read matches a name/shorthand this
// SKU has been confirmed with before (catalog name, seed shorthand, or a
// reviewer-confirmed alias). Wording avoids "ความมั่นใจ"/"โอกาสถูก" on purpose.
export function lineConfidenceMeta(item: ConfidenceItem): ConfidenceMeta {
  const pct = item.confidence == null ? null : Math.round(item.confidence * 100);
  if (!item.product_code) {
    return {
      pct,
      color: RED,
      tint: "rgba(185,28,28,0.06)",
      label: "ไม่พบสินค้านี้ใน catalog — เลือก SKU ให้ตรงก่อน แล้วเทียบกับรูป",
      flag: true,
    };
  }
  // A server-side flag outranks a perfect text match: the text can match
  // the picked SKU 100% and still be ambiguous with a sibling, or the bill's
  // own arithmetic can contradict the quantity.
  if (item.needs_review) {
    return {
      pct,
      color: AMBER,
      tint: "rgba(180,83,9,0.07)",
      label:
        item.review_reason ??
        `ตัวย่อ/ชื่อนี้ยังไม่เคยถูกยืนยันกับ SKU นี้ — ตรงกับชื่อในระบบแค่ ${pct}% ` +
          "จึงควรเทียบกับรูปก่อนยืนยัน (พอยืนยันแล้ว ครั้งหน้าจะขึ้นเขียวเอง ไม่ใช่ 'โอกาสถูก')",
      flag: true,
    };
  }
  const exact = item.confidence != null && item.confidence >= 0.999;
  if (exact) {
    return {
      pct,
      color: GREEN,
      tint: "transparent",
      label: "ตรงกับชื่อ/คำย่อที่ยืนยันแล้ว — ระบบรู้จักคำนี้ เชื่อได้",
      flag: false,
    };
  }
  return {
    pct,
    color: GREEN,
    tint: "transparent",
    label:
      `ใกล้เคียงชื่อใน catalog — คำที่อ่านได้ตรงกับชื่อสินค้า ${pct}% ` +
      "(เป็น 'ความตรงของข้อความ' ไม่ใช่ 'โอกาสถูก')",
    flag: false,
  };
}

/** Short row chip for a flagged line: the server's reason, trimmed to the
 *  part before the em-dash so it fits next to the score. Full text in the
 *  badge tooltip. */
export function ReviewReasonChip({ item }: { item: ConfidenceItem }) {
  if (!item.needs_review || !item.review_reason || !item.product_code) return null;
  const short = item.review_reason.split(" — ")[0];
  return (
    <Tooltip label={item.review_reason} multiline w={240} withArrow position="top" openDelay={150}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          whiteSpace: "nowrap",
          fontSize: 11,
          fontWeight: 600,
          lineHeight: 1.3,
          padding: "1px 6px",
          borderRadius: 999,
          background: "rgba(180,83,9,0.12)",
          color: AMBER,
          cursor: "default",
        }}
      >
        {short}
      </span>
    </Tooltip>
  );
}

/** Three states — ✓ known / ? needs a look / ✗ no SKU — with the text-match
 *  percentage and the reason in the tooltip. Reps do nothing different at
 *  76% vs 90%, so the digits stay out of the row. */
export function ConfidenceBadge({ item }: { item: ConfidenceItem }) {
  const m = lineConfidenceMeta(item);
  const glyph = !item.product_code ? "✗" : item.needs_review ? "?" : "✓";
  const label = m.pct == null ? m.label : `${m.pct}% — ${m.label}`;
  return (
    <Tooltip label={label} multiline w={260} withArrow position="top" openDelay={150}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 16,
          height: 16,
          borderRadius: 999,
          fontFamily: "monospace",
          fontSize: 11,
          fontWeight: 700,
          lineHeight: 1,
          color: m.color,
          background: !item.product_code
            ? "rgba(185,28,28,0.12)"
            : item.needs_review
              ? "rgba(180,83,9,0.14)"
              : "rgba(21,128,61,0.10)",
          cursor: "default",
          userSelect: "none",
        }}
        aria-label={label}
      >
        {glyph}
      </span>
    </Tooltip>
  );
}
