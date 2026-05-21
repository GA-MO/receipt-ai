import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { format, parse } from "date-fns";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Clock,
  FileText,
  Loader2,
  Search,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import "dayjs/locale/th";
import {
  useBulkApprove,
  useBulkDelete,
  useDocumentCount,
  useDocuments,
} from "../api/queries";
import { getDocumentImageUrl } from "../api/client";
import { parseFraudFlags } from "@/lib/fraud";
import { CATEGORY_FILTER_OPTIONS as CATEGORY_OPTIONS } from "@/lib/categories";
import { useToast } from "@/components/Toast";

const STATUS_OPTIONS = [
  { value: "", label: "ทั้งหมด" },
  { value: "processing", label: "กำลังประมวลผล" },
  { value: "extracted", label: "รอตรวจสอบ" },
  { value: "reviewed", label: "ตรวจสอบแล้ว" },
  { value: "error", label: "ผิดพลาด" },
];

const STATUS_BADGE: Record<string, { color: string; label: string; icon: typeof Clock }> = {
  pending: { color: "gray", label: "รอดำเนินการ", icon: Clock },
  processing: { color: "blue", label: "กำลังประมวลผล", icon: Loader2 },
  extracted: { color: "yellow", label: "รอตรวจสอบ", icon: AlertCircle },
  reviewed: { color: "green", label: "ตรวจสอบแล้ว", icon: CheckCircle2 },
  error: { color: "red", label: "ผิดพลาด", icon: AlertCircle },
};

const PAGE_SIZE = 20;

type SortKey =
  | "uploaded_at"
  | "document_date"
  | "merchant_name"
  | "grand_total"
  | "confidence"
  | "status"
  | "category";
type SortDir = "asc" | "desc";

function SortHeader({
  label,
  column,
  sortBy,
  sortDir,
  onChange,
  align = "left",
  width,
}: {
  label: string;
  column: SortKey;
  sortBy: SortKey;
  sortDir: SortDir;
  onChange: (col: SortKey) => void;
  align?: "left" | "right" | "center";
  width?: number;
}) {
  const active = sortBy === column;
  const Icon = active ? (sortDir === "asc" ? ArrowUp : ArrowDown) : ChevronsUpDown;
  return (
    <Table.Th ta={align} w={width}>
      <UnstyledButton
        onClick={() => onChange(column)}
        style={{ display: "inline-flex", alignItems: "center", gap: 4, fontWeight: 600 }}
      >
        <Text size="sm" fw={600}>{label}</Text>
        <Icon size={12} className={active ? "" : "opacity-40"} />
      </UnstyledButton>
    </Table.Th>
  );
}

