import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  AlertCircle,
  BarChart3,
  Brain,
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  PackageSearch,
  Receipt,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { BarChart, Sparkline } from "@mantine/charts";
import "dayjs/locale/th";
import {
  type AiInsightResponse,
  type ExportFormat,
  type HeatmapDay,
  getExportUrl,
} from "../api/client";
import {
  useAiInsight,
  useCatalogGaps,
  useCategoryBreakdown,
  useDailySales,
  useDashboardStats,
  useDocuments,
  useFraudSummary,
  usePeriodComparison,
  useSpendingHeatmap,
  useTopMerchants,
  useTopProducts,
  useTypoRecoveries,
  useVatSummary,
} from "../api/queries";
import { PeriodComparisonCard } from "@/components/PeriodComparison";

import { CATEGORY_COLORS, CATEGORY_TW_COLORS } from "@/lib/categories";

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (!then) return "ไม่ทราบ";
  const now = Date.now();
  const sec = Math.max(1, Math.round((now - then) / 1000));
  if (sec < 60) return `${sec} วินาทีที่แล้ว`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} นาทีที่แล้ว`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ชั่วโมงที่แล้ว`;
  const day = Math.round(hr / 24);
  return `${day} วันที่แล้ว`;
}

const EXPORT_FORMAT_OPTIONS: { value: ExportFormat; label: string; hint: string }[] = [
  { value: "line_items", label: "รายการสินค้า (ละเอียด)", hint: "1 แถวต่อสินค้า + ยอดรวมของเอกสาร" },
  { value: "summary", label: "สรุปรายเอกสาร", hint: "1 แถวต่อเอกสาร พร้อมยอด VAT/สุทธิ" },
  { value: "purchase_journal", label: "สมุดซื้อ (ภาษีซื้อ)", hint: "รูปแบบมาตรฐานยื่นภาษี ภ.พ.30" },
  { value: "journal_entries", label: "บัญชีแบบ Dr/Cr", hint: "สำหรับลงสมุดบัญชี double-entry" },
];

