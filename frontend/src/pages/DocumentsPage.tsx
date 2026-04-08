import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  Loader2,
  Search,
  ShieldAlert,
} from "lucide-react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import "dayjs/locale/th";
import {
  type DocumentListItem,
  getDocumentCount,
  getDocuments,
} from "../api/client";
import { parseFraudFlags } from "@/lib/fraud";

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

const CATEGORY_OPTIONS = [
  { value: "", label: "ทุกหมวด" },
  { value: "เบียร์", label: "เบียร์" },
  { value: "น้ำดื่ม", label: "น้ำดื่ม" },
  { value: "โซดาและน้ำอัดลม", label: "โซดาและน้ำอัดลม" },
  { value: "น้ำแร่", label: "น้ำแร่" },
  { value: "สุรา", label: "สุรา" },
  { value: "เครื่องดื่มอื่นๆ", label: "เครื่องดื่มอื่นๆ" },
  { value: "อาหาร", label: "อาหาร" },
  { value: "อื่นๆ", label: "อื่นๆ" },
];

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [dateRange, setDateRange] = useState<[Date | null, Date | null] | undefined>(undefined);

  const dateFrom = dateRange?.[0] ? format(dateRange[0], "yyyy-MM-dd") : "";
  const dateTo = dateRange?.[1] ? format(dateRange[1], "yyyy-MM-dd") : "";

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const filters = {
        status: statusFilter || undefined,
        category: categoryFilter || undefined,
        search: searchQuery || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      };
      const [docList, countResult] = await Promise.all([
        getDocuments({ skip: page * PAGE_SIZE, limit: PAGE_SIZE, ...filters }),
        getDocumentCount(filters),
      ]);
      setDocs(docList);
      setTotalCount(countResult.count);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, categoryFilter, searchQuery, dateFrom, dateTo]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  const handleSearch = () => {
    setPage(0);
    setSearchQuery(searchInput);
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
                onClick={() => { setSearchInput(""); setSearchQuery(""); setPage(0); }}
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
          onChange={(v) => { setStatusFilter(v || ""); setPage(0); }}
          clearable
          w={160}
        />
        <Select
          placeholder="ทุกหมวด"
          data={CATEGORY_OPTIONS}
          value={categoryFilter || null}
          onChange={(v) => { setCategoryFilter(v || ""); setPage(0); }}
          clearable
          w={180}
        />
        <DatePickerInput
          type="range"
          placeholder="เลือกช่วงวันที่"
          value={dateRange as [Date | null, Date | null]}
          onChange={(v) => { setDateRange(v as [Date | null, Date | null]); setPage(0); }}
          locale="th"
          clearable
          w={260}
        />
      </Group>

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
                  <Table.Th>เอกสาร</Table.Th>
                  <Table.Th>ร้านค้า</Table.Th>
                  <Table.Th>หมวดหมู่</Table.Th>
                  <Table.Th>สถานะ</Table.Th>
                  <Table.Th ta="center">Fraud</Table.Th>
                  <Table.Th ta="right">ยอดรวม</Table.Th>
                  <Table.Th ta="right">Confidence</Table.Th>
                  <Table.Th ta="right">รายการ</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {docs.map((doc) => {
                  const meta = STATUS_BADGE[doc.status] ?? STATUS_BADGE.pending;
                  const Icon = meta.icon;
                  const flags = parseFraudFlags(doc.fraud_flags);
                  const hasSevere = flags.some((f) => f.severity === "high");

                  return (
                    <Table.Tr key={doc.id}>
                      <Table.Td>
                        <Text
                          component={Link}
                          to={`/documents/${doc.id}`}
                          fw={500}
                          c="indigo"
                          className="hover:underline"
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
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                >
                  <ChevronLeft size={16} />
                </ActionIcon>
                <Text size="sm" px="xs">
                  หน้า {page + 1} / {totalPages}
                </Text>
                <ActionIcon
                  variant="outline"
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                >
                  <ChevronRight size={16} />
                </ActionIcon>
              </Group>
            </Group>
          )}
        </>
      )}
    </div>
  );
}