export default function DocumentsPage() {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  // Filters + pagination + sort all live in URL query params so back-nav restores them
  const page = Number(searchParams.get("page") ?? "0") || 0;
  const statusFilter = searchParams.get("status") ?? "";
  const categoryFilter = searchParams.get("category") ?? "";
  const searchQuery = searchParams.get("q") ?? "";
  const sortBy = (searchParams.get("sort_by") ?? "uploaded_at") as SortKey;
  const sortDir = (searchParams.get("sort_dir") ?? "desc") as SortDir;
  const dateFrom = searchParams.get("from") ?? "";
  const dateTo = searchParams.get("to") ?? "";

  const updateParams = (updates: Record<string, string | null>) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value === null || value === "") next.delete(key);
          else next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  };

  const [searchInput, setSearchInput] = useState(searchQuery);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Keep searchInput in sync when URL query changes externally (e.g., back-nav)
  useEffect(() => {
    setSearchInput(searchQuery);
  }, [searchQuery]);

  const dateRange: [Date | null, Date | null] = [
    dateFrom ? parse(dateFrom, "yyyy-MM-dd", new Date()) : null,
    dateTo ? parse(dateTo, "yyyy-MM-dd", new Date()) : null,
  ];

  const setPage = (p: number) =>
    updateParams({ page: p === 0 ? null : String(p) });

  const bulkApprove = useBulkApprove();
  const bulkDelete = useBulkDelete();

  const filters = {
    status: statusFilter || undefined,
    category: categoryFilter || undefined,
    search: searchQuery || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };

  const { data: docs = [], isPending: docsLoading } = useDocuments({
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort_by: sortBy,
    sort_dir: sortDir,
    ...filters,
  });
  const { data: countResult } = useDocumentCount(filters);
  const totalCount = countResult?.count ?? 0;
  const loading = docsLoading;

  const handleSearch = () => {
    updateParams({ q: searchInput || null, page: null });
  };

  const handleSort = (col: SortKey) => {
    const nextDir =
      sortBy === col ? (sortDir === "asc" ? "desc" : "asc") : "desc";
    updateParams({ sort_by: col, sort_dir: nextDir, page: null });
  };

  const toggleOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const pageIds = useMemo(() => docs.map((d) => d.id), [docs]);
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
  const someOnPageSelected = pageIds.some((id) => selectedIds.has(id));

  const toggleAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const selectedCount = selectedIds.size;
  const selectedList = Array.from(selectedIds);

  const handleBulkApprove = async () => {
    try {
      const res = await bulkApprove.mutateAsync(selectedList);
      toast("success", `อนุมัติ ${res.succeeded} เอกสาร${res.failed ? ` (ผิดพลาด ${res.failed})` : ""}`);
      setSelectedIds(new Set());
    } catch {
      toast("error", "ไม่สามารถอนุมัติได้");
    }
  };

  const handleBulkDelete = async () => {
    try {
      const res = await bulkDelete.mutateAsync(selectedList);
      toast("success", `ลบ ${res.succeeded} เอกสาร${res.failed ? ` (ผิดพลาด ${res.failed})` : ""}`);
      setSelectedIds(new Set());
      setConfirmDelete(false);
    } catch {
      toast("error", "ไม่สามารถลบได้");
      setConfirmDelete(false);
    }
  };

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <div>
      <Group justify="space-between" mb="lg">
        <div>
          <Title order={2}>เอกสารทั้งหมด</Title>
          <Text c="dimmed" size="sm">{totalCount} เอกสาร</Text>
        </div>
        <Button component={Link} to="/">
          + อัปโหลดใหม่
        </Button>
      </Group>

      {/* Search */}
      <Group mb="sm" gap="sm">
        <TextInput
          className="flex-1"
          placeholder="ค้นหาร้านค้า, ชื่อไฟล์, เลขที่เอกสาร..."
          leftSection={<Search size={16} />}
          value={searchInput}
          onChange={(e) => setSearchInput(e.currentTarget.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          rightSection={
            searchInput ? (
              <ActionIcon
                variant="subtle"
                size="sm"
                onClick={() => {
                  setSearchInput("");
                  updateParams({ q: null, page: null });
                }}
              >
                ✕
              </ActionIcon>
            ) : undefined
          }
        />
        <Button variant="light" onClick={handleSearch}>ค้นหา</Button>
      </Group>

      {/* Filters */}
      <Group mb="lg" gap="sm" wrap="wrap">
        <Select
          placeholder="ทั้งหมด"
          data={STATUS_OPTIONS}
          value={statusFilter || null}
          onChange={(v) => updateParams({ status: v || null, page: null })}
          clearable
          w={160}
        />
        <Select
          placeholder="ทุกหมวด"
          data={CATEGORY_OPTIONS}
          value={categoryFilter || null}
          onChange={(v) => updateParams({ category: v || null, page: null })}
          clearable
          w={180}
        />
        <DatePickerInput
          type="range"
          placeholder="เลือกช่วงวันที่"
          value={dateRange}
          onChange={(v) => {
            const [from, to] = (v as [Date | null, Date | null]) ?? [null, null];
            updateParams({
              from: from ? format(from, "yyyy-MM-dd") : null,
              to: to ? format(to, "yyyy-MM-dd") : null,
              page: null,
            });
          }}
          locale="th"
          clearable
          w={260}
        />
      </Group>

      {/* Bulk action toolbar */}
      {selectedCount > 0 && (
        <Paper
          withBorder
          p="sm"
          mb="sm"
          style={{ background: "var(--mantine-color-indigo-0)", borderColor: "var(--mantine-color-indigo-4)" }}
        >
          <Group justify="space-between">
            <Text size="sm" fw={600}>
              เลือกแล้ว {selectedCount} เอกสาร
            </Text>
            <Group gap="xs">
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setSelectedIds(new Set())}
              >
                ยกเลิก
              </Button>
              <Button
                size="xs"
                color="green"
                leftSection={<CheckCircle2 size={14} />}
                onClick={handleBulkApprove}
                loading={bulkApprove.isPending}
              >
                อนุมัติทั้งหมด
              </Button>
              <Button
                size="xs"
                color="red"
                variant="light"
                leftSection={<Trash2 size={14} />}
                onClick={() => setConfirmDelete(true)}
              >
                ลบทั้งหมด
              </Button>
            </Group>
          </Group>
        </Paper>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader size="lg" />
        </div>
      ) : docs.length === 0 ? (
        <Stack align="center" py="xl" gap="md">
          <FileText className="w-16 h-16 text-gray-300" />
          <Text c="dimmed" size="lg">
            {searchQuery || statusFilter ? "ไม่พบเอกสารที่ตรงกับเงื่อนไข" : "ยังไม่มีเอกสาร"}
          </Text>
          {!searchQuery && !statusFilter && (
            <Button variant="subtle" component={Link} to="/">อัปโหลดเอกสารแรก</Button>
          )}
        </Stack>
      ) : (
        <>
          <Paper withBorder className="overflow-x-auto">
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={40}>
                    <Checkbox
                      checked={allOnPageSelected}
                      indeterminate={!allOnPageSelected && someOnPageSelected}
                      onChange={toggleAllOnPage}
                      aria-label="เลือกทั้งหมดในหน้านี้"
                    />
                  </Table.Th>
                  <Table.Th w={72}></Table.Th>
                  <SortHeader label="เอกสาร" column="uploaded_at" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} />
                  <SortHeader label="ร้านค้า" column="merchant_name" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} />
                  <SortHeader label="หมวดหมู่" column="category" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} />
                  <SortHeader label="สถานะ" column="status" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} />
                  <Table.Th ta="center">Fraud</Table.Th>
                  <SortHeader label="ยอดรวม" column="grand_total" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} align="right" />
                  <SortHeader label="Confidence" column="confidence" sortBy={sortBy} sortDir={sortDir} onChange={handleSort} align="right" />
                  <Table.Th ta="right">รายการ</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {docs.map((doc) => {
                  const meta = STATUS_BADGE[doc.status] ?? STATUS_BADGE.pending;
                  const Icon = meta.icon;
                  const flags = parseFraudFlags(doc.fraud_flags);
                  const hasSevere = flags.some((f) => f.severity === "high");
                  const checked = selectedIds.has(doc.id);

                  return (
                    <Table.Tr
                      key={doc.id}
                      bg={checked ? "var(--mantine-color-indigo-0)" : undefined}
                    >
                      <Table.Td>
                        <Checkbox
                          checked={checked}
                          onChange={() => toggleOne(doc.id)}
                          aria-label="เลือกเอกสาร"
                        />
                      </Table.Td>
                      <Table.Td>
                        <Link to={doc.visit_id ? `/visits/${doc.visit_id}` : "/documents"} className="block">
                          {doc.file_type === "pdf" ? (
                            <div className="w-14 h-14 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
                              <FileText className="w-6 h-6 text-gray-400" />
                            </div>
                          ) : (
                            <img
                              src={getDocumentImageUrl(doc.id)}
                              alt=""
                              loading="lazy"
                              className="w-14 h-14 rounded-md border border-gray-200 dark:border-gray-700 object-cover bg-gray-50 dark:bg-gray-800 hover:opacity-80 transition-opacity"
                              onError={(e) => {
                                e.currentTarget.style.visibility = "hidden";
                              }}
                            />
                          )}
                        </Link>
                      </Table.Td>
                      <Table.Td>
                        <Text
                          component={Link}
                          to={doc.visit_id ? `/visits/${doc.visit_id}` : "/documents"}
                          fw={500}
                          c="indigo"
                          className="hover:underline"
                          lineClamp={1}
                        >
                          {doc.filename}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {new Date(doc.uploaded_at).toLocaleString("th-TH")}
                        </Text>
                      </Table.Td>
                      <Table.Td>{doc.merchant_name || "-"}</Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">{doc.category || "-"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          color={meta.color}
                          variant="light"
                          leftSection={<Icon size={12} />}
                        >
                          {meta.label}
                        </Badge>
                      </Table.Td>
                      <Table.Td ta="center">
                        {flags.length === 0 ? (
                          <Text c="dimmed">-</Text>
                        ) : (
                          <Badge
                            color={hasSevere ? "red" : "yellow"}
                            variant="light"
                            leftSection={<ShieldAlert size={12} />}
                            title={flags.map((f) => f.label).join(", ")}
                          >
                            {flags.length}
                          </Badge>
                        )}
                      </Table.Td>
                      <Table.Td ta="right">
                        <Text ff="monospace" size="sm">
                          {doc.grand_total != null
                            ? `฿${doc.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}`
                            : "-"}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        {doc.confidence != null ? (
                          <Text
                            ff="monospace"
                            size="sm"
                            c={
                              doc.confidence >= 0.9
                                ? "green"
                                : doc.confidence >= 0.7
                                  ? "yellow"
                                  : "red"
                            }
                          >
                            {(doc.confidence * 100).toFixed(0)}%
                          </Text>
                        ) : (
                          "-"
                        )}
                      </Table.Td>
                      <Table.Td ta="right">{doc.item_count}</Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Paper>

          {/* Pagination */}
          {totalPages > 1 && (
            <Group justify="space-between" mt="md">
              <Text size="sm" c="dimmed">
                แสดง {page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, totalCount)} จาก {totalCount} รายการ
              </Text>
              <Group gap="xs">
                <ActionIcon
                  variant="outline"
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                >
                  <ChevronLeft size={16} />
                </ActionIcon>
                <Text size="sm" px="xs">
                  หน้า {page + 1} / {totalPages}
                </Text>
                <ActionIcon
                  variant="outline"
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  disabled={page >= totalPages - 1}
                >
                  <ChevronRight size={16} />
                </ActionIcon>
              </Group>
            </Group>
          )}
        </>
      )}

      <Modal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="ย้ายไปถังขยะ"
        centered
      >
        <Text size="sm" c="dimmed">
          ย้าย {selectedCount} เอกสารไปที่ถังขยะ — สามารถกู้คืนได้ภายหลัง
        </Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="outline" onClick={() => setConfirmDelete(false)}>ยกเลิก</Button>
          <Button
            color="red"
            leftSection={<Trash2 size={14} />}
            onClick={handleBulkDelete}
            loading={bulkDelete.isPending}
          >
            ย้ายไปถังขยะ
          </Button>
        </Group>
      </Modal>
    </div>
  );
}
