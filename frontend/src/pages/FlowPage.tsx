import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "motion/react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Select, Autocomplete, Loader, ActionIcon } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconUpload,
  IconBuildingStore,
  IconArrowRight,
  IconSparkles,
  IconX,
  IconCheck,
  IconAlertTriangle,
  IconReceipt,
  IconPhotoOff,
  IconClock,
  IconRefresh,
  IconTrash,
  IconChevronLeft,
  IconChevronRight,
  IconPhoto,
} from "@tabler/icons-react";
import {
  useDashboard,
  useUploadInbox,
  useDocument,
  useMarkVisitReviewed,
  useUpdateItem,
  useDeleteItem,
  useDeleteDocument,
  useApproveDocument,
  useAutocomplete,
  useStores,
  useAssignStoreToDoc,
  useDiscardInboxDoc,
  visitsKey,
  qk,
} from "../api/queries";
import { getDocumentImageUrl, getVisit, getDocument, deleteItem } from "../api/client";
import { ImageCanvas } from "@/components/ImageCanvas";
import type {
  DashboardVisit,
  DocumentListItem,
  DocumentItemData,
  VisitAggregateRow,
  VisitDetail,
} from "../api/client";

type Stage = "idle" | "processing" | "results";

const THAI_MONTHS = [
  "ม.ค.",
  "ก.พ.",
  "มี.ค.",
  "เม.ย.",
  "พ.ค.",
  "มิ.ย.",
  "ก.ค.",
  "ส.ค.",
  "ก.ย.",
  "ต.ค.",
  "พ.ย.",
  "ธ.ค.",
];

function formatPeriod(p: string | null): string {
  if (!p) return "ไม่ระบุเดือน";
  const [y, m] = p.split("-");
  const mi = Number(m) - 1;
  if (mi < 0 || mi > 11) return p;
  return `${THAI_MONTHS[mi]} ${Number(y) + 543}`;
}

function isOurs(manufacturer: string | null): boolean {
  if (!manufacturer) return false;
  const m = manufacturer.toLowerCase();
  return (
    m.includes("boonrawd") || m.includes("บุญรอด") || m.includes("singha") || m.includes("สิงห์")
  );
}

function isFlagged(d: {
  needs_review: boolean;
  confidence: number | null;
  status?: string;
}): boolean {
  return d.needs_review || (d.confidence != null && d.confidence < 0.7) || d.status === "error";
}

/** Why the AI flagged this receipt — turns the accumulated `notes` (validation
 *  warnings, period/store mismatch) + off-catalog items + low confidence into
 *  short, human reasons so "ต้องตรวจ" actually says what to check. */
function reviewReasons(d: {
  notes: string | null;
  confidence: number | null;
  items: { product_code: string | null }[];
}): string[] {
  const reasons: string[] = [];
  if (d.notes) {
    // Only ⚠️-prefixed lines are real warnings; the model's free-text note
    // (e.g. "เอกสารชัดเจน อ่านง่าย") is left out so it can't contradict the box.
    for (const line of d.notes.split("\n")) {
      if (!line.includes("⚠️")) continue;
      const t = line.replace(/^⚠️\s*/, "").trim();
      if (t) reasons.push(t);
    }
  }
  const offCatalog = d.items.filter((it) => !it.product_code).length;
  if (offCatalog > 0) {
    reasons.push(`มีสินค้านอกแคตตาล็อก ${offCatalog} รายการ (จุดส้มด้านล่าง) — ตรวจชื่อ/แก้ให้ตรง`);
  }
  if (reasons.length === 0 && d.confidence != null && d.confidence < 0.7) {
    reasons.push(
      `ระบบไม่มั่นใจการอ่านใบนี้ (${Math.round(d.confidence * 100)}%) — ตรวจตัวเลขและชื่อสินค้า`,
    );
  }
  return reasons;
}

function isSaved(v: DashboardVisit, optimistic: Set<string>): boolean {
  return optimistic.has(v.id) || (!!v.last_reviewed_at && v.new_doc_count === 0);
}

/** Same-store visits collapse into one card (months merged) — demo presents a
 * store, not a store×month pair. The underlying per-month visits stay intact. */
interface StoreGroup {
  key: string;
  label: string;
  visitIds: string[];
  documentCount: number;
  needsReviewCount: number;
  periods: string[];
  isNew: boolean;
  saved: boolean;
  latestUpdated: string;
}

