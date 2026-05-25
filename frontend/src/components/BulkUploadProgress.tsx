/**
 * Live progress panel for a bulk upload batch.
 *
 * Wires one SSE stream per document and renders an animated tile grid so the
 * viewer can SEE the pipeline working: N tiles spinning, popping green as
 * extractions finish wave by wave. Built for the demo — the parallel pool
 * already runs; this just makes its rhythm visible.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActionIcon,
  Badge,
  Card,
  Group,
  Paper,
  Progress,
  Text,
  Tooltip,
} from "@mantine/core";
import { CheckCircle2, Loader2, X, AlertCircle } from "lucide-react";
import { useDocumentStream } from "../hooks/useDocumentStream";

type Status = "processing" | "extracted" | "not_receipt" | "error";

export interface BulkUploadItem {
  id: string;
  filename: string;
}

interface Props {
  items: BulkUploadItem[];
  /** Concurrent extraction cap (from EXTRACTION_CONCURRENCY). Used for the
   * "N พร้อมกัน" label. */
  concurrency?: number;
  /** Called when user dismisses the panel after batch completes. */
  onDismiss?: () => void;
}

export function BulkUploadProgress({
  items,
  concurrency = 4,
  onDismiss,
}: Props) {
  const [statuses, setStatuses] = useState<Record<string, Status>>(() =>
    Object.fromEntries(items.map((i) => [i.id, "processing" as Status])),
  );
  const [recentlyDone, setRecentlyDone] = useState<Set<string>>(new Set());
  const startedAt = useRef(performance.now());
  const finishedAt = useRef<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Tick the elapsed timer every 100ms until the batch is fully done.
  useEffect(() => {
    const tick = () => {
      const now = performance.now();
      const end = finishedAt.current ?? now;
      setElapsed((end - startedAt.current) / 1000);
    };
    tick();
    const t = setInterval(tick, 100);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => {
    let done = 0;
    let processing = 0;
    let failed = 0;
    for (const s of Object.values(statuses)) {
      if (s === "extracted" || s === "not_receipt") done += 1;
      else if (s === "error") failed += 1;
      else processing += 1;
    }
    return { done, processing, failed };
  }, [statuses]);

  const allDone = counts.processing === 0;
  useEffect(() => {
    if (allDone && finishedAt.current === null) {
      finishedAt.current = performance.now();
    }
  }, [allDone]);

  const pct = items.length === 0 ? 0 : (counts.done / items.length) * 100;
  // Visible concurrency = min(remaining unfinished, configured cap).
  const liveConcurrency = Math.min(counts.processing, concurrency);

  return (
    <Card
      withBorder
      radius="md"
      p="md"
      style={{
        borderLeft: `4px solid ${
          allDone
            ? counts.failed
              ? "var(--mantine-color-orange-5)"
              : "var(--mantine-color-green-5)"
            : "var(--mantine-color-indigo-5)"
        }`,
      }}
    >
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          {allDone ? (
            counts.failed > 0 ? (
              <AlertCircle size={20} color="var(--mantine-color-orange-6)" />
            ) : (
              <CheckCircle2 size={20} color="var(--mantine-color-green-6)" />
            )
          ) : (
            <Loader2
              size={20}
              color="var(--mantine-color-indigo-6)"
              className="animate-spin"
            />
          )}
          <Text fw={600} size="md">
            {allDone
              ? counts.failed > 0
                ? `เสร็จแล้ว ${counts.done}/${items.length} (ผิดพลาด ${counts.failed})`
                : `ประมวลผลเสร็จ ${items.length} ไฟล์`
              : `AI กำลังอ่าน ${liveConcurrency} ไฟล์พร้อมกัน`}
          </Text>
          {!allDone && (
            <Badge variant="light" color="indigo" size="lg">
              {counts.done}/{items.length}
            </Badge>
          )}
        </Group>
        <Group gap="sm" wrap="nowrap">
          <Text size="sm" c="dimmed" ff="monospace">
            ⏱ {elapsed.toFixed(1)}s
          </Text>
          {allDone && onDismiss && (
            <ActionIcon variant="subtle" color="gray" onClick={onDismiss} aria-label="ปิด">
              <X size={16} />
            </ActionIcon>
          )}
        </Group>
      </Group>

      <Progress
        value={pct}
        animated={!allDone}
        striped={!allDone}
        color={allDone ? (counts.failed ? "orange" : "green") : "indigo"}
        size="md"
        radius="xl"
        mb="md"
      />

      <Group gap="xs" align="flex-start">
        {items.map((it) => (
          <DocTile
            key={it.id}
            item={it}
            status={statuses[it.id] ?? "processing"}
            justFinished={recentlyDone.has(it.id)}
            onStatus={(s) => {
              setStatuses((prev) =>
                prev[it.id] === s ? prev : { ...prev, [it.id]: s },
              );
              if (s !== "processing") {
                setRecentlyDone((prev) => new Set(prev).add(it.id));
                // Pop animation lasts 800ms.
                setTimeout(() => {
                  setRecentlyDone((prev) => {
                    const next = new Set(prev);
                    next.delete(it.id);
                    return next;
                  });
                }, 800);
              }
            }}
          />
        ))}
      </Group>

      {allDone && (
        <Paper bg="var(--mantine-color-default-hover)" p="xs" radius="sm" mt="md">
          <Group justify="space-between">
            <Text size="sm">
              <Text component="span" fw={600}>
                {items.length} ใบ
              </Text>{" "}
              ใน{" "}
              <Text component="span" fw={600} ff="monospace">
                {elapsed.toFixed(1)} วินาที
              </Text>{" "}
              · ขนานสูงสุด{" "}
              <Text component="span" fw={600}>
                {concurrency}
              </Text>{" "}
              ไฟล์ · เฉลี่ย{" "}
              <Text component="span" fw={600} ff="monospace">
                {(elapsed / items.length).toFixed(1)}s
              </Text>
              /ไฟล์
            </Text>
            <Text size="xs" c="dimmed">
              เทียบทำมือ ~{Math.round((items.length * 180) / 60)} นาที → ประหยัด{" "}
              {Math.round(((items.length * 180 - elapsed) / 60) * 10) / 10} นาที
            </Text>
          </Group>
        </Paper>
      )}
    </Card>
  );
}

function DocTile({
  item,
  status,
  justFinished,
  onStatus,
}: {
  item: BulkUploadItem;
  status: Status;
  justFinished: boolean;
  onStatus: (s: Status) => void;
}) {
  // Keep the SSE subscription alive only while we still think we're processing.
  useDocumentStream(item.id, {
    enabled: status === "processing",
    onEvent: (ev) => {
      const next = ev.status as Status;
      if (
        next === "extracted" ||
        next === "reviewed" ||
        next === "not_receipt" ||
        next === "error"
      ) {
        onStatus(next === "reviewed" ? "extracted" : next);
      }
    },
  });

  const color =
    status === "extracted"
      ? "green"
      : status === "not_receipt"
        ? "gray"
        : status === "error"
          ? "red"
          : "indigo";
  const Icon =
    status === "extracted"
      ? CheckCircle2
      : status === "not_receipt"
        ? AlertCircle
        : status === "error"
          ? X
          : Loader2;

  return (
    <Tooltip label={item.filename}>
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: `1px solid var(--mantine-color-${color}-4)`,
          background:
            status === "processing"
              ? "var(--mantine-color-default-hover)"
              : `var(--mantine-color-${color}-light)`,
          color: `var(--mantine-color-${color}-7)`,
          transform: justFinished ? "scale(1.15)" : "scale(1)",
          transition: "transform 250ms cubic-bezier(0.34, 1.56, 0.64, 1), background 250ms",
          boxShadow: justFinished
            ? `0 0 0 4px var(--mantine-color-${color}-2)`
            : "none",
        }}
      >
        <Icon
          size={20}
          className={status === "processing" ? "animate-spin" : ""}
        />
      </div>
    </Tooltip>
  );
}
