/**
 * Compact audit-trail timeline shown on the Review page.
 * Collapsible "ประวัติการแก้ไข" panel that lists every event the backend
 * recorded for this document.
 */

import { useState } from "react";
import {
  Accordion,
  Badge,
  Group,
  Loader,
  Stack,
  Text,
  Timeline,
  Tooltip,
} from "@mantine/core";
import {
  Activity,
  AlertTriangle,
  Brain,
  CheckCircle2,
  Edit3,
  FileUp,
  MinusCircle,
  PlusCircle,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Trash2,
  Undo2,
} from "lucide-react";
import { useDocumentHistory } from "@/api/queries";
import type { DocumentEventItem } from "@/api/client";

const EVENT_META: Record<string, { icon: typeof Activity; color: string; label: string }> = {
  uploaded: { icon: FileUp, color: "blue", label: "อัปโหลด" },
  extracted: { icon: Sparkles, color: "indigo", label: "AI ดึงข้อมูล" },
  extraction_failed: { icon: AlertTriangle, color: "red", label: "AI ผิดพลาด" },
  edited: { icon: Edit3, color: "yellow", label: "แก้ไขข้อมูล" },
  item_added: { icon: PlusCircle, color: "green", label: "เพิ่มรายการ" },
  item_updated: { icon: Edit3, color: "yellow", label: "แก้ไขรายการ" },
  item_deleted: { icon: MinusCircle, color: "red", label: "ลบรายการ" },
  approved: { icon: CheckCircle2, color: "green", label: "อนุมัติ" },
  reextracted: { icon: RotateCcw, color: "violet", label: "ประมวลผลใหม่" },
  trashed: { icon: Trash2, color: "red", label: "ย้ายไปถังขยะ" },
  restored: { icon: Undo2, color: "green", label: "กู้คืน" },
  purged: { icon: Trash2, color: "red", label: "ลบถาวร" },
  alias_learned: { icon: Brain, color: "grape", label: "AI เรียนรู้" },
  product_alias_learned: { icon: Brain, color: "grape", label: "AI เรียนรู้สินค้า" },
  product_alias_skipped: { icon: AlertTriangle, color: "orange", label: "ไม่บันทึก alias" },
  fraud_detected: { icon: ShieldAlert, color: "red", label: "พบความเสี่ยง" },
};

function formatEventDetail(ev: DocumentEventItem): string | null {
  const p = ev.payload;
  if (!p) return null;
  if (ev.event_type === "edited" && p.changed && typeof p.changed === "object") {
    const fields = Object.keys(p.changed as Record<string, unknown>);
    return `${fields.length} ฟิลด์: ${fields.slice(0, 3).join(", ")}${fields.length > 3 ? "…" : ""}`;
  }
  if (ev.event_type === "extracted") {
    const conf = p.confidence as number | undefined;
    const items = p.items as number | undefined;
    const parts: string[] = [];
    if (conf !== undefined) parts.push(`confidence ${(conf * 100).toFixed(0)}%`);
    if (items !== undefined) parts.push(`${items} รายการ`);
    return parts.join(" · ") || null;
  }
  if (ev.event_type === "uploaded") {
    const size = p.size_bytes as number | undefined;
    return size ? `${(size / 1024).toFixed(1)} KB` : null;
  }
  if (ev.event_type === "item_added" || ev.event_type === "item_deleted") {
    return typeof p.name === "string" ? p.name : null;
  }
  if (ev.event_type === "item_updated" && Array.isArray(p.fields)) {
    return (p.fields as string[]).join(", ");
  }
  if (ev.event_type === "alias_learned" || ev.event_type === "product_alias_learned") {
    return `${p.source} → ${p.canonical}`;
  }
  if (ev.event_type === "product_alias_skipped") {
    const reason = p.reason as string | undefined;
    const label =
      reason === "catalog_conflict"
        ? "ชนกับ PRODUCT_CATALOG — มีผลเฉพาะใบนี้"
        : reason === "semantic_jump"
          ? "ต่างกันมากเกินไป — มีผลเฉพาะใบนี้"
          : reason || "ไม่บันทึก";
    return `${label} (${p.source} ≠ ${p.canonical})`;
  }
  if (ev.event_type === "extraction_failed") {
    return typeof p.error === "string" ? p.error : null;
  }
  return null;
}

export function DocumentHistory({ documentId }: { documentId: string }) {
  const { data: events = [], isPending } = useDocumentHistory(documentId);
  const [opened, setOpened] = useState<string | null>(null);

  return (
    <Accordion
      value={opened}
      onChange={setOpened}
      variant="contained"
    >
      <Accordion.Item value="history">
        <Accordion.Control icon={<Activity size={16} />}>
          <Group justify="space-between" pr="md">
            <Text size="sm" fw={600}>ประวัติการทำงาน</Text>
            <Badge size="xs" variant="light">{events.length}</Badge>
          </Group>
        </Accordion.Control>
        <Accordion.Panel>
          {isPending ? (
            <Group justify="center" py="md">
              <Loader size="sm" />
            </Group>
          ) : events.length === 0 ? (
            <Text size="sm" c="dimmed" ta="center" py="md">ยังไม่มีประวัติ</Text>
          ) : (
            <Timeline active={events.length} bulletSize={22} lineWidth={2}>
              {events.map((ev) => {
                const meta = EVENT_META[ev.event_type] ?? {
                  icon: Activity,
                  color: "gray",
                  label: ev.event_type,
                };
                const Icon = meta.icon;
                const detail = formatEventDetail(ev);
                return (
                  <Timeline.Item
                    key={ev.id}
                    bullet={<Icon size={12} />}
                    color={meta.color}
                    title={
                      <Group gap="xs">
                        <Text size="sm" fw={500}>{meta.label}</Text>
                        <Tooltip label={ev.actor === "system" ? "ระบบ/AI" : "ผู้ใช้"}>
                          <Badge size="xs" variant="light" color={ev.actor === "system" ? "gray" : "indigo"}>
                            {ev.actor === "system" ? "AI" : "user"}
                          </Badge>
                        </Tooltip>
                      </Group>
                    }
                  >
                    {detail && (
                      <Text size="xs" c="dimmed" lineClamp={2}>{detail}</Text>
                    )}
                    <Text size="xs" c="dimmed">
                      {ev.created_at ? new Date(ev.created_at).toLocaleString("th-TH") : "-"}
                    </Text>
                  </Timeline.Item>
                );
              })}
            </Timeline>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}

export default DocumentHistory;