export default function FlowPage() {
  const [stage, setStage] = useState<Stage>("idle");
  const [uploadedIds, setUploadedIds] = useState<string[]>([]);
  const [runStartedAt, setRunStartedAt] = useState<string>("");
  const [openGroup, setOpenGroup] = useState<string[] | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [success, setSuccess] = useState<number | null>(null);
  const [runMs, setRunMs] = useState<number | null>(null);
  const uploadDoneAt = useRef<number>(0);
  const runStartAt = useRef<number>(0);

  const upload = useUploadInbox();
  const bulkSave = useMarkVisitReviewed();
  const dashboard = useDashboard(null);

  const onDrop = useCallback(
    async (files: File[]) => {
      const images = files.filter((f) => f.type.startsWith("image/"));
      if (images.length === 0) {
        notifications.show({ color: "red", message: "กรุณาวางไฟล์รูปภาพใบเสร็จ" });
        return;
      }
      setRunStartedAt(new Date().toISOString());
      runStartAt.current = Date.now();
      setRunMs(null);
      setSavedIds(new Set());
      setStage("processing");
      setUploadedIds([]);
      try {
        const res = await upload.mutateAsync(images);
        setUploadedIds(res.document_ids);
        uploadDoneAt.current = Date.now();
        if (res.document_ids.length === 0) {
          notifications.show({
            color: "yellow",
            message: res.duplicates.length ? "ไฟล์เหล่านี้เคยอัปโหลดแล้ว" : "อัปโหลดไม่สำเร็จ",
          });
          setStage("results");
        }
        if (res.failures.length) {
          notifications.show({
            color: "yellow",
            message: `อัปโหลดไม่ผ่าน ${res.failures.length} ไฟล์`,
          });
        }
      } catch {
        notifications.show({ color: "red", message: "อัปโหลดไม่สำเร็จ" });
        setStage("idle");
      }
    },
    [upload],
  );

  const data = dashboard.data;
  const ourProcessing = useMemo(() => {
    if (!data || uploadedIds.length === 0) return 0;
    const ids = new Set(uploadedIds);
    return data.processing.filter((d) => ids.has(d.id)).length;
  }, [data, uploadedIds]);

  const total = uploadedIds.length;
  const done = Math.max(0, total - ourProcessing);

  useEffect(() => {
    if (stage !== "processing" || total === 0) return;
    const polledAfterUpload = dashboard.dataUpdatedAt > uploadDoneAt.current;
    if (polledAfterUpload && ourProcessing === 0) {
      setRunMs((m) => m ?? Date.now() - runStartAt.current);
      const t = setTimeout(() => setStage("results"), 450);
      return () => clearTimeout(t);
    }
  }, [stage, total, ourProcessing, dashboard.dataUpdatedAt]);

  const reset = () => {
    setStage("idle");
    setUploadedIds([]);
    setOpenGroup(null);
    setSavedIds(new Set());
    setSuccess(null);
    setRunMs(null);
  };

  const markSaved = (ids: string[]) => setSavedIds((prev) => new Set([...prev, ...ids]));

  const onSaveAll = async (ids: string[], storeCount: number) => {
    if (ids.length === 0) return;
    try {
      await Promise.all(ids.map((id) => bulkSave.mutateAsync(id)));
      markSaved(ids);
      setSuccess(storeCount);
    } catch {
      notifications.show({ color: "red", message: "บันทึกไม่สำเร็จบางรายการ" });
    }
  };

  return (
    <div className="flow-root">
      <div className="flow-wrap">
        <AnimatePresence mode="wait">
          <motion.div
            key={stage}
            initial={{ opacity: 0, y: 12, filter: "blur(4px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
            transition={{ duration: 0.36, ease: [0.22, 1, 0.36, 1] }}
          >
            {stage === "idle" && <Hero onDrop={onDrop} />}
            {stage === "processing" && (
              <Processing total={total} done={done} pending={upload.isPending} />
            )}
            {stage === "results" && data && (
              <Results
                data={data}
                runStartedAt={runStartedAt}
                runMs={runMs}
                runCount={uploadedIds.length}
                savedIds={savedIds}
                saving={bulkSave.isPending}
                onOpenGroup={setOpenGroup}
                onSaveAll={onSaveAll}
                onAddMore={reset}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {openGroup && (
          <StoreSheet
            key="sheet"
            visitIds={openGroup}
            onClose={() => setOpenGroup(null)}
            onSaved={(ids) => markSaved(ids)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {success != null && (
          <SuccessOverlay key="success" count={success} onDone={() => setSuccess(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------------------ Hero */

function Hero({ onDrop }: { onDrop: (files: File[]) => void }) {
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: { "image/*": [] },
    noClick: true,
    noKeyboard: true,
  });

  return (
    <div className="flow-hero flow-stage">
      <span className="flow-badge">
        <IconSparkles size={13} /> ผู้ช่วยขายอัจฉริยะ · ขับเคลื่อนด้วย AI
      </span>
      <h1 className="flow-title">
        ใบเสร็จทั้งเดือน
        <br />
        <span className="flow-title-grad">สรุปเสร็จในไม่กี่วินาที</span>
      </h1>
      <p className="flow-sub">
        โยนรูปใบเสร็จเข้ามาทั้งกอง — ระบบอ่าน แยกตามร้าน และสรุปสินค้ากับจำนวนให้อัตโนมัติ แม่นยำ
        ตรวจย้อนได้ และไม่ต้องคีย์เอง
      </p>

      <div
        {...getRootProps({
          className: "flow-drop",
          "data-active": isDragActive,
          onClick: open,
        })}
      >
        <input {...getInputProps()} />
        <div className="flow-drop-glow" />
        <div className="flow-drop-icon">
          <IconUpload size={26} />
        </div>
        <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.01em" }}>
          {isDragActive ? "วางได้เลย" : "ลากใบเสร็จมาวางที่นี่"}
        </div>
        <div style={{ color: "var(--ink-soft)", marginTop: 6, fontSize: 14 }}>
          หรือคลิกเพื่อเลือกรูป · วางพร้อมกันหลายใบ · JPG · PNG · HEIC
        </div>
      </div>

      <div className="flow-trust">
        <span className="flow-trust-item">
          <IconCheck size={13} /> อ่านลายมือไทยได้
        </span>
        <span className="flow-trust-item">
          <IconCheck size={13} /> จับคู่แคตตาล็อกอัตโนมัติ
        </span>
        <span className="flow-trust-item">
          <IconCheck size={13} /> เตือนเฉพาะใบที่มีปัญหา
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Processing */

const PROCESSING_STEPS = [
  "กำลังอ่านใบเสร็จ",
  "อ่านชื่อร้านและวันที่",
  "จับคู่สินค้ากับแคตตาล็อก",
  "แยกตามร้าน",
  "สรุปสินค้าและจำนวน",
];

function Processing({ total, done, pending }: { total: number; done: number; pending: boolean }) {
  const ratio = total > 0 ? done / total : 0.12;
  const R = 84;
  const CIRC = 2 * Math.PI * R;
  const offset = CIRC * (1 - ratio);
  const indeterminate = total === 0;

  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => (s + 1) % PROCESSING_STEPS.length), 1700);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flow-center-col flow-stage">
      <div className="flow-scan">
        <span className="flow-scan-pulse" />
        <span className="flow-scan-pulse" style={{ animationDelay: "1s" }} />
        <span className="flow-scan-pulse" style={{ animationDelay: "2s" }} />
        <svg className={`flow-scan-svg ${indeterminate ? "is-spin" : ""}`} viewBox="0 0 200 200">
          <defs>
            <linearGradient id="flowScanGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#6366f1" />
              <stop offset="55%" stopColor="#8b5cf6" />
              <stop offset="100%" stopColor="#38bdf8" />
            </linearGradient>
          </defs>
          <circle className="flow-scan-track" cx="100" cy="100" r={R} />
          <circle
            className="flow-scan-prog"
            cx="100"
            cy="100"
            r={R}
            strokeDasharray={CIRC}
            strokeDashoffset={offset}
            transform="rotate(-90 100 100)"
          />
        </svg>
        <div className="flow-scan-center">
          <div className="flow-ring-num">{total > 0 ? `${done}/${total}` : "…"}</div>
          <div style={{ fontSize: 12.5, color: "var(--ink-soft)", marginTop: 2 }}>
            {total > 0 ? "อ่านแล้ว" : "เริ่มอ่าน"}
          </div>
        </div>
      </div>

      <h2 className="flow-h2" style={{ marginTop: 36 }}>
        {pending ? "กำลังรับใบเสร็จ…" : "กำลังอ่านและจัดกลุ่มให้"}
      </h2>

      <div className="flow-scan-status">
        <AnimatePresence mode="wait">
          <motion.span
            key={step}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          >
            <span className="flow-scan-dot" />
            {PROCESSING_STEPS[step]}…
          </motion.span>
        </AnimatePresence>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- Results */

function Results({
  data,
  runStartedAt,
  runMs,
  runCount,
  savedIds,
  saving,
  onOpenGroup,
  onSaveAll,
  onAddMore,
}: {
  data: NonNullable<ReturnType<typeof useDashboard>["data"]>;
  runStartedAt: string;
  runMs: number | null;
  runCount: number;
  savedIds: Set<string>;
  saving: boolean;
  onOpenGroup: (ids: string[]) => void;
  onSaveAll: (ids: string[], storeCount: number) => void;
  onAddMore: () => void;
}) {
  const touched = useMemo(() => {
    const set = new Set<string>();
    for (const v of data.visits) {
      if (runStartedAt && v.updated_at >= runStartedAt) set.add(v.id);
    }
    return set;
  }, [data.visits, runStartedAt]);

  // Collapse same-store visits (across months) into one card.
  const groups = useMemo<StoreGroup[]>(() => {
    const m = new Map<string, StoreGroup>();
    for (const v of data.visits) {
      const key = v.store_id || v.store_key || v.store_label || v.id;
      let g = m.get(key);
      if (!g) {
        g = {
          key,
          label: v.store_label || v.store_key || "ร้านไม่มีชื่อ",
          visitIds: [],
          documentCount: 0,
          needsReviewCount: 0,
          periods: [],
          isNew: false,
          saved: true,
          latestUpdated: "",
        };
        m.set(key, g);
      }
      g.visitIds.push(v.id);
      g.documentCount += v.document_count;
      g.needsReviewCount += v.needs_review_count;
      if (v.report_period && !g.periods.includes(v.report_period)) g.periods.push(v.report_period);
      if (touched.has(v.id)) g.isNew = true;
      if (!isSaved(v, savedIds)) g.saved = false;
      if (v.updated_at > g.latestUpdated) g.latestUpdated = v.updated_at;
    }
    const arr = [...m.values()];
    for (const g of arr) g.periods.sort();
    // Order: needs-review (warning) first → unsaved → saved last.
    const rank = (g: StoreGroup) =>
      !g.saved && g.needsReviewCount > 0 ? 0 : g.saved ? 2 : 1;
    arr.sort((a, b) => {
      const ra = rank(a);
      const rb = rank(b);
      if (ra !== rb) return ra - rb;
      if (a.isNew !== b.isNew) return a.isNew ? -1 : 1;
      return b.latestUpdated.localeCompare(a.latestUpdated);
    });
    return arr;
  }, [data.visits, touched, savedIds]);

  const storeCount = groups.length;
  const receiptCount = data.visits.reduce((s, v) => s + v.document_count, 0);
  const unsavedGroups = groups.filter((g) => !g.saved);
  const unsavedIds = unsavedGroups.flatMap((g) => g.visitIds);
  const allSaved = storeCount > 0 && unsavedGroups.length === 0;
  const attention =
    data.counts.unknown_stores +
    data.counts.orphans +
    data.counts.non_receipts +
    data.counts.errors;

  return (
    <div className="flow-stage">
      <div className="flow-results-head" style={{ marginTop: 12 }}>
        <div>
          <h2 className="flow-h2">จัดกลุ่มให้เรียบร้อยแล้ว</h2>
          <p style={{ color: "var(--ink-soft)", marginTop: 6, fontSize: 15 }}>
            แตะร้านเพื่อดูสรุปสินค้าและตรวจใบเสร็จรายใบ — หรือบันทึกทั้งหมดทีเดียวก็ได้
          </p>
        </div>
        <div className="flow-kpis">
          <div>
            <div className="flow-kpi-num">{receiptCount}</div>
            <div className="flow-kpi-label">ใบเสร็จ</div>
          </div>
          <div>
            <div className="flow-kpi-num">{storeCount}</div>
            <div className="flow-kpi-label">ร้าน</div>
          </div>
        </div>
      </div>

      {storeCount === 0 ? (
        <div style={{ color: "var(--ink-soft)", padding: "32px 0" }}>
          ยังไม่มีร้านที่จัดกลุ่มได้ — ตรวจรายการด้านล่างที่ต้องการให้ช่วยดู
        </div>
      ) : (
        <div className="flow-grid">
          {groups.map((g, i) => (
            <StoreCard
              key={g.key}
              group={g}
              delay={Math.min(i, 8) * 0.05}
              onClick={() => onOpenGroup(g.visitIds)}
            />
          ))}
        </div>
      )}

      {attention > 0 && <AttentionPanel data={data} />}

      {storeCount > 0 && (
        <div className="flow-actionbar">
          {runMs != null && runCount > 0 && (
            <div className="flow-actionbar-stat">
              <span className="flow-stat-badge">
                <IconSparkles size={13} /> AI
              </span>
              <div className="flow-stat-metrics">
                <span className="flow-stat-metric">
                  <b>{runCount}</b> ใบ
                </span>
                <span className="flow-stat-dot" />
                <span className="flow-stat-metric">
                  <b>{(runMs / 1000).toFixed(1)}</b> วิ
                </span>
                <span className="flow-stat-dot" />
                <span className="flow-stat-metric flow-stat-muted">
                  เฉลี่ย <b>{(runMs / runCount / 1000).toFixed(1)}</b> วิ/ใบ
                </span>
              </div>
            </div>
          )}
          <button className="flow-ghost-btn flow-ghost-lg" onClick={onAddMore}>
            <IconUpload size={17} /> โยนใบเสร็จเพิ่ม
          </button>
          <button
            className="flow-primary-btn flow-primary-lg"
            disabled={allSaved || saving}
            onClick={() => onSaveAll(unsavedIds, unsavedGroups.length)}
          >
            {allSaved ? (
              <>
                <IconCheck size={18} /> บันทึกครบทุกร้านแล้ว
              </>
            ) : saving ? (
              "กำลังบันทึก…"
            ) : (
              <>
                <IconCheck size={18} /> บันทึกทั้งหมด · {unsavedGroups.length} ร้าน
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}

function periodLabel(periods: string[]): string {
  if (periods.length === 0) return "ไม่ระบุเดือน";
  if (periods.length === 1) return formatPeriod(periods[0]);
  return `${periods.length} เดือน`;
}

function StoreCard({
  group,
  delay,
  onClick,
}: {
  group: StoreGroup;
  delay: number;
  onClick: () => void;
}) {
  const qc = useQueryClient();
  const needsReview = !group.saved && group.needsReviewCount > 0;

  // Warm the visit-detail cache on hover so the sheet has data ready when it
  // opens — avoids the Loader→content reflow stuttering mid open-animation.
  const prefetch = () => {
    for (const id of group.visitIds) {
      qc.prefetchQuery({ queryKey: visitsKey.detail(id), queryFn: () => getVisit(id) });
    }
  };

  return (
    <motion.button
      className="flow-card"
      data-saved={group.saved}
      data-attention={needsReview}
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 26, delay }}
      whileHover={{ y: -4 }}
      onMouseEnter={prefetch}
      onFocus={prefetch}
      onClick={onClick}
    >
      <div className="flow-card-top">
        <div className="flow-card-store">
          <span className="flow-card-store-ic">
            <IconBuildingStore size={18} />
          </span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {group.label}
          </span>
        </div>
        {needsReview ? (
          <span className="flow-tag flow-tag-warn">
            <IconAlertTriangle size={11} /> ตรวจ {group.needsReviewCount}
          </span>
        ) : group.isNew && !group.saved ? (
          <span className="flow-tag flow-tag-new">ใหม่</span>
        ) : null}
      </div>

      <div className="flow-card-count">
        <b>{group.documentCount}</b>
        <span style={{ color: "var(--ink-soft)", fontSize: 14 }}>ใบเสร็จ</span>
      </div>

      <div className="flow-card-foot">
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <IconClock size={13} /> {periodLabel(group.periods)}
        </span>
        {group.saved ? (
          <span className="flow-chip flow-chip-ok">
            <IconCheck size={12} /> บันทึกแล้ว
          </span>
        ) : needsReview ? (
          <span
            style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--warn)" }}
          >
            ตรวจใบ <IconArrowRight size={14} />
          </span>
        ) : (
          <span
            style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--accent)" }}
          >
            ดูสรุป <IconArrowRight size={14} />
          </span>
        )}
      </div>
    </motion.button>
  );
}

/* ---------------------------------------------------------- Attention */

function AttentionPanel({ data }: { data: NonNullable<ReturnType<typeof useDashboard>["data"]> }) {
  const c = data.counts;
  const [lightbox, setLightbox] = useState<string | null>(null);
  const total = c.unknown_stores + c.orphans + c.non_receipts + c.errors;
  const hasResolve = data.unknown_stores.length > 0 || data.orphans.length > 0;

  return (
    <section className="flow-attn">
      <div className="flow-attn-head">
        <span className="flow-attn-ic">
          <IconAlertTriangle size={17} />
        </span>
        <div>
          <div className="flow-attn-title">ต้องการให้คุณช่วยดู · {total}</div>
          <div className="flow-attn-sub">
            ใบที่มั่นใจสูงระบบจัดเข้าร้านให้แล้ว — เหลือเฉพาะที่ยังไม่รู้จักร้าน หรือไม่ใช่ใบเสร็จ
          </div>
        </div>
      </div>

      {hasResolve && (
        <div className="flow-resolve-grid">
          {data.unknown_stores.map((d) => (
            <UnknownStoreCard key={d.id} doc={d} onView={setLightbox} />
          ))}
          {data.orphans.map((d) => (
            <OrphanCard key={d.id} doc={d} onView={setLightbox} />
          ))}
        </div>
      )}

      {data.non_receipts.length > 0 && (
        <NonReceiptStrip docs={data.non_receipts} onView={setLightbox} />
      )}

      {c.errors > 0 && (
        <div className="flow-attn-note">
          <IconAlertTriangle size={15} style={{ color: "var(--bad)" }} />
          อ่านไม่สำเร็จ {c.errors} ใบ — ลองโยนเข้ามาใหม่อีกครั้ง
        </div>
      )}

      {createPortal(
        <AnimatePresence>
          {lightbox && (
            <motion.div
              className="flow-lightbox"
              onClick={() => setLightbox(null)}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              <motion.div
                className="flow-lightbox-stage"
                onClick={(e) => e.stopPropagation()}
                initial={{ scale: 0.94, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.94, opacity: 0 }}
                transition={{ type: "spring", stiffness: 320, damping: 30 }}
              >
                <button
                  className="flow-lightbox-x"
                  onClick={() => setLightbox(null)}
                  aria-label="ปิด"
                >
                  <IconX size={18} />
                </button>
                <ImageCanvas src={lightbox} />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </section>
  );
}

function UnknownStoreCard({
  doc,
  onView,
}: {
  doc: DocumentListItem;
  onView: (url: string) => void;
}) {
  const [storeId, setStoreId] = useState<string | null>(null);
  const stores = useStores();
  const assign = useAssignStoreToDoc();
  const discard = useDiscardInboxDoc();

  const options = useMemo(
    () => (stores.data ?? []).map((s) => ({ value: s.id, label: s.name })),
    [stores.data],
  );

  const onAssign = async () => {
    if (!storeId) return;
    await assign.mutateAsync({ docId: doc.id, storeId });
    notifications.show({ color: "green", message: "ผูกร้านเรียบร้อย" });
  };

  return (
    <div className="flow-resolve-card">
      <div className="flow-resolve-top">
        <img
          className="flow-resolve-thumb"
          src={getDocumentImageUrl(doc.id)}
          alt={doc.filename}
          loading="lazy"
          onClick={() => onView(getDocumentImageUrl(doc.id))}
        />
        <div className="flow-resolve-info">
          <div className="flow-resolve-name">{doc.merchant_name || "ร้านที่อ่านได้"}</div>
          <div className="flow-resolve-meta">
            <IconClock size={12} /> {doc.document_date || "ไม่มีวันที่"} · {doc.item_count} รายการ
          </div>
        </div>
        <button
          className="flow-resolve-x"
          title="ทิ้งใบนี้"
          disabled={discard.isPending}
          onClick={() => discard.mutate(doc.id)}
        >
          <IconTrash size={15} />
        </button>
      </div>
      <Select
        placeholder="เลือกร้านที่มีอยู่…"
        data={options}
        value={storeId}
        onChange={setStoreId}
        searchable
        size="sm"
        nothingFoundMessage="ไม่พบร้าน"
        comboboxProps={{ withinPortal: true }}
      />
      <div className="flow-resolve-btns">
        <button
          className="flow-primary-btn flow-resolve-go"
          disabled={!storeId || assign.isPending}
          onClick={onAssign}
        >
          <IconCheck size={15} /> ผูกร้านนี้
        </button>
      </div>
    </div>
  );
}

function OrphanCard({ doc, onView }: { doc: DocumentListItem; onView: (url: string) => void }) {
  const [storeId, setStoreId] = useState<string | null>(null);
  const stores = useStores();
  const assign = useAssignStoreToDoc();
  const discard = useDiscardInboxDoc();

  const options = useMemo(
    () => (stores.data ?? []).map((s) => ({ value: s.id, label: s.name })),
    [stores.data],
  );

  const onAssign = async () => {
    if (!storeId) return;
    await assign.mutateAsync({ docId: doc.id, storeId });
    notifications.show({ color: "green", message: "ผูกร้านเรียบร้อย" });
  };

  return (
    <div className="flow-resolve-card">
      <div className="flow-resolve-top">
        <img
          className="flow-resolve-thumb"
          src={getDocumentImageUrl(doc.id)}
          alt={doc.filename}
          loading="lazy"
          onClick={() => onView(getDocumentImageUrl(doc.id))}
        />
        <div className="flow-resolve-info">
          <div className="flow-resolve-name" style={{ color: "var(--ink-soft)" }}>
            อ่านชื่อร้านไม่ออก
          </div>
          <div className="flow-resolve-meta">
            <IconClock size={12} /> {doc.document_date || "ไม่มีวันที่"} · {doc.item_count} รายการ
          </div>
        </div>
        <button
          className="flow-resolve-x"
          title="ทิ้งใบนี้"
          disabled={discard.isPending}
          onClick={() => discard.mutate(doc.id)}
        >
          <IconTrash size={15} />
        </button>
      </div>
      <Select
        placeholder="เลือกร้านที่มีอยู่…"
        data={options}
        value={storeId}
        onChange={setStoreId}
        searchable
        size="sm"
        nothingFoundMessage="ไม่พบร้าน"
        comboboxProps={{ withinPortal: true }}
      />
      <div className="flow-resolve-btns">
        <button
          className="flow-primary-btn flow-resolve-go"
          disabled={!storeId || assign.isPending}
          onClick={onAssign}
        >
          <IconCheck size={15} /> ผูกร้านนี้
        </button>
      </div>
    </div>
  );
}

function NonReceiptStrip({
  docs,
  onView,
}: {
  docs: DocumentListItem[];
  onView: (url: string) => void;
}) {
  return (
    <div className="flow-nonreceipt">
      <div className="flow-nonreceipt-head">
        <IconPhotoOff size={16} /> ไม่ใช่ใบเสร็จ {docs.length} รูป · ระบบข้ามให้แล้ว (ลบอัตโนมัติใน 7 วัน) — กด ✕
        เพื่อลบเลยก็ได้
      </div>
      <div className="flow-thumbs" style={{ marginBottom: 0 }}>
        {docs.map((d) => (
          <NonReceiptThumb key={d.id} doc={d} onView={onView} />
        ))}
      </div>
    </div>
  );
}

function NonReceiptThumb({
  doc,
  onView,
}: {
  doc: DocumentListItem;
  onView: (url: string) => void;
}) {
  const discard = useDiscardInboxDoc();
  return (
    <div className="flow-nr-thumb">
      <img
        className="flow-thumb"
        src={getDocumentImageUrl(doc.id)}
        alt={doc.filename}
        loading="lazy"
        onClick={() => onView(getDocumentImageUrl(doc.id))}
      />
      <button
        className="flow-nr-del"
        title="ลบรูปนี้"
        aria-label="ลบรูปนี้"
        disabled={discard.isPending}
        onClick={() => discard.mutate(doc.id)}
      >
        <IconX size={12} />
      </button>
    </div>
  );
}

/* ------------------------------------------------------------ StoreSheet */

interface MergedStore {
  label: string;
  periods: string[];
  documents: DocumentListItem[];
  aggregate: VisitAggregateRow[];
}

function mergeVisits(details: VisitDetail[]): MergedStore {
  const documents: DocumentListItem[] = [];
  const periods: string[] = [];
  const rows = new Map<string, VisitAggregateRow>();
  let label = "ร้าน";
  for (const v of details) {
    label = v.store_label || v.store_key || label;
    if (v.report_period && !periods.includes(v.report_period)) periods.push(v.report_period);
    documents.push(...v.documents);
    for (const r of v.aggregate) {
      const key = r.product_code || `~${r.display_name}`;
      const ex = rows.get(key);
      if (ex) {
        ex.total_quantity += r.total_quantity;
        ex.source_count += r.source_count;
        ex.source_doc_ids = [...ex.source_doc_ids, ...r.source_doc_ids];
        ex.is_catalog_match = ex.is_catalog_match || r.is_catalog_match;
        for (const u of r.units_seen) if (!ex.units_seen.includes(u)) ex.units_seen.push(u);
        if (ex.unit && r.unit && ex.unit !== r.unit && !ex.units_seen.includes(r.unit)) {
          ex.units_seen.push(r.unit);
        }
      } else {
        rows.set(key, {
          ...r,
          source_doc_ids: [...r.source_doc_ids],
          units_seen: [...r.units_seen],
        });
      }
    }
  }
  periods.sort();
  const aggregate = [...rows.values()].sort((a, b) => b.total_quantity - a.total_quantity);
  return { label, periods, documents, aggregate };
}

function StoreSheet({
  visitIds,
  onClose,
  onSaved,
}: {
  visitIds: string[];
  onClose: () => void;
  onSaved: (ids: string[]) => void;
}) {
  const markReviewed = useMarkVisitReviewed();
  const [justSaved, setJustSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const visitResults = useQueries({
    queries: visitIds.map((id) => ({
      queryKey: visitsKey.detail(id),
      queryFn: () => getVisit(id),
    })),
  });
  const details = visitResults.map((r) => r.data).filter(Boolean) as VisitDetail[];
  const merged = details.length ? mergeVisits(details) : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (openIndex !== null) setOpenIndex(null);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, openIndex]);

  const docs = merged?.documents ?? [];
  const flaggedCount = docs.filter(isFlagged).length;
  const multi = docs.length > 1;
  const catalogRows = (merged?.aggregate ?? []).filter((r) => r.is_catalog_match);
  const unknownRows = (merged?.aggregate ?? []).filter((r) => !r.is_catalog_match);
  const catalogCodes = new Set(
    catalogRows.map((r) => r.product_code).filter((c): c is string => !!c),
  );

  const onSave = async () => {
    setSaving(true);
    await Promise.all(visitIds.map((id) => markReviewed.mutateAsync(id)));
    onSaved(visitIds);
    setSaving(false);
    setJustSaved(true);
    notifications.show({
      color: "green",
      icon: <IconCheck size={16} />,
      message: "บันทึกร้านนี้แล้ว",
    });
    setTimeout(onClose, 750);
  };

  return (
    <motion.div
      className="flow-overlay"
      onClick={onClose}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
    >
      <motion.div
        className="flow-sheet"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 64, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 48, scale: 0.985 }}
        transition={{ type: "spring", stiffness: 360, damping: 34 }}
      >
        <div className="flow-sheet-head">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="flow-card-store-ic">
              <IconBuildingStore size={18} />
            </span>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em" }}>
                {merged?.label || "ร้าน"}
              </div>
              <div style={{ color: "var(--ink-soft)", fontSize: 13 }}>
                {merged ? periodLabel(merged.periods) : ""} · {docs.length} ใบเสร็จ
              </div>
            </div>
          </div>
          <button className="flow-ghost-btn" onClick={onClose}>
            <IconX size={18} />
          </button>
        </div>

        <div className="flow-sheet-body">
          {!merged && (
            <div style={{ display: "grid", placeItems: "center", padding: 60 }}>
              <Loader />
            </div>
          )}

          {merged && (
            <>
              {flaggedCount === 0 ? (
                <div className="flow-chip flow-chip-ok" style={{ marginBottom: 18 }}>
                  <IconCheck size={13} /> ทุกใบมั่นใจสูง — ไม่ต้องตรวจเพิ่ม
                </div>
              ) : (
                <div className="flow-chip flow-chip-q" style={{ marginBottom: 18 }}>
                  <IconAlertTriangle size={13} /> มี {flaggedCount} ใบที่ควรตรวจ —
                  แตะใบขอบเหลืองด้านล่าง
                </div>
              )}

              {/* Clean read-only summary — only catalog-matched products count. */}
              <div className="flow-section-label">
                {multi ? "สรุปรวมทั้งร้าน (ทุกใบ)" : "สรุปสินค้า"}
              </div>
              {catalogRows.length === 0 ? (
                <div style={{ color: "var(--ink-soft)", padding: "12px 0" }}>
                  ยังไม่มีสินค้าที่ตรงแคตตาล็อกในร้านนี้
                </div>
              ) : (
                <table className="flow-tbl">
                  <thead>
                    <tr>
                      <th>สินค้า</th>
                      <th>ที่มา</th>
                      <th style={{ textAlign: "right" }}>จำนวนรวม</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalogRows.map((row, i) => (
                      <AggregateRow key={`${row.product_code ?? "x"}-${i}`} row={row} />
                    ))}
                  </tbody>
                </table>
              )}

              {/* Off-catalog items — warned, not counted, one-click clear. */}
              {unknownRows.length > 0 && (
                <UnknownPile docs={docs} rows={unknownRows} catalogCodes={catalogCodes} />
              )}

              {/* Receipt strip — tap one to verify against its image & edit. */}
              {docs.length > 0 && (
                <>
                  <div className="flow-thumb-hint" style={{ marginTop: 22 }}>
                    <IconPhoto size={13} /> ใบเสร็จ — แตะเพื่อดูรูปจริงและแก้สิ่งที่ระบบอ่านได้
                  </div>
                  <div className="flow-thumbs">
                    {docs.map((doc, i) => (
                      <img
                        key={doc.id}
                        className="flow-thumb"
                        data-flag={isFlagged(doc)}
                        src={getDocumentImageUrl(doc.id)}
                        alt={doc.filename}
                        loading="lazy"
                        onClick={() => setOpenIndex(i)}
                      />
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <div className="flow-sheet-foot">
          <span style={{ color: "var(--ink-soft)", fontSize: 13 }}>
            {merged ? `${catalogRows.length} สินค้าในรายงาน` : ""}
            {unknownRows.length > 0 && (
              <span style={{ color: "var(--warn)" }}> · {unknownRows.length} ไม่นับ</span>
            )}
          </span>
          <button
            className="flow-primary-btn"
            data-ok={justSaved}
            disabled={saving || justSaved || !merged}
            onClick={onSave}
          >
            {justSaved ? (
              <>
                <IconCheck size={17} /> บันทึกแล้ว
              </>
            ) : saving ? (
              "กำลังบันทึก…"
            ) : (
              <>
                <IconCheck size={17} /> บันทึกร้านนี้
              </>
            )}
          </button>
        </div>
      </motion.div>

      <AnimatePresence>
        {openIndex !== null && docs[openIndex] && (
          <ReceiptDetail
            docs={docs}
            index={openIndex}
            onIndex={setOpenIndex}
            onClose={() => setOpenIndex(null)}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/** Off-catalog items: the system isn't sure what they are, so they're piled
 *  here, NOT counted in the report. One button clears them all. */
function UnknownPile({
  docs,
  rows,
  catalogCodes,
}: {
  docs: DocumentListItem[];
  rows: VisitAggregateRow[];
  catalogCodes: Set<string>;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const onClear = async () => {
    setBusy(true);
    try {
      const fulls = await Promise.all(
        docs.map((d) =>
          qc.fetchQuery({ queryKey: qk.document(d.id), queryFn: () => getDocument(d.id) }),
        ),
      );
      const targets: { docId: string; itemId: string }[] = [];
      for (const full of fulls) {
        for (const it of full.items) {
          const known = !!it.product_code && catalogCodes.has(it.product_code);
          if (!known) targets.push({ docId: full.id, itemId: it.id });
        }
      }
      await Promise.all(targets.map((t) => deleteItem(t.docId, t.itemId)));
      qc.invalidateQueries({ queryKey: ["visits"] });
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      notifications.show({
        color: "green",
        message: `ลบสินค้านอกแคตตาล็อก ${targets.length} รายการแล้ว`,
      });
    } catch {
      notifications.show({ color: "red", message: "ลบไม่สำเร็จ" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flow-unknown">
      <div className="flow-unknown-head">
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          <IconAlertTriangle size={15} /> นอกแคตตาล็อก · ไม่นับในสรุป ({rows.length})
        </span>
        <button className="flow-mini-btn flow-mini-ghost" disabled={busy} onClick={onClear}>
          ลบทั้งหมด
        </button>
      </div>
      <div style={{ color: "var(--ink-soft)", fontSize: 12.5, marginBottom: 8 }}>
        ระบบไม่มั่นใจว่าเป็นสินค้าอะไร จึงไม่รวมในรายงาน — ปล่อยไว้ก็ได้ หรือลบทิ้งถ้าไม่ต้องการ
      </div>
      {rows.map((r, i) => (
        <div className="flow-unknown-row" key={`${r.display_name}-${i}`}>
          <span className="flow-chip flow-chip-q">?</span>
          <span style={{ flex: 1, minWidth: 0 }}>{r.display_name}</span>
          <span className="flow-qty-unit" style={{ color: "var(--ink-soft)" }}>
            {r.total_quantity} {r.unit || ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ----------- ReceiptDetail: image left, editable items right ----------- */

function ReceiptDetail({
  docs,
  index,
  onIndex,
  onClose,
}: {
  docs: DocumentListItem[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const meta = docs[index];
  const doc = useDocument(meta.id);
  const approve = useApproveDocument();
  const del = useDeleteDocument();
  const qc = useQueryClient();
  const d = doc.data;
  const flagged = isFlagged(meta);
  const reasons = d ? reviewReasons(d) : [];
  const multi = docs.length > 1;

  const onConfirm = async () => {
    await approve.mutateAsync(meta.id);
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    notifications.show({
      color: "green",
      icon: <IconCheck size={16} />,
      message: "ยืนยันใบนี้แล้ว",
    });
    if (index < docs.length - 1) onIndex(index + 1);
    else onClose();
  };

  const onDelete = async () => {
    await del.mutateAsync(meta.id);
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    notifications.show({ message: "ย้ายใบนี้ไปถังขยะแล้ว" });
    // The docs prop is now stale; close back to the sheet, which refetches.
    onClose();
  };

  return (
    <motion.div
      className="flow-rcpt"
      onClick={onClose}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <motion.div
        className="flow-rcpt-card"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 36, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 24, scale: 0.98 }}
        transition={{ type: "spring", stiffness: 340, damping: 32 }}
      >
        <div className="flow-rcpt-img">
          <ImageCanvas
            src={getDocumentImageUrl(meta.id)}
            alt={meta.filename}
            downloadFilename={meta.filename}
          />
        </div>
        <div className="flow-rcpt-side">
          <div className="flow-rcpt-side-head">
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {multi && (
                  <div className="flow-rcpt-nav">
                    <button
                      disabled={index === 0}
                      onClick={() => onIndex(index - 1)}
                      aria-label="ใบก่อนหน้า"
                    >
                      <IconChevronLeft size={16} />
                    </button>
                    <span>
                      ใบที่ {index + 1}/{docs.length}
                    </span>
                    <button
                      disabled={index === docs.length - 1}
                      onClick={() => onIndex(index + 1)}
                      aria-label="ใบถัดไป"
                    >
                      <IconChevronRight size={16} />
                    </button>
                  </div>
                )}
              </div>
              <div
                style={{
                  fontWeight: 700,
                  fontSize: 17,
                  letterSpacing: "-0.01em",
                  marginTop: multi ? 6 : 0,
                }}
              >
                {d?.merchant_name || meta.merchant_name || "ใบเสร็จ"}
              </div>
              <div style={{ color: "var(--ink-soft)", fontSize: 13 }}>
                ระบบอ่านได้ดังนี้ — แก้ได้เลยถ้าไม่ตรง
                {meta.document_date ? ` · ${meta.document_date}` : ""}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flex: "none" }}>
              <button
                className="flow-rcpt-del"
                title="ลบใบนี้ (ย้ายไปถังขยะ)"
                aria-label="ลบใบนี้"
                disabled={del.isPending}
                onClick={onDelete}
              >
                <IconTrash size={16} />
              </button>
              <button className="flow-ghost-btn" onClick={onClose}>
                <IconX size={18} />
              </button>
            </div>
          </div>

          <div className="flow-rcpt-items">
            {doc.isPending && (
              <div style={{ display: "grid", placeItems: "center", padding: 40 }}>
                <Loader size="sm" />
              </div>
            )}
            {d && flagged && reasons.length > 0 && (
              <div className="flow-review-why">
                <div className="flow-review-why-head">
                  <IconAlertTriangle size={14} /> ทำไมต้องตรวจ
                </div>
                <ul>
                  {reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            {d && d.items.length === 0 && (
              <div style={{ color: "var(--ink-soft)", padding: "20px 0" }}>
                ไม่พบรายการสินค้าในใบนี้
              </div>
            )}
            {d?.items.map((it) => (
              <EditableItem key={it.id} docId={meta.id} item={it} />
            ))}
          </div>

          <div className="flow-rcpt-foot">
            <span
              style={{
                color: flagged ? "var(--warn)" : "var(--good)",
                fontSize: 13,
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              {flagged ? <IconAlertTriangle size={14} /> : <IconCheck size={14} />}
              {flagged ? "ใบนี้ควรตรวจ" : "ใบนี้มั่นใจสูง"}
            </span>
            <button
              className="flow-primary-btn"
              disabled={approve.isPending || !d}
              onClick={onConfirm}
            >
              <IconCheck size={17} /> ยืนยันว่าถูกต้อง
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

function AggregateRow({ row }: { row: VisitAggregateRow }) {
  const mixedUnit = row.units_seen.length > 1;
  return (
    <tr>
      <td>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          {row.is_catalog_match ? (
            <IconCheck size={15} className="flow-check-mini" aria-label="ตรงแคตตาล็อก" />
          ) : (
            <span className="flow-chip flow-chip-q">?</span>
          )}
          <span style={{ fontWeight: 600 }}>{row.display_name}</span>
        </div>
      </td>
      <td>
        {row.manufacturer ? (
          <span
            className={`flow-chip ${isOurs(row.manufacturer) ? "flow-chip-ok" : "flow-chip-mute"}`}
          >
            {isOurs(row.manufacturer) ? "สิงห์" : "คู่แข่ง"}
          </span>
        ) : (
          <span style={{ color: "var(--ink-faint)" }}>—</span>
        )}
      </td>
      <td>
        <div className="flow-qty-cell">
          <span className="flow-qty">{row.total_quantity}</span>
          <span className="flow-qty-unit">{row.unit || ""}</span>
        </div>
        {mixedUnit && (
          <div className="flow-chip flow-chip-q" style={{ marginTop: 4, float: "right" }}>
            หน่วยปนกัน: {row.units_seen.join(", ")}
          </div>
        )}
      </td>
    </tr>
  );
}

function EditableItem({ docId, item }: { docId: string; item: DocumentItemData }) {
  const update = useUpdateItem(docId);
  const del = useDeleteItem(docId);
  const initialName = item.product_name_normalized || item.product_name_raw || "";
  const [name, setName] = useState(initialName);
  const [qty, setQty] = useState(item.quantity == null ? "" : String(item.quantity));

  const ac = useAutocomplete("product", name, 8);
  const codeByValue = useMemo(() => {
    const m = new Map<string, string | null | undefined>();
    for (const o of ac.data ?? []) m.set(o.value, o.code);
    return m;
  }, [ac.data]);
  const nameOptions = useMemo(() => (ac.data ?? []).map((o) => o.value), [ac.data]);

  const saveQty = () => {
    const n = qty.trim() === "" ? null : Number(qty);
    if (n != null && Number.isNaN(n)) return;
    if (n === item.quantity) return;
    update.mutate({ itemId: item.id, data: { quantity: n } });
  };

  const saveName = () => {
    const v = name.trim();
    if (!v || v === initialName) return;
    const code = codeByValue.get(v);
    const data: Record<string, unknown> =
      code != null
        ? { product_name_normalized: v, product_code: code }
        : { product_name_normalized: v };
    update.mutate({ itemId: item.id, data });
  };

  const isCatalog = !!item.product_code;

  return (
    <div className="flow-eitem" data-unknown={!isCatalog}>
      <span className={`flow-dot ${isCatalog ? "flow-dot-ok" : "flow-dot-warn"}`} />
      <div className="flow-eitem-name">
        <Autocomplete
          variant="unstyled"
          value={name}
          data={nameOptions}
          onChange={setName}
          onBlur={saveName}
          onOptionSubmit={() => requestAnimationFrame(saveName)}
          placeholder="ชื่อสินค้า"
          aria-label="ชื่อสินค้า"
          comboboxProps={{ withinPortal: true }}
        />
        {isCatalog ? (
          <span className="flow-eitem-code">{item.product_code}</span>
        ) : (
          <span className="flow-eitem-code flow-eitem-unknown">
            <IconAlertTriangle size={11} style={{ verticalAlign: "-1px" }} /> นอกแคตตาล็อก · ไม่นับ
          </span>
        )}
      </div>
      <input
        className="flow-qty-input"
        inputMode="numeric"
        value={qty}
        onChange={(e) => setQty(e.currentTarget.value)}
        onBlur={saveQty}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        aria-label="จำนวน"
      />
      <span className="flow-qty-unit" style={{ minWidth: 34 }}>
        {item.unit || ""}
      </span>
      <ActionIcon
        variant="subtle"
        color="red"
        size="md"
        aria-label="ลบรายการ"
        loading={del.isPending}
        onClick={() => del.mutate(item.id)}
      >
        <IconTrash size={16} />
      </ActionIcon>
    </div>
  );
}

/* ------------------------------------------------------- SuccessOverlay */

function SuccessOverlay({ count, onDone }: { count: number; onDone: () => void }) {
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    const t = setTimeout(() => doneRef.current(), 2200);
    return () => clearTimeout(t);
  }, []);
  return (
    <motion.div
      className="flow-success"
      onClick={onDone}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
    >
      <motion.div
        className="flow-success-inner"
        initial={{ scale: 0.85, opacity: 0, y: 8 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 22 }}
      >
        <svg className="flow-check" viewBox="0 0 52 52">
          <circle className="flow-check-ring" cx="26" cy="26" r="24" />
          <path className="flow-check-mark" d="M15 27 l8 8 l15 -16" />
        </svg>
        <div className="flow-success-title">บันทึกเรียบร้อย</div>
        <div className="flow-success-sub">บันทึกแล้ว {count} ร้าน</div>
      </motion.div>
    </motion.div>
  );
}