export default function DashboardPage() {
  const [exportDateRange, setExportDateRange] = useState<[Date | null, Date | null]>([null, null]);
  const [exportFormat, setExportFormat] = useState<ExportFormat>("line_items");
  const [aiInsight, setAiInsight] = useState<AiInsightResponse | null>(null);

  const exportDateFrom = exportDateRange[0] ? format(exportDateRange[0], "yyyy-MM-dd") : "";
  const exportDateTo = exportDateRange[1] ? format(exportDateRange[1], "yyyy-MM-dd") : "";

  const statsQuery = useDashboardStats();
  const periodComparisonQuery = usePeriodComparison("month");
  const recentQuery = useDocuments({ limit: 5 });
  const dailyQuery = useDailySales(30);
  const topMerchantsQuery = useTopMerchants(5);
  const [topProductsScope, setTopProductsScope] = useState<"all" | "catalog">("all");
  const [topProductsExpanded, setTopProductsExpanded] = useState(false);
  const topProductsQuery = useTopProducts(10, { catalog_only: topProductsScope === "catalog" });
  const categoriesQuery = useCategoryBreakdown();
  const vatQuery = useVatSummary();
  const fraudQuery = useFraudSummary();
  const heatmapQuery = useSpendingHeatmap(90);
  const catalogGapsQuery = useCatalogGaps(30);
  const typoRecoveriesQuery = useTypoRecoveries(30);
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
  const topProducts = topProductsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const vatSummary = vatQuery.data ?? null;
  const fraudSummary = fraudQuery.data ?? null;
  const heatmapData = heatmapQuery.data ?? [];

  const handleAiInsight = async () => {
    try {
      const data = await aiInsightMut.mutateAsync();
      setAiInsight(data);
    } catch {
      setAiInsight({
        headline: "ไม่สามารถสร้าง insight ได้",
        insights: [],
        risks: [],
        opportunities: [],
        trends: [],
        doc_count: 0,
        generated_at: new Date().toISOString(),
      });
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

  // Last-14-day series for sparklines (pad short data)
  const recentDaily = dailySales.slice(-14);
  const salesSeries = recentDaily.map((d) => d.total);
  const countSeries = recentDaily.map((d) => d.count);

  const pc = periodComparisonQuery.data;
  const salesDeltaPct = pc?.delta.total_pct ?? null;
  const docsDeltaPct = pc?.delta.count_pct ?? null;

  const statCards: StatCardData[] = stats
    ? [
        {
          label: "เอกสารทั้งหมด",
          value: stats.total_documents.toLocaleString("th-TH"),
          icon: FileText,
          color: "indigo",
          deltaPct: docsDeltaPct,
          sparkline: countSeries,
          context: "all time",
        },
        {
          label: "รอตรวจสอบ",
          value: stats.pending_review.toLocaleString("th-TH"),
          icon: AlertCircle,
          color: "yellow",
          context: "ใน queue",
        },
        {
          label: "ตรวจสอบแล้ว",
          value: stats.reviewed.toLocaleString("th-TH"),
          icon: CheckCircle2,
          color: "green",
          context: "สะสม",
        },
        {
          label: "ยอดขายรวม",
          value: `฿${stats.total_sales.toLocaleString("th-TH", { minimumFractionDigits: 2 })}`,
          icon: TrendingUp,
          color: "grape",
          deltaPct: salesDeltaPct,
          sparkline: salesSeries,
          context: "เดือนนี้",
        },
        {
          label: "Avg Confidence",
          value: `${(stats.avg_confidence * 100).toFixed(1)}%`,
          icon: BarChart3,
          color: "cyan",
          context: "AI accuracy",
        },
        {
          label: "อัปโหลดวันนี้",
          value: stats.documents_today.toLocaleString("th-TH"),
          icon: FileText,
          color: "pink",
          context: "วันนี้",
        },
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
            w={220}
          />
          <Select
            placeholder="รูปแบบไฟล์"
            w={220}
            value={exportFormat}
            onChange={(v) => v && setExportFormat(v as ExportFormat)}
            data={EXPORT_FORMAT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            description={EXPORT_FORMAT_OPTIONS.find((o) => o.value === exportFormat)?.hint}
            allowDeselect={false}
          />
          <Button
            component="a"
            href={getExportUrl({
              date_from: exportDateFrom || undefined,
              date_to: exportDateTo || undefined,
              format: exportFormat,
            })}
            color="green"
            leftSection={<Download size={16} />}
          >
            Export CSV
          </Button>
        </Group>
      </Group>

      {/* Period comparison */}
      <div style={{ marginBottom: "var(--mantine-spacing-lg)" }}>
        <PeriodComparisonCard />
      </div>

      {/* Stats cards */}
      <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="md" mb="lg">
        {statCards.map((card, idx) => (
          <StatCard key={idx} card={card} />
        ))}
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
            <Group justify="space-between" align="flex-start">
              <Group gap="xs" align="center">
                <ThemeIcon size="md" radius="md" variant="gradient" gradient={{ from: "indigo", to: "violet" }}>
                  <TrendingUp size={16} />
                </ThemeIcon>
                <div>
                  <Text fw={700} size="sm">AI Business Insight</Text>
                  <Text size="xs" c="dimmed">
                    ดึงจาก {aiInsight.doc_count.toLocaleString("th-TH")} เอกสาร · อัปเดต {formatRelativeTime(aiInsight.generated_at)}
                  </Text>
                </div>
              </Group>
              <Button variant="subtle" size="xs" color="indigo" onClick={handleAiInsight} loading={insightLoading}>
                วิเคราะห์ใหม่
              </Button>
            </Group>

            <Text fw={600} size="md">{aiInsight.headline}</Text>

            {(aiInsight.risks.length > 0 ||
              aiInsight.opportunities.length > 0 ||
              aiInsight.trends.length > 0) && (
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
                {aiInsight.risks.slice(0, 1).map((text, i) => (
                  <Paper
                    key={`r-${i}`}
                    p="xs"
                    radius="sm"
                    withBorder
                    style={{ borderLeft: "3px solid var(--mantine-color-red-5)" }}
                  >
                    <Text size="xs" fw={600} c="red.7" mb={2}>
                      ⚠ Risk
                    </Text>
                    <Text size="xs" lineClamp={2}>
                      {text}
                    </Text>
                  </Paper>
                ))}
                {aiInsight.opportunities.slice(0, 1).map((text, i) => (
                  <Paper
                    key={`o-${i}`}
                    p="xs"
                    radius="sm"
                    withBorder
                    style={{ borderLeft: "3px solid var(--mantine-color-green-5)" }}
                  >
                    <Text size="xs" fw={600} c="green.7" mb={2}>
                      ✦ Opportunity
                    </Text>
                    <Text size="xs" lineClamp={2}>
                      {text}
                    </Text>
                  </Paper>
                ))}
                {aiInsight.trends.slice(0, 1).map((text, i) => (
                  <Paper
                    key={`t-${i}`}
                    p="xs"
                    radius="sm"
                    withBorder
                    style={{ borderLeft: "3px solid var(--mantine-color-indigo-5)" }}
                  >
                    <Text size="xs" fw={600} c="indigo.7" mb={2}>
                      ↗ Trend
                    </Text>
                    <Text size="xs" lineClamp={2}>
                      {text}
                    </Text>
                  </Paper>
                ))}
              </SimpleGrid>
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

      {/* Top products (by revenue) */}
      <Paper withBorder p="md" mb="lg">
        <Group justify="space-between" mb="md" wrap="wrap">
          <div>
            <Text fw={600}>สินค้ายอดขายสูงสุด</Text>
            <Text size="xs" c="dimmed">เรียงตามยอดรวม (line_total)</Text>
          </div>
          <SegmentedControl
            size="xs"
            value={topProductsScope}
            onChange={(v) => setTopProductsScope(v as "all" | "catalog")}
            data={[
              { value: "all", label: "ทั้งหมด" },
              { value: "catalog", label: "เฉพาะ catalog" },
            ]}
          />
        </Group>
        {topProducts.length === 0 ? (
          <Text c="dimmed" size="sm" ta="center" py="xl">ยังไม่มีข้อมูล</Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={40}>#</Table.Th>
                <Table.Th>สินค้า</Table.Th>
                <Table.Th ta="right" w={100}>จำนวน</Table.Th>
                <Table.Th ta="right" w={100}>เอกสาร</Table.Th>
                <Table.Th ta="right" w={140}>ยอดรวม</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(topProductsExpanded ? topProducts : topProducts.slice(0, 5)).map((p, i) => (
                <Table.Tr key={p.product}>
                  <Table.Td>
                    <Badge
                      variant={i < 3 ? "gradient" : "light"}
                      gradient={i < 3 ? { from: "indigo", to: "violet" } : undefined}
                      size="sm"
                    >
                      {i + 1}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm" fw={500} lineClamp={1} style={{ flex: 1 }}>{p.product}</Text>
                      {p.in_catalog && p.manufacturer && (
                        <Badge
                          size="xs"
                          color={p.is_boonrawd ? "indigo" : "gray"}
                          variant="light"
                          title={p.manufacturer}
                        >
                          {p.is_boonrawd ? "บุญรอด" : "คู่แข่ง"}
                        </Badge>
                      )}
                      {p.in_catalog ? (
                        <Badge size="xs" color="green" variant="light" title={`SKU ${p.product_code}`}>catalog</Badge>
                      ) : (
                        <Badge size="xs" color="gray" variant="light">นอก</Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td ta="right">
                    <Text size="sm" ff="monospace">{p.quantity.toLocaleString("th-TH")}</Text>
                  </Table.Td>
                  <Table.Td ta="right">
                    <Text size="sm" c="dimmed">{p.doc_count}</Text>
                  </Table.Td>
                  <Table.Td ta="right">
                    <Text size="sm" ff="monospace" fw={600}>
                      ฿{p.total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        {topProducts.length > 5 && (
          <Group justify="center" mt="xs">
            <Button
              size="xs"
              variant="subtle"
              onClick={() => setTopProductsExpanded((v) => !v)}
            >
              {topProductsExpanded ? "ย่อ" : `ดูเพิ่มอีก ${topProducts.length - 5} รายการ`}
            </Button>
          </Group>
        )}
      </Paper>

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

      {/* Compact AI Health summary on dashboard — links to /ai-health for
          full detail. Admin observability content lives outside the dashboard
          so business analytics stay focused. */}
      {(() => {
        const gapCount = catalogGapsQuery.data?.gaps.length ?? 0;
        const gapHits = (catalogGapsQuery.data?.gaps ?? []).reduce((s, g) => s + g.hit_count, 0);
        const typoPatterns = typoRecoveriesQuery.data?.recoveries.length ?? 0;
        const typoHits = (typoRecoveriesQuery.data?.recoveries ?? []).reduce((s, r) => s + r.hit_count, 0);
        const healthy = gapCount === 0 && typoPatterns === 0;
        return (
          <Paper
            withBorder
            p="md"
            mb="lg"
            component={Link}
            to="/ai-health"
            className="cursor-pointer hover:shadow-md transition-shadow no-underline"
          >
            <Group justify="space-between" wrap="nowrap">
              <Group gap="md" wrap="nowrap">
                <ThemeIcon
                  size={36}
                  radius="md"
                  color={healthy ? "green" : "indigo"}
                  variant="light"
                >
                  <Brain size={18} />
                </ThemeIcon>
                <div>
                  <Text fw={600} size="sm">AI Health (30 วัน)</Text>
                  <Text c="dimmed" size="xs">
                    ระบบเฝ้าตัวเอง — กดเพื่อดูรายละเอียด
                  </Text>
                </div>
              </Group>
              <Group gap="lg" wrap="nowrap">
                <Stack gap={2} align="flex-end">
                  <Group gap={6} align="baseline">
                    <PackageSearch size={12} className="text-(--mantine-color-dimmed)" />
                    <Text size="lg" fw={700} c={gapCount > 0 ? "orange" : "green"}>
                      {gapCount}
                    </Text>
                    {gapHits > 0 && (
                      <Text size="xs" c="dimmed">({gapHits} hits)</Text>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">Catalog gaps</Text>
                </Stack>
                <Stack gap={2} align="flex-end">
                  <Group gap={6} align="baseline">
                    <AlertCircle size={12} className="text-(--mantine-color-dimmed)" />
                    <Text size="lg" fw={700} c={typoPatterns > 0 ? "yellow.7" : "green"}>
                      {typoPatterns}
                    </Text>
                    {typoHits > 0 && (
                      <Text size="xs" c="dimmed">({typoHits} hits)</Text>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">Typo recoveries</Text>
                </Stack>
                <ActionIcon variant="subtle" color="gray" size="sm" aria-label="ดูรายละเอียด">
                  <ChevronRight size={16} />
                </ActionIcon>
              </Group>
            </Group>
          </Paper>
        );
      })()}

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

type StatCardIcon = React.ComponentType<{ size?: number }>;

interface StatCardData {
  label: string;
  value: string;
  icon: StatCardIcon;
  color:
    | "indigo"
    | "yellow"
    | "green"
    | "grape"
    | "cyan"
    | "pink";
  deltaPct?: number | null;
  sparkline?: number[];
  context?: string;
}

function StatCard({ card }: { card: StatCardData }) {
  const Icon = card.icon;
  const hasDelta = card.deltaPct != null;
  const deltaPositive = hasDelta && (card.deltaPct as number) >= 0;
  const deltaColor = !hasDelta
    ? "dimmed"
    : deltaPositive
      ? "teal.7"
      : "red.7";
  const deltaArrow = !hasDelta ? "" : deltaPositive ? "↑" : "↓";
  const hasSparkline = card.sparkline && card.sparkline.length >= 2;

  return (
    <Paper withBorder p="md">
      <Group justify="space-between" align="flex-start" mb="xs" wrap="nowrap">
        <Text size="sm" c="dimmed" fw={500}>
          {card.label}
        </Text>
        <ThemeIcon size="lg" radius="md" variant="light" color={card.color}>
          <Icon size={18} />
        </ThemeIcon>
      </Group>
      <Group gap="xs" align="baseline" wrap="nowrap">
        <Text size="xl" fw={700} style={{ lineHeight: 1.1 }}>
          {card.value}
        </Text>
        {hasDelta && (
          <Text size="xs" c={deltaColor} fw={600}>
            {deltaArrow} {Math.abs(card.deltaPct as number).toFixed(1)}%
          </Text>
        )}
      </Group>
      {(hasSparkline || card.context) && (
        <Group justify="space-between" align="center" mt="xs" wrap="nowrap">
          {card.context && (
            <Text size="xs" c="dimmed">
              {card.context}
            </Text>
          )}
          {hasSparkline && (
            <Sparkline
              w={80}
              h={24}
              data={card.sparkline as number[]}
              curveType="monotone"
              color={card.color}
              fillOpacity={0.3}
              strokeWidth={1.5}
            />
          )}
        </Group>
      )}
    </Paper>
  );
}
