import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Download,
  FileText,
  Receipt,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import {
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { BarChart } from "@mantine/charts";
import "dayjs/locale/th";
import {
  type AiInsightResponse,
  type HeatmapDay,
  getExportUrl,
} from "../api/client";
import {
  useAiInsight,
  useCategoryBreakdown,
  useDailySales,
  useDashboardStats,
  useDocuments,
  useFraudSummary,
  useSpendingHeatmap,
  useTopMerchants,
  useVatSummary,
} from "../api/queries";

const CATEGORY_COLORS: Record<string, string> = {
  "เบียร์": "yellow",
  "น้ำดื่ม": "blue",
  "โซดาและน้ำอัดลม": "cyan",
  "น้ำแร่": "teal",
  "สุรา": "red",
  "เครื่องดื่มอื่นๆ": "violet",
  "อาหาร": "orange",
  "อื่นๆ": "gray",
};

const CATEGORY_TW_COLORS: Record<string, string> = {
  "อาหารและเครื่องดื่ม": "bg-orange-500",
  "วัตถุดิบ": "bg-emerald-500",
  "อุปกรณ์สำนักงาน": "bg-blue-500",
  "เดินทางและขนส่ง": "bg-yellow-500",
  "สาธารณูปโภค": "bg-cyan-500",
  "การตลาดและโฆษณา": "bg-pink-500",
  "บริการ": "bg-violet-500",
  "อื่นๆ": "bg-gray-400",
};

export default function DashboardPage() {
  const [exportDateRange, setExportDateRange] = useState<[Date | null, Date | null]>([null, null]);
  const [aiInsight, setAiInsight] = useState<AiInsightResponse | null>(null);

  const exportDateFrom = exportDateRange[0] ? format(exportDateRange[0], "yyyy-MM-dd") : "";
  const exportDateTo = exportDateRange[1] ? format(exportDateRange[1], "yyyy-MM-dd") : "";

  const statsQuery = useDashboardStats();
  const recentQuery = useDocuments({ limit: 5 });
  const dailyQuery = useDailySales(30);
  const topMerchantsQuery = useTopMerchants(5);
  const categoriesQuery = useCategoryBreakdown();
  const vatQuery = useVatSummary();
  const fraudQuery = useFraudSummary();
  const heatmapQuery = useSpendingHeatmap(90);
  const aiInsightMut = useAiInsight();

  const loading =
    statsQuery.isPending ||
    recentQuery.isPending ||
    dailyQuery.isPending ||
    topMerchantsQuery.isPending ||
    categoriesQuery.isPending;

  const stats = statsQuery.data ?? null;
  const recent = recentQuery.data ?? [];
  const dailySales = dailyQuery.data ?? [];
  const topMerchants = topMerchantsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const vatSummary = vatQuery.data ?? null;
  const fraudSummary = fraudQuery.data ?? null;
  const heatmapData = heatmapQuery.data ?? [];

  const handleAiInsight = async () => {
    try {
      const data = await aiInsightMut.mutateAsync();
      setAiInsight(data);
    } catch {
      setAiInsight({ headline: "ไม่สามารถสร้าง insight ได้", insights: [], risks: [], opportunities: [] });
    }
  };
  const insightLoading = aiInsightMut.isPending;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader size="lg" />
      </div>
    );
  }

  const statCards = stats
    ? [
        { label: "เอกสารทั้งหมด", value: stats.total_documents, icon: FileText, color: "indigo" as const },
        { label: "รอตรวจสอบ", value: stats.pending_review, icon: AlertCircle, color: "yellow" as const },
        { label: "ตรวจสอบแล้ว", value: stats.reviewed, icon: CheckCircle2, color: "green" as const },
        {
          label: "ยอดขายรวม",
          value: `฿${stats.total_sales.toLocaleString("th-TH", { minimumFractionDigits: 2 })}`,
          icon: TrendingUp,
          color: "grape" as const,
        },
        {
          label: "Avg Confidence",
          value: `${(stats.avg_confidence * 100).toFixed(1)}%`,
          icon: BarChart3,
          color: "cyan" as const,
        },
        { label: "อัปโหลดวันนี้", value: stats.documents_today, icon: FileText, color: "pink" as const },
      ]
    : [];

  const categoryTotal = categories.reduce((sum, c) => sum + c.total, 0) || 1;

  const dailyChartData = dailySales.slice(-10).map((d) => ({
    date: d.date.slice(5),
    ยอดขาย: d.total,
  }));

  const merchantChartData = topMerchants.map((m) => ({
    merchant: m.merchant.length > 20 ? m.merchant.slice(0, 18) + "…" : m.merchant,
    ยอดรวม: m.total,
  }));

  return (
    <div>
      <Group justify="space-between" mb="lg" wrap="wrap">
        <div>
          <Title order={2}>Dashboard</Title>
          <Text c="dimmed" size="sm" mt={4}>
            ภาพรวมข้อมูลยอดขายจากเอกสาร
          </Text>
        </div>
        <Group gap="sm" wrap="wrap">
          <DatePickerInput
            type="range"
            placeholder="เลือกช่วงวันที่"
            value={exportDateRange}
            onChange={(v) => setExportDateRange(v as [Date | null, Date | null])}
            locale="th"
            clearable
            w={260}
          />
          <Button
            component="a"
            href={getExportUrl({
              date_from: exportDateFrom || undefined,
              date_to: exportDateTo || undefined,
            })}
            color="green"
            leftSection={<Download size={16} />}
          >
            Export CSV
          </Button>
        </Group>
      </Group>

      {/* Stats cards */}
      <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="md" mb="lg">
        {statCards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <Paper key={idx} withBorder p="md">
              <Group justify="space-between" mb="xs">
                <Text size="sm" c="dimmed" fw={500}>{card.label}</Text>
                <ThemeIcon size="lg" radius="md" variant="light" color={card.color}>
                  <Icon size={18} />
                </ThemeIcon>
              </Group>
              <Text size="xl" fw={700}>{card.value}</Text>
            </Paper>
          );
        })}
      </SimpleGrid>

      {/* AI Business Insight */}
      <Paper withBorder p="md" mb="lg" radius="md" style={{ background: "linear-gradient(135deg, var(--mantine-color-indigo-0) 0%, var(--mantine-color-violet-0) 100%)" }}>
        {!aiInsight ? (
          <Group justify="space-between">
            <Group gap="xs">
              <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: "indigo", to: "violet" }}>
                <TrendingUp size={20} />
              </ThemeIcon>
              <Text fw={700} size="sm">AI Business Insight</Text>
            </Group>
            <Button
              variant="gradient"
              gradient={{ from: "indigo", to: "violet" }}
              size="sm"
              onClick={handleAiInsight}
              loading={insightLoading}
            >
              วิเคราะห์
            </Button>
          </Group>
        ) : (
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={700}>{aiInsight.headline}</Text>
              <Button variant="subtle" size="xs" color="indigo" onClick={handleAiInsight} loading={insightLoading}>
                วิเคราะห์ใหม่
              </Button>
            </Group>

            <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
              {aiInsight.insights.slice(0, 3).map((text, i) => (
                <Paper key={i} p="xs" radius="sm" withBorder>
                  <Text size="xs" lineClamp={2}>{text}</Text>
                </Paper>
              ))}
            </SimpleGrid>

            {(aiInsight.risks.length > 0 || aiInsight.opportunities.length > 0) && (
              <Group gap="md">
                {aiInsight.risks.slice(0, 2).map((text, i) => (
                  <Badge key={i} color="red" variant="light" size="sm" style={{ maxWidth: "48%" }}>
                    ⚠ {text.length > 50 ? text.slice(0, 50) + "…" : text}
                  </Badge>
                ))}
                {aiInsight.opportunities.slice(0, 2).map((text, i) => (
                  <Badge key={i} color="green" variant="light" size="sm" style={{ maxWidth: "48%" }}>
                    ✦ {text.length > 50 ? text.slice(0, 50) + "…" : text}
                  </Badge>
                ))}
              </Group>
            )}
          </Stack>
        )}
      </Paper>

      {/* Charts row 1: daily sales + top merchants */}
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" mb="lg">
        <Paper withBorder p="md">
          <Text fw={600} mb="md">ยอดขายรายวัน (30 วันล่าสุด)</Text>
          {dailySales.length === 0 ? (
            <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
          ) : (
            <BarChart
              h={250}
              data={dailyChartData}
              dataKey="date"
              series={[{ name: "ยอดขาย", color: "indigo.6" }]}
              tickLine="y"
              gridAxis="y"
              valueFormatter={(v) => `฿${v.toLocaleString("th-TH")}`}
            />
          )}
        </Paper>

        <Paper withBorder p="md">
          <Text fw={600} mb="md">ร้านค้ายอดสูงสุด</Text>
          {topMerchants.length === 0 ? (
            <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
          ) : (
            <BarChart
              h={250}
              data={merchantChartData}
              dataKey="merchant"
              series={[{ name: "ยอดรวม", color: "grape.6" }]}
              tickLine="y"
              gridAxis="y"
              valueFormatter={(v) => `฿${v.toLocaleString("th-TH")}`}
            />
          )}
        </Paper>
      </SimpleGrid>

      {/* Charts row 2: category breakdown + VAT summary */}
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" mb="lg">
        <Paper withBorder p="md">
          <Text fw={600} mb="md">สัดส่วนค่าใช้จ่ายตามหมวดหมู่</Text>
          {categories.length === 0 ? (
            <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
          ) : (
            <Stack gap="sm">
              <div className="flex h-6 rounded-full overflow-hidden">
                {categories.map((c) => (
                  <div
                    key={c.category}
                    className={`${CATEGORY_TW_COLORS[c.category] || "bg-gray-400"} transition-all`}
                    style={{ width: `${(c.total / categoryTotal) * 100}%` }}
                    title={`${c.category}: ฿${c.total.toLocaleString("th-TH")}`}
                  />
                ))}
              </div>
              <Stack gap="xs" mt="xs">
                {categories.map((c) => (
                  <Group key={c.category} justify="space-between">
                    <Group gap="xs">
                      <Badge size="xs" color={CATEGORY_COLORS[c.category] || "gray"} variant="filled" circle>
                        {" "}
                      </Badge>
                      <Text size="sm">{c.category}</Text>
                      <Text size="xs" c="dimmed">({c.count})</Text>
                    </Group>
                    <Group gap="md">
                      <Text size="xs" c="dimmed">
                        {((c.total / categoryTotal) * 100).toFixed(0)}%
                      </Text>
                      <Text size="xs" ff="monospace" w={100} ta="right">
                        ฿{c.total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                      </Text>
                    </Group>
                  </Group>
                ))}
              </Stack>
            </Stack>
          )}
        </Paper>

        <Paper withBorder p="md">
          <Group gap="xs" mb="md">
            <Receipt size={16} />
            <Text fw={600}>สรุป VAT รายเดือน</Text>
          </Group>
          {!vatSummary || vatSummary.months.length === 0 ? (
            <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
          ) : (
            <div className="overflow-x-auto">
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>เดือน</Table.Th>
                    <Table.Th ta="right">ยอดก่อน VAT</Table.Th>
                    <Table.Th ta="right">VAT 7%</Table.Th>
                    <Table.Th ta="right">ยอดรวม</Table.Th>
                    <Table.Th ta="right">เอกสาร</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {vatSummary.months.map((m) => (
                    <Table.Tr key={m.month}>
                      <Table.Td fw={500}>{m.month}</Table.Td>
                      <Table.Td ta="right">
                        <Text ff="monospace" size="sm">
                          ฿{m.subtotal.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        <Text ff="monospace" size="sm" c="yellow.7" fw={500}>
                          ฿{m.vat.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        <Text ff="monospace" size="sm">
                          ฿{m.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        <Text size="sm" c="dimmed">{m.count}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
                <Table.Tfoot>
                  <Table.Tr style={{ borderTop: "2px solid var(--mantine-color-default-border)" }}>
                    <Table.Td fw={700}>รวม</Table.Td>
                    <Table.Td ta="right">
                      <Text ff="monospace" size="sm" fw={600}>
                        ฿{vatSummary.totals.subtotal.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text ff="monospace" size="sm" c="yellow.7" fw={600}>
                        ฿{vatSummary.totals.vat.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text ff="monospace" size="sm" fw={600}>
                        ฿{vatSummary.totals.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text size="sm" c="dimmed" fw={600}>{vatSummary.totals.count}</Text>
                    </Table.Td>
                  </Table.Tr>
                </Table.Tfoot>
              </Table>
            </div>
          )}
        </Paper>
      </SimpleGrid>

      {/* Spending Heatmap + Fraud Summary */}
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md" mb="lg">
        <Paper withBorder p="md">
          <Text fw={600} mb="md">Spending Heatmap (90 วัน)</Text>
          {heatmapData.length === 0 ? (
            <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
          ) : (
            <SpendingHeatmap data={heatmapData} />
          )}
        </Paper>

        <Paper withBorder p="md">
          <Group gap="xs" mb="md">
            <ShieldAlert size={16} />
            <Text fw={600}>Fraud Detection</Text>
          </Group>
          {!fraudSummary || fraudSummary.total_flagged === 0 ? (
            <Stack align="center" py="xl" gap="sm">
              <ThemeIcon size={48} radius="xl" color="green" variant="light">
                <CheckCircle2 size={24} />
              </ThemeIcon>
              <Text c="green" fw={500}>ไม่พบรายการต้องสงสัย</Text>
              <Text c="dimmed" size="sm">เอกสารทั้งหมดผ่านการตรวจสอบ</Text>
            </Stack>
          ) : (
            <Stack gap="md">
              <Group gap="sm" grow>
                {fraudSummary.by_severity.high > 0 && (
                  <Paper withBorder p="sm" ta="center" style={{ borderColor: "var(--mantine-color-red-4)" }}>
                    <Text size="xl" fw={700} c="red">{fraudSummary.by_severity.high}</Text>
                    <Text size="xs" c="red">ร้ายแรง</Text>
                  </Paper>
                )}
                {fraudSummary.by_severity.medium > 0 && (
                  <Paper withBorder p="sm" ta="center" style={{ borderColor: "var(--mantine-color-yellow-4)" }}>
                    <Text size="xl" fw={700} c="yellow.7">{fraudSummary.by_severity.medium}</Text>
                    <Text size="xs" c="yellow.7">ปานกลาง</Text>
                  </Paper>
                )}
                {fraudSummary.by_severity.low > 0 && (
                  <Paper withBorder p="sm" ta="center" style={{ borderColor: "var(--mantine-color-orange-4)" }}>
                    <Text size="xl" fw={700} c="orange">{fraudSummary.by_severity.low}</Text>
                    <Text size="xs" c="orange">ต่ำ</Text>
                  </Paper>
                )}
              </Group>
              <Stack gap="xs">
                {fraudSummary.documents.slice(0, 5).map((d) => (
                  <Paper
                    key={d.id}
                    component={Link}
                    to={`/documents/${d.id}`}
                    withBorder
                    p="sm"
                    className="hover:bg-[var(--mantine-color-default-hover)] transition-colors no-underline"
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <div className="min-w-0 flex-1">
                        <Text size="sm" fw={500} truncate>
                          {d.merchant_name || d.filename}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {d.flags.join(", ")}
                        </Text>
                      </div>
                      <Group gap="sm" wrap="nowrap" className="shrink-0">
                        {d.grand_total != null && (
                          <Text size="xs" ff="monospace">
                            ฿{d.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                          </Text>
                        )}
                        <div
                          className={`w-2 h-2 rounded-full shrink-0 ${
                            d.severity === "high"
                              ? "bg-red-500"
                              : d.severity === "medium"
                                ? "bg-amber-500"
                                : "bg-yellow-400"
                          }`}
                        />
                      </Group>
                    </Group>
                  </Paper>
                ))}
              </Stack>
              {fraudSummary.total_flagged > 5 && (
                <Text size="xs" c="dimmed" ta="center">
                  และอีก {fraudSummary.total_flagged - 5} รายการ
                </Text>
              )}
            </Stack>
          )}
        </Paper>
      </SimpleGrid>

      {/* Recent docs */}
      <Paper withBorder>
        <Group justify="space-between" p="md" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
          <Text fw={600}>เอกสารล่าสุด</Text>
          <Text component={Link} to="/documents" size="sm" c="indigo" className="hover:underline">
            ดูทั้งหมด
          </Text>
        </Group>
        {recent.length === 0 ? (
          <Text c="dimmed" ta="center" py="xl">ยังไม่มีเอกสาร</Text>
        ) : (
          <Stack gap={0}>
            {recent.map((doc) => (
              <Link
                key={doc.id}
                to={`/documents/${doc.id}`}
                className="flex items-center justify-between p-4 hover:bg-[var(--mantine-color-default-hover)] transition-colors no-underline"
                style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}
              >
                <div>
                  <Text fw={500}>{doc.merchant_name || doc.filename}</Text>
                  <Text size="sm" c="dimmed">
                    {new Date(doc.uploaded_at).toLocaleString("th-TH")} · {doc.item_count} รายการ
                  </Text>
                </div>
                <div className="text-right shrink-0">
                  {doc.grand_total != null && (
                    <Text fw={600}>
                      ฿{doc.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                    </Text>
                  )}
                  {doc.confidence != null && (
                    <Text
                      size="sm"
                      c={
                        doc.confidence >= 0.9
                          ? "green"
                          : doc.confidence >= 0.7
                            ? "yellow.7"
                            : "red"
                      }
                    >
                      {(doc.confidence * 100).toFixed(0)}%
                    </Text>
                  )}
                </div>
              </Link>
            ))}
          </Stack>
        )}
      </Paper>
    </div>
  );
}

// ---------- Spending Heatmap ----------

const DAY_LABELS = ["", "จ", "", "พ", "", "ศ", ""];
const MONTH_LABELS_TH = [
  "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
  "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
];

function getHeatColor(value: number, max: number): string {
  if (value === 0) return "bg-[var(--mantine-color-default-border)]";
  const ratio = value / max;
  if (ratio < 0.25) return "bg-emerald-200";
  if (ratio < 0.5) return "bg-emerald-400";
  if (ratio < 0.75) return "bg-emerald-500";
  return "bg-emerald-700";
}

function SpendingHeatmap({ data }: { data: HeatmapDay[] }) {
  const maxTotal = useMemo(() => Math.max(...data.map((d) => d.total), 1), [data]);

  const weeks = useMemo(() => {
    if (data.length === 0) return [];
    const result: (HeatmapDay | null)[][] = [];
    let currentWeek: (HeatmapDay | null)[] = [];

    const firstDate = new Date(data[0].date + "T00:00:00");
    const startDow = (firstDate.getDay() + 6) % 7;
    for (let i = 0; i < startDow; i++) currentWeek.push(null);

    for (const day of data) {
      currentWeek.push(day);
      if (currentWeek.length === 7) {
        result.push(currentWeek);
        currentWeek = [];
      }
    }
    if (currentWeek.length > 0) {
      while (currentWeek.length < 7) currentWeek.push(null);
      result.push(currentWeek);
    }
    return result;
  }, [data]);

  const monthLabels = useMemo(() => {
    const labels: { col: number; label: string }[] = [];
    let lastMonth = -1;
    weeks.forEach((week, colIdx) => {
      for (const day of week) {
        if (day) {
          const m = new Date(day.date + "T00:00:00").getMonth();
          if (m !== lastMonth) {
            labels.push({ col: colIdx, label: MONTH_LABELS_TH[m] });
            lastMonth = m;
          }
          break;
        }
      }
    });
    return labels;
  }, [weeks]);

  return (
    <div>
      <div className="flex ml-7 mb-1">
        {monthLabels.map((m, i) => (
          <span
            key={i}
            className="text-[10px] text-[var(--mantine-color-dimmed)]"
            style={{ position: "relative", left: `${m.col * 14}px` }}
          >
            {m.label}
          </span>
        ))}
      </div>
      <div className="flex gap-0">
        <div className="flex flex-col gap-[2px] mr-1 shrink-0">
          {DAY_LABELS.map((label, i) => (
            <div key={i} className="w-5 h-[12px] flex items-center justify-end">
              <span className="text-[10px] text-[var(--mantine-color-dimmed)] leading-none">{label}</span>
            </div>
          ))}
        </div>
        <div className="flex gap-[2px] overflow-x-auto">
          {weeks.map((week, colIdx) => (
            <div key={colIdx} className="flex flex-col gap-[2px]">
              {week.map((day, rowIdx) => (
                <div
                  key={rowIdx}
                  className={`w-[12px] h-[12px] rounded-[2px] ${day ? getHeatColor(day.total, maxTotal) : "bg-transparent"} transition-colors`}
                  title={
                    day
                      ? `${day.date}: ฿${day.total.toLocaleString("th-TH", { minimumFractionDigits: 2 })} (${day.count} เอกสาร)`
                      : ""
                  }
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-end gap-1 mt-2">
        <span className="text-[10px] text-[var(--mantine-color-dimmed)] mr-1">น้อย</span>
        <div className="w-[12px] h-[12px] rounded-[2px] bg-[var(--mantine-color-default-border)]" />
        <div className="w-[12px] h-[12px] rounded-[2px] bg-emerald-200" />
        <div className="w-[12px] h-[12px] rounded-[2px] bg-emerald-400" />
        <div className="w-[12px] h-[12px] rounded-[2px] bg-emerald-500" />
        <div className="w-[12px] h-[12px] rounded-[2px] bg-emerald-700" />
        <span className="text-[10px] text-[var(--mantine-color-dimmed)] ml-1">มาก</span>
      </div>
    </div>
  );
}
