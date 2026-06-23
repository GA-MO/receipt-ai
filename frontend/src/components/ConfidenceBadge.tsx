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
  if (!item.needs_review) {
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
  return {
    pct,
    color: AMBER,
    tint: "rgba(180,83,9,0.07)",
    label:
      `ตัวย่อ/ชื่อนี้ยังไม่เคยถูกยืนยันกับ SKU นี้ — ตรงกับชื่อในระบบแค่ ${pct}% ` +
      "จึงควรเทียบกับรูปก่อนยืนยัน (พอยืนยันแล้ว ครั้งหน้าจะขึ้นเขียวเอง ไม่ใช่ 'โอกาสถูก')",
    flag: true,
  };
}

export function ConfidenceBadge({ item }: { item: ConfidenceItem }) {
  const m = lineConfidenceMeta(item);
  if (m.pct == null) return null;
  return (
    <Tooltip label={m.label} multiline w={240} withArrow position="top" openDelay={150}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          cursor: "default",
          userSelect: "none",
        }}
        aria-label={`ตรงกับชื่อ/คำย่อที่ยืนยันแล้ว ${m.pct}%`}
      >
        <span
          style={{
            width: 26,
            height: 5,
            borderRadius: 3,
            background: "rgba(0,0,0,0.08)",
            overflow: "hidden",
            display: "inline-block",
          }}
        >
          <span
            style={{
              display: "block",
              height: "100%",
              width: `${m.pct}%`,
              background: m.color,
            }}
          />
        </span>
        <span
          style={{
            fontFamily: "monospace",
            fontSize: 11,
            lineHeight: 1,
            color: m.color,
            fontVariantNumeric: "tabular-nums",
            minWidth: 24,
          }}
        >
          {m.pct}%
        </span>
      </span>
    </Tooltip>
  );
}
