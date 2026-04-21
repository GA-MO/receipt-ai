/**
 * Single source of truth for product categories.
 *
 * Aligned with singhaonline.com (2026-04) — 4 top-level buckets.
 * If you change this list, also update:
 *   - backend/app/services/extraction.py PRODUCT_CATEGORIES
 *   - backend/app/services/extraction.py PRODUCT_CATALOG table's หมวด column
 */

export const PRODUCT_CATEGORIES = [
  "เครื่องดื่ม",
  "อาหาร และของว่าง",
  "สินค้าพรีเมียมสิงห์",
  "สินค้าอื่นๆ",
] as const;

export type ProductCategory = (typeof PRODUCT_CATEGORIES)[number];

/** For <Select> data= prop; includes an empty "unset" choice. */
export const CATEGORY_OPTIONS_WITH_BLANK = [
  { value: "", label: "ไม่ระบุ" },
  ...PRODUCT_CATEGORIES.map((c) => ({ value: c, label: c })),
];

/** For filter dropdowns, where the empty slot means "all". */
export const CATEGORY_FILTER_OPTIONS = [
  { value: "", label: "ทุกหมวด" },
  ...PRODUCT_CATEGORIES.map((c) => ({ value: c, label: c })),
];

export const CATEGORY_COLORS: Record<string, string> = {
  "เครื่องดื่ม": "indigo",
  "อาหาร และของว่าง": "orange",
  "สินค้าพรีเมียมสิงห์": "grape",
  "สินค้าอื่นๆ": "gray",
};

export const CATEGORY_TW_COLORS: Record<string, string> = {
  "เครื่องดื่ม": "bg-indigo-500",
  "อาหาร และของว่าง": "bg-orange-500",
  "สินค้าพรีเมียมสิงห์": "bg-violet-500",
  "สินค้าอื่นๆ": "bg-gray-400",
};
