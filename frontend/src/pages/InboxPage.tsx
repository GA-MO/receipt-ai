import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { format } from "date-fns";
import {
  ActionIcon,
  Autocomplete,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Menu,
  Modal,
  Paper,
  Progress,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronRight,
  FileText,
  HelpCircle,
  Inbox as InboxIcon,
  MoreVertical,
  PackageOpen,
  Plus,
  RefreshCw,
  Sparkles,
  Store as StoreIcon,
  Trash2,
  Upload as UploadIcon,
  X,
} from "lucide-react";
import {
  type DashboardVisit,
  type DocumentListItem,
  getDocumentImageUrl,
} from "../api/client";
import {
  useAssignStoreToDoc,
  useCreateStoreFromDoc,
  useDashboard,
  useDiscardInboxDoc,
  useNameOrphan,
  usePurgeNonReceipts,
  useStores,
  useUploadInbox,
} from "../api/queries";
import type { StoreListItem } from "../api/client";
import { ImageCanvas } from "@/components/ImageCanvas";
import { useToast } from "@/components/Toast";

const ALL_MONTHS = "__all__";

function currentYearMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function formatMonthLabel(yyyymm: string): string {
  if (yyyymm === ALL_MONTHS) return "ทุกเดือน";
  if (!/^\d{4}-\d{2}$/.test(yyyymm)) return yyyymm;
  const [y, m] = yyyymm.split("-").map(Number);
  const months = [
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
  return `${months[m - 1]} ${y + 543}`;
}

export default function InboxPage() {
  const { toast } = useToast();
  // Default to "All months" so freshly-uploaded receipts with old dates don't
  // silently disappear behind a current-month filter.
  const [month, setMonth] = useState<string>(ALL_MONTHS);
  const dashboardMonth = month === ALL_MONTHS ? null : month;
  const dashboard = useDashboard(dashboardMonth);
  const stores = useStores();
  const upload = useUploadInbox();
  const purgeNonReceipts = usePurgeNonReceipts();

  // Auto-cleanup of non-receipts > 7 days on first load. Quiet best-effort.
  useEffect(() => {
    purgeNonReceipts.mutate(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onDrop = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      try {
        const res = await upload.mutateAsync(files);
        const skipped = res.duplicates.length + res.failures.length;
        if (res.document_ids.length) {
          toast(
            "success",
            `อัปโหลด ${res.document_ids.length} ไฟล์${skipped ? ` (ข้าม ${skipped})` : ""}`,
          );
        } else if (skipped) {
          toast("info", `ทุกไฟล์ถูกข้าม (${skipped} ซ้ำ/ผิดพลาด)`);
        }
      } catch (e: unknown) {
        toast("error", e instanceof Error ? e.message : "อัปโหลดล้มเหลว");
      }
    },
    [upload, toast],
  );

  const dropzone = useDropzone({
    onDrop,
    accept: {
      "image/*": [".png", ".jpg", ".jpeg", ".heic", ".webp"],
      "application/pdf": [".pdf"],
    },
    multiple: true,
    noClick: false,
  });

  const data = dashboard.data;
  const availableMonths = useMemo(() => {
    const months = new Set(data?.available_months ?? []);
    if (month !== ALL_MONTHS) months.add(month);
    months.add(currentYearMonth());
    const sorted = Array.from(months).sort().reverse();
    return [ALL_MONTHS, ...sorted];
  }, [data?.available_months, month]);

  return (
    <div>
      {/* Header */}
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Group gap="xs" align="center">
            <ThemeIcon
              size="lg"
              radius="md"
              variant="gradient"
              gradient={{ from: "indigo", to: "violet" }}
            >
              <InboxIcon size={20} />
            </ThemeIcon>
            <Title order={2}>อัปโหลด & จัดกลุ่ม</Title>
          </Group>
          <Text c="dimmed" size="sm" mt={4}>
            โยนใบเสร็จมาทีเดียว AI จะแยกร้านให้อัตโนมัติ คุณรีวิวสินค้าและจำนวนทีหลัง
          </Text>
        </div>
        <MonthSwitcher month={month} months={availableMonths} onChange={setMonth} />
      </Group>

      {/* Drop zone */}
      <Paper
        {...dropzone.getRootProps()}
        withBorder
        p="xl"
        mb="md"
        radius="md"
        style={{
          borderStyle: "dashed",
          borderWidth: 2,
          borderColor: dropzone.isDragActive
            ? "var(--mantine-color-indigo-5)"
            : "var(--mantine-color-gray-4)",
          background: dropzone.isDragActive
            ? "var(--mantine-color-indigo-0)"
            : undefined,
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
      >
        <input {...dropzone.getInputProps()} />
        <Group justify="center" gap="md">
          <ThemeIcon size={64} radius="xl" variant="light" color="indigo">
            <UploadIcon size={32} />
          </ThemeIcon>
          <div>
            <Text fw={600} size="lg">
              {dropzone.isDragActive ? "ปล่อยไฟล์เลย!" : "ลากใบเสร็จมาวางที่นี่"}
            </Text>
            <Text size="sm" c="dimmed">
              JPG, PNG, HEIC, PDF — อัปโหลดได้หลายไฟล์ ไม่จำกัด
            </Text>
          </div>
          {upload.isPending && <Loader size="sm" />}
        </Group>
      </Paper>

      {dashboard.isLoading ? (
        <Group justify="center" py={64}>
          <Loader />
        </Group>
      ) : !data ? null : (
        <Stack gap="md">
          {/* Processing section */}
          {data.processing.length > 0 && (
            <ProcessingSection docs={data.processing} />
          )}

          {/* Unknown stores — AI read merchant but no Store master row matches. */}
          {data.unknown_stores.length > 0 && (
            <UnknownStoresSection
              docs={data.unknown_stores}
              stores={stores.data ?? []}
            />
          )}

          {/* Orphans — AI couldn't read merchant. */}
          {data.orphans.length > 0 && (
            <OrphanSection
              docs={data.orphans}
              stores={stores.data ?? []}
            />
          )}

          {/* Errors */}
          {data.errors.length > 0 && <ErrorSection docs={data.errors} />}

          {/* Non-receipts */}
          {data.non_receipts.length > 0 && (
            <NonReceiptSection docs={data.non_receipts} />
          )}

          {/* Visits */}
          <VisitsSection
            visits={data.visits}
            month={month}
            counts={data.counts}
          />
        </Stack>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

function MonthSwitcher({
  month,
  months,
  onChange,
}: {
  month: string;
  months: string[];
  onChange: (m: string) => void;
}) {
  return (
    <Select
      value={month}
      data={months.map((m) => ({ value: m, label: formatMonthLabel(m) }))}
      onChange={(v) => v && onChange(v)}
      leftSection={<Calendar size={14} />}
      style={{ width: 170 }}
      allowDeselect={false}
    />
  );
}

function SectionCard({
  color,
  icon: Icon,
  title,
  count,
  subtitle,
  children,
  rightSlot,
}: {
  color: string;
  icon: React.ComponentType<{ size?: number }>;
  title: string;
  count: number;
  subtitle?: string;
  children: React.ReactNode;
  rightSlot?: React.ReactNode;
}) {
  return (
    <Card
      withBorder
      radius="md"
      p={0}
      style={{ borderLeft: `4px solid var(--mantine-color-${color}-5)` }}
    >
      <Group justify="space-between" p="md" pb="sm">
        <Group gap="xs">
          <ThemeIcon variant="light" color={color} size="md" radius="md">
            <Icon size={16} />
          </ThemeIcon>
          <div>
            <Text fw={600}>{title}</Text>
            {subtitle && (
              <Text size="xs" c="dimmed">
                {subtitle}
              </Text>
            )}
          </div>
          <Badge variant="light" color={color} size="lg">
            {count}
          </Badge>
        </Group>
        {rightSlot}
      </Group>
      <div className="px-4 pb-4">{children}</div>
    </Card>
  );
}

function ProcessingSection({ docs }: { docs: DocumentListItem[] }) {
  return (
    <Card
      withBorder
      radius="md"
      p="md"
      style={{ borderLeft: "4px solid var(--mantine-color-blue-5)" }}
    >
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Loader size="sm" />
          <Text fw={600}>กำลังประมวลผล</Text>
          <Badge variant="light" color="blue">
            {docs.length}
          </Badge>
        </Group>
        <Text size="xs" c="dimmed">
          AI กำลังอ่านใบเสร็จและจัดเข้าร้าน...
        </Text>
      </Group>
      <Progress value={50} animated color="blue" size="sm" />
      <Group gap="xs" mt="sm">
        {docs.slice(0, 12).map((d) => (
          <Tooltip key={d.id} label={d.filename}>
            <div className="w-10 h-10 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
              <Loader size="xs" />
            </div>
          </Tooltip>
        ))}
        {docs.length > 12 && (
          <Text size="xs" c="dimmed">
            +{docs.length - 12}
          </Text>
        )}
      </Group>
    </Card>
  );
}

function OrphanSection({
  docs,
  stores,
}: {
  docs: DocumentListItem[];
  stores: { id: string; name: string }[];
}) {
  const { toast } = useToast();
  const nameMut = useNameOrphan();
  const discardMut = useDiscardInboxDoc();
  const [naming, setNaming] = useState<DocumentListItem | null>(null);
  const [text, setText] = useState("");
  const storeNames = stores.map((s) => s.name);

  const submitName = async () => {
    if (!naming) return;
    const trimmed = text.trim();
    if (!trimmed) {
      toast("error", "กรุณาใส่ชื่อร้าน");
      return;
    }
    try {
      const updated = await nameMut.mutateAsync({
        docId: naming.id,
        merchantName: trimmed,
      });
      if (updated.visit_id) {
        toast("success", "ผูกใบเสร็จกับร้านเรียบร้อย");
      } else {
        toast(
          "info",
          "บันทึกชื่อร้านแล้ว — ร้านยังไม่อยู่ในระบบ ใบเสร็จย้ายไปรอเพิ่มร้านใหม่",
        );
      }
      setNaming(null);
      setText("");
    } catch (e: unknown) {
      toast("error", e instanceof Error ? e.message : "ตั้งชื่อไม่สำเร็จ");
    }
  };

  return (
    <>
      <SectionCard
        color="orange"
        icon={HelpCircle}
        title="AI อ่านชื่อร้านไม่ได้"
        count={docs.length}
        subtitle="ตั้งชื่อร้านเองเพื่อจัดเข้า visit"
      >
        <Group gap="sm" wrap="wrap">
          {docs.map((d) => (
            <OrphanThumb
              key={d.id}
              doc={d}
              onName={() => {
                setNaming(d);
                setText("");
              }}
              onDiscard={async () => {
                try {
                  await discardMut.mutateAsync(d.id);
                  toast("success", "ลบออกจากกล่อง");
                } catch (e: unknown) {
                  toast(
                    "error",
                    e instanceof Error ? e.message : "ลบไม่สำเร็จ",
                  );
                }
              }}
            />
          ))}
        </Group>
      </SectionCard>

      <Modal
        opened={!!naming}
        onClose={() => setNaming(null)}
        title="ตั้งชื่อร้านให้ใบเสร็จนี้"
        fullScreen
        withCloseButton
        styles={{ body: { height: "calc(100vh - 60px)", padding: 0 } }}
      >
        {naming && (
          <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] h-full min-h-0">
            {/* Left — image */}
            <div className="overflow-hidden border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 min-h-0">
              {naming.file_type === "pdf" ? (
                <iframe
                  src={getDocumentImageUrl(naming.id)}
                  className="w-full h-full"
                  title={naming.filename}
                />
              ) : (
                <ImageCanvas
                  src={getDocumentImageUrl(naming.id)}
                  alt={naming.filename}
                  downloadFilename={naming.filename}
                />
              )}
            </div>

            {/* Right — form */}
            <div className="overflow-auto">
              <Stack p="md">
                <Autocomplete
                  label="ชื่อร้าน"
                  placeholder="เริ่มพิมพ์เพื่อค้นหาร้านที่มี..."
                  data={storeNames}
                  value={text}
                  onChange={setText}
                  data-autofocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitName();
                  }}
                />
                <Text size="xs" c="dimmed">
                  ถ้าชื่อตรงกับร้านใน Store master ระบบจะผูกใบเสร็จเข้า visit
                  ของเดือนนี้ให้ทันที ถ้ายังไม่มีร้านในระบบ ใบเสร็จจะย้ายไปอยู่ที่
                  "ร้านยังไม่อยู่ในระบบ" ให้คุณเลือกหรือเพิ่มร้านใหม่
                </Text>
                <Group justify="flex-end">
                  <Button variant="default" onClick={() => setNaming(null)}>
                    ยกเลิก
                  </Button>
                  <Button onClick={submitName} loading={nameMut.isPending}>
                    ผูกกับร้าน
                  </Button>
                </Group>
              </Stack>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

function UnknownStoresSection({
  docs,
  stores,
}: {
  docs: DocumentListItem[];
  stores: StoreListItem[];
}) {
  const { toast } = useToast();
  const assignMut = useAssignStoreToDoc();
  const createMut = useCreateStoreFromDoc();
  const discardMut = useDiscardInboxDoc();
  const [resolving, setResolving] = useState<DocumentListItem | null>(null);

  const assign = async (storeId: string) => {
    if (!resolving) return;
    try {
      await assignMut.mutateAsync({ docId: resolving.id, storeId });
      toast("success", "ผูกใบเสร็จกับร้านเรียบร้อย");
      setResolving(null);
    } catch (e: unknown) {
      toast("error", e instanceof Error ? e.message : "ผูกร้านไม่สำเร็จ");
    }
  };

  const create = async (payload: { name: string; code?: string }) => {
    if (!resolving) return;
    try {
      await createMut.mutateAsync({ docId: resolving.id, ...payload });
      toast("success", `เพิ่มร้าน "${payload.name}" ลงระบบและผูกใบเสร็จเรียบร้อย`);
      setResolving(null);
    } catch (e: unknown) {
      toast("error", e instanceof Error ? e.message : "เพิ่มร้านไม่สำเร็จ");
    }
  };

  return (
    <>
      <SectionCard
        color="yellow"
        icon={StoreIcon}
        title="ร้านยังไม่อยู่ในระบบ"
        count={docs.length}
        subtitle="AI อ่านชื่อร้านได้ แต่ยังไม่มีใน Store master — เลือกร้านที่มี หรือเพิ่มร้านใหม่"
      >
        <Group gap="sm" wrap="wrap">
          {docs.map((d) => (
            <UnknownStoreThumb
              key={d.id}
              doc={d}
              onResolve={() => setResolving(d)}
              onDiscard={async () => {
                try {
                  await discardMut.mutateAsync(d.id);
                  toast("success", "ลบออกจากกล่อง");
                } catch (e: unknown) {
                  toast(
                    "error",
                    e instanceof Error ? e.message : "ลบไม่สำเร็จ",
                  );
                }
              }}
            />
          ))}
        </Group>
      </SectionCard>

      <ResolveStoreModal
        doc={resolving}
        stores={stores}
        onClose={() => setResolving(null)}
        onAssign={assign}
        onCreate={create}
        assignPending={assignMut.isPending}
        createPending={createMut.isPending}
      />
    </>
  );
}

function ResolveStoreModal({
  doc,
  stores,
  onClose,
  onAssign,
  onCreate,
  assignPending,
  createPending,
}: {
  doc: DocumentListItem | null;
  stores: StoreListItem[];
  onClose: () => void;
  onAssign: (storeId: string) => void | Promise<void>;
  onCreate: (payload: { name: string; code?: string }) => void | Promise<void>;
  assignPending: boolean;
  createPending: boolean;
}) {
  const [tab, setTab] = useState<"existing" | "new">("existing");
  const [storeSearch, setStoreSearch] = useState("");
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState("");

  useEffect(() => {
    if (doc) {
      setTab("existing");
      setStoreSearch("");
      setSelectedStoreId(null);
      setNewName(doc.merchant_name || doc.merchant_normalized || "");
      setNewCode("");
    }
  }, [doc?.id]);

  const filteredStores = useMemo(() => {
    const q = storeSearch.trim().toLowerCase();
    if (!q) return stores.slice(0, 30);
    return stores
      .filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.normalized_name || "").toLowerCase().includes(q) ||
          (s.code || "").toLowerCase().includes(q),
      )
      .slice(0, 30);
  }, [storeSearch, stores]);

  if (!doc) return null;

  return (
    <Modal
      opened={!!doc}
      onClose={onClose}
      title="จัดร้านให้ใบเสร็จนี้"
      fullScreen
      withCloseButton
      styles={{ body: { height: "calc(100vh - 60px)", padding: 0 } }}
    >
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] h-full min-h-0">
        {/* Left — image */}
        <div className="overflow-hidden border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 min-h-0">
          {doc.file_type === "pdf" ? (
            <iframe
              src={getDocumentImageUrl(doc.id)}
              className="w-full h-full"
              title={doc.filename}
            />
          ) : (
            <ImageCanvas
              src={getDocumentImageUrl(doc.id)}
              alt={doc.filename}
              downloadFilename={doc.filename}
            />
          )}
        </div>

        {/* Right — form */}
        <div className="overflow-auto p-md">
          <Stack p="md">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <div className="min-w-0">
                <Text size="xs" c="dimmed">
                  AI อ่านชื่อร้านได้
                </Text>
                <Text fw={600} size="lg" truncate>
                  {doc.merchant_name || doc.merchant_normalized || "(ไม่ระบุ)"}
                </Text>
              </div>
              {doc.document_date && (
                <Text size="xs" c="dimmed" ff="monospace" mt={4} className="shrink-0">
                  วันที่ {doc.document_date}
                </Text>
              )}
            </Group>

            <Tabs value={tab} onChange={(v) => v && setTab(v as "existing" | "new")}>
              <Tabs.List>
            <Tabs.Tab value="existing" leftSection={<StoreIcon size={14} />}>
              เลือกจากร้านที่มี
            </Tabs.Tab>
            <Tabs.Tab value="new" leftSection={<Plus size={14} />}>
              เพิ่มร้านใหม่
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="existing" pt="md">
            <Stack gap="xs">
              <TextInput
                placeholder="ค้นหาชื่อร้าน / รหัสร้าน..."
                value={storeSearch}
                onChange={(e) => setStoreSearch(e.currentTarget.value)}
                autoFocus
              />
              <Paper
                withBorder
                radius="sm"
                style={{ maxHeight: 240, overflowY: "auto" }}
              >
                {filteredStores.length === 0 ? (
                  <Text size="sm" c="dimmed" ta="center" py="md">
                    ไม่พบร้านที่ตรง — ลองเพิ่มร้านใหม่
                  </Text>
                ) : (
                  filteredStores.map((s) => (
                    <div
                      key={s.id}
                      onClick={() => setSelectedStoreId(s.id)}
                      className={`px-3 py-2 cursor-pointer border-b border-gray-100 dark:border-gray-800 last:border-0 transition-colors ${
                        selectedStoreId === s.id
                          ? "bg-indigo-50 dark:bg-indigo-900/30"
                          : "hover:bg-gray-50 dark:hover:bg-gray-800/40"
                      }`}
                    >
                      <Group justify="space-between" wrap="nowrap">
                        <div className="min-w-0">
                          <Text size="sm" fw={500} truncate>
                            {s.name}
                          </Text>
                          {s.code && (
                            <Text size="xs" c="dimmed">
                              {s.code}
                            </Text>
                          )}
                        </div>
                        <Badge size="xs" variant="light" color="gray">
                          {s.visit_count} visits
                        </Badge>
                      </Group>
                    </div>
                  ))
                )}
              </Paper>
              <Group justify="flex-end">
                <Button variant="default" onClick={onClose}>
                  ยกเลิก
                </Button>
                <Button
                  disabled={!selectedStoreId}
                  loading={assignPending}
                  onClick={() => selectedStoreId && onAssign(selectedStoreId)}
                >
                  ผูกกับร้านนี้
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="new" pt="md">
            <Stack gap="sm">
              <TextInput
                label="ชื่อร้าน"
                placeholder="เช่น ร้านสมศักดิ์การค้า"
                value={newName}
                onChange={(e) => setNewName(e.currentTarget.value)}
                required
              />
              <TextInput
                label="รหัสร้าน (ไม่บังคับ)"
                placeholder="เช่น R001"
                value={newCode}
                onChange={(e) => setNewCode(e.currentTarget.value)}
              />
              <Text size="xs" c="dimmed">
                จะสร้างร้านใหม่ใน Store master และผูกใบเสร็จนี้เข้า visit
                ของเดือนรายงานทันที
              </Text>
              <Group justify="flex-end">
                <Button variant="default" onClick={onClose}>
                  ยกเลิก
                </Button>
                <Button
                  disabled={!newName.trim()}
                  loading={createPending}
                  onClick={() =>
                    onCreate({
                      name: newName.trim(),
                      code: newCode.trim() || undefined,
                    })
                  }
                >
                  เพิ่มร้าน & ผูกใบเสร็จ
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>
            </Tabs>
          </Stack>
        </div>
      </div>
    </Modal>
  );
}

function UnknownStoreThumb({
  doc,
  onResolve,
  onDiscard,
}: {
  doc: DocumentListItem;
  onResolve: () => void;
  onDiscard: () => void;
}) {
  const label = doc.merchant_name || doc.merchant_normalized || "(ไม่ระบุ)";
  return (
    <div className="relative w-28 h-28 rounded-md overflow-hidden border-2 border-yellow-400 bg-gray-50 dark:bg-gray-800 group">
      {doc.file_type === "image" ? (
        <img
          src={getDocumentImageUrl(doc.id)}
          alt={doc.filename}
          loading="lazy"
          className="w-full h-full object-cover cursor-pointer"
          onClick={onResolve}
          onError={(e) => {
            e.currentTarget.style.visibility = "hidden";
          }}
        />
      ) : (
        <div
          className="w-full h-full flex items-center justify-center text-gray-400 text-xs font-medium cursor-pointer"
          onClick={onResolve}
        >
          PDF
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 bg-black/70 text-white text-[10px] px-1 py-0.5 truncate">
        {label}
      </div>
      <div className="absolute top-1 right-1">
        <Menu position="bottom-end" withinPortal shadow="md">
          <Menu.Target>
            <ActionIcon
              size="sm"
              variant="white"
              radius="xl"
              style={{
                boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
                background: "white",
              }}
              aria-label="ตัวเลือก"
            >
              <MoreVertical size={14} className="text-gray-700" />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<StoreIcon size={14} />} onClick={onResolve}>
              จัดร้าน
            </Menu.Item>
            <Menu.Item
              leftSection={<X size={14} />}
              color="red"
              onClick={onDiscard}
            >
              ลบออกจากกล่อง
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>
    </div>
  );
}

function ErrorSection({ docs }: { docs: DocumentListItem[] }) {
  const { toast } = useToast();
  const discardMut = useDiscardInboxDoc();
  return (
    <SectionCard
      color="red"
      icon={AlertTriangle}
      title="ประมวลผลไม่ได้"
      count={docs.length}
      subtitle="ใบเสร็จที่ AI ดึงข้อมูลไม่สำเร็จ — ลองอัปโหลดใหม่หรือลบ"
    >
      <Stack gap="xs">
        {docs.map((d) => (
          <Paper key={d.id} withBorder p="xs" radius="sm">
            <Group justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
                <FileText size={16} className="text-red-500 shrink-0" />
                <Text size="sm" truncate>
                  {d.filename}
                </Text>
              </Group>
              <ActionIcon
                color="red"
                variant="subtle"
                onClick={async () => {
                  try {
                    await discardMut.mutateAsync(d.id);
                    toast("success", "ลบออกจากกล่อง");
                  } catch (e: unknown) {
                    toast(
                      "error",
                      e instanceof Error ? e.message : "ลบไม่สำเร็จ",
                    );
                  }
                }}
              >
                <Trash2 size={14} />
              </ActionIcon>
            </Group>
          </Paper>
        ))}
      </Stack>
    </SectionCard>
  );
}

function NonReceiptSection({ docs }: { docs: DocumentListItem[] }) {
  const { toast } = useToast();
  const discardMut = useDiscardInboxDoc();
  return (
    <SectionCard
      color="gray"
      icon={PackageOpen}
      title="ไฟล์ไม่ใช่ใบเสร็จ"
      count={docs.length}
      subtitle="AI ตรวจพบว่าไม่ใช่ใบเสร็จ — ระบบจะลบให้อัตโนมัติหลัง 7 วัน"
    >
      <Group gap="sm" wrap="wrap">
        {docs.map((d) => (
          <div
            key={d.id}
            className="relative w-20 h-20 rounded-md overflow-hidden border bg-gray-50 dark:bg-gray-800"
          >
            <img
              src={getDocumentImageUrl(d.id)}
              alt={d.filename}
              className="w-full h-full object-cover opacity-60"
              onError={(e) => {
                e.currentTarget.style.visibility = "hidden";
              }}
            />
            <Tooltip label="ลบทันที">
              <ActionIcon
                size="sm"
                variant="white"
                radius="xl"
                onClick={async () => {
                  try {
                    await discardMut.mutateAsync(d.id);
                    toast("success", "ลบแล้ว");
                  } catch (e: unknown) {
                    toast(
                      "error",
                      e instanceof Error ? e.message : "ลบไม่สำเร็จ",
                    );
                  }
                }}
                style={{
                  position: "absolute",
                  top: 2,
                  right: 2,
                  boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
                }}
              >
                <X size={12} className="text-red-600" />
              </ActionIcon>
            </Tooltip>
          </div>
        ))}
      </Group>
    </SectionCard>
  );
}

function VisitsSection({
  visits,
  month,
  counts,
}: {
  visits: DashboardVisit[];
  month: string;
  counts: { attention: number; visits: number };
}) {
  const isAll = month === ALL_MONTHS;
  if (!visits.length) {
    return (
      <Paper withBorder p="lg" radius="md">
        <Text c="dimmed" ta="center">
          {isAll
            ? "ยังไม่มี visit — โยนใบเสร็จเข้ามาเพื่อเริ่ม"
            : `เดือน ${formatMonthLabel(month)} ยังไม่มี visit — โยนใบเสร็จเข้ามาเพื่อเริ่ม`}
        </Text>
      </Paper>
    );
  }
  // Show "needs attention" visits first.
  const sorted = [...visits].sort((a, b) => {
    const aAttn = (a.new_doc_count > 0 ? 1 : 0) + (a.reviewed_count < a.document_count ? 0.5 : 0);
    const bAttn = (b.new_doc_count > 0 ? 1 : 0) + (b.reviewed_count < b.document_count ? 0.5 : 0);
    return bAttn - aAttn;
  });
  return (
    <Card withBorder radius="md" p={0}>
      <Group justify="space-between" p="md" pb="sm">
        <Group gap="xs">
          <ThemeIcon variant="light" color="indigo" size="md" radius="md">
            <CheckCircle2 size={16} />
          </ThemeIcon>
          <div>
            <Text fw={600}>
              {isAll ? "Visits ทั้งหมด" : `Visits ของเดือน ${formatMonthLabel(month)}`}
            </Text>
            <Text size="xs" c="dimmed">
              {counts.attention > 0
                ? `${counts.attention} visit มีใบใหม่ที่ยังไม่ได้รีวิว`
                : "AI จัดทุกใบเสร็จเข้า visit เรียบร้อย"}
            </Text>
          </div>
          <Badge variant="light" color="indigo" size="lg">
            {visits.length}
          </Badge>
        </Group>
      </Group>
      <Stack gap={0} className="border-t border-gray-100 dark:border-gray-800">
        {sorted.map((v) => (
          <VisitRow key={v.id} visit={v} showPeriod={isAll} />
        ))}
      </Stack>
    </Card>
  );
}

function VisitRow({ visit, showPeriod }: { visit: DashboardVisit; showPeriod: boolean }) {
  const allReviewed =
    visit.document_count > 0 && visit.reviewed_count === visit.document_count;
  const hasNew = visit.new_doc_count > 0;
  const dateRange =
    visit.earliest_doc_date && visit.latest_doc_date
      ? visit.earliest_doc_date === visit.latest_doc_date
        ? visit.earliest_doc_date
        : `${visit.earliest_doc_date} → ${visit.latest_doc_date}`
      : null;
  return (
    <Link
      to={`/visits/${visit.id}`}
      className="block px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors no-underline text-inherit"
      style={{
        borderLeft: hasNew
          ? "3px solid var(--mantine-color-orange-5)"
          : "3px solid transparent",
      }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
          <div className="min-w-0">
            <Group gap="xs" wrap="nowrap">
              <Text fw={500} truncate>
                {visit.store_label || visit.store_key || "(ไม่ระบุ)"}
              </Text>
              {showPeriod && visit.report_period && (
                <Badge size="sm" color="gray" variant="light">
                  {formatMonthLabel(visit.report_period)}
                </Badge>
              )}
              {hasNew && (
                <Badge size="sm" color="orange" variant="filled">
                  +{visit.new_doc_count} ใหม่
                </Badge>
              )}
            </Group>
            {dateRange && (
              <Text size="xs" c="dimmed" ff="monospace" mt={2}>
                {dateRange}
              </Text>
            )}
          </div>
        </Group>
        <Group gap="md" wrap="nowrap">
          <Badge
            variant="light"
            color={
              visit.document_count === 0
                ? "gray"
                : allReviewed
                  ? "green"
                  : "yellow"
            }
            size="md"
          >
            {visit.reviewed_count}/{visit.document_count}
          </Badge>
          <ChevronRight size={16} className="text-gray-400" />
        </Group>
      </Group>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Thumbnails
// ---------------------------------------------------------------------------

function OrphanThumb({
  doc,
  onName,
  onDiscard,
}: {
  doc: DocumentListItem;
  onName: () => void;
  onDiscard: () => void;
}) {
  return (
    <div className="relative w-24 h-24 rounded-md overflow-hidden border-2 border-orange-300 bg-gray-50 dark:bg-gray-800 group">
      {doc.file_type === "image" ? (
        <img
          src={getDocumentImageUrl(doc.id)}
          alt={doc.filename}
          loading="lazy"
          className="w-full h-full object-cover cursor-pointer"
          onClick={onName}
          onError={(e) => {
            e.currentTarget.style.visibility = "hidden";
          }}
        />
      ) : (
        <div
          className="w-full h-full flex items-center justify-center text-gray-400 text-xs font-medium cursor-pointer"
          onClick={onName}
        >
          PDF
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-[10px] px-1 py-0.5 text-center">
        แตะเพื่อตั้งชื่อ
      </div>
      <div className="absolute top-1 right-1">
        <Menu position="bottom-end" withinPortal shadow="md">
          <Menu.Target>
            <ActionIcon
              size="sm"
              variant="white"
              radius="xl"
              style={{
                boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
                background: "white",
              }}
              aria-label="ตัวเลือก"
            >
              <MoreVertical size={14} className="text-gray-700" />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item leftSection={<Sparkles size={14} />} onClick={onName}>
              ตั้งชื่อร้าน
            </Menu.Item>
            <Menu.Item
              leftSection={<X size={14} />}
              color="red"
              onClick={onDiscard}
            >
              ลบออกจากกล่อง
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>
    </div>
  );
}
