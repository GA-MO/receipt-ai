import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Calculator,
  CheckCircle2,
  CircleDashed,
  Loader2,
  PackageCheck,
  Plus,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { format, parse } from "date-fns";
import "dayjs/locale/th";
import {
  type DocumentItemData,
  type DocumentResponse,
  getDocumentImageUrl,
} from "../api/client";
import {
  useApproveDocument,
  useAutocomplete,
  useCreateItem,
  useDeleteDocument,
  useDeleteItem,
  useDocument,
  useReextractDocument,
  useUpdateDocument,
  useUpdateItem,
} from "../api/queries";
import { useDocumentStream } from "@/hooks/useDocumentStream";
import { parseFraudData } from "@/lib/fraud";
import {
  type TotalsPatch,
  type ValidationIssue,
  validateTotals,
} from "@/lib/validation";
import { CATEGORY_OPTIONS_WITH_BLANK as CATEGORY_OPTIONS } from "@/lib/categories";
import { useToast } from "@/components/Toast";
import { ImageCanvas } from "@/components/ImageCanvas";
import { DocumentHistory } from "@/components/DocumentHistory";

const SEVERITY_COLOR: Record<string, string> = {
  high: "red",
  medium: "yellow",
  low: "orange",
};

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  const { data: doc, isPending, error } = useDocument(id);
  const updateDoc = useUpdateDocument(id ?? "");
  const updateItemMut = useUpdateItem(id ?? "");
  const deleteItemMut = useDeleteItem(id ?? "");
  const createItemMut = useCreateItem(id ?? "");
  const approveMut = useApproveDocument();
  const deleteMut = useDeleteDocument();
  const reextractMut = useReextractDocument();

  const location = useLocation();
  // If we navigated here from within the app, go back to preserve filters/pagination.
  // Otherwise (direct URL / refresh), fall back to the documents list.
  const handleBack = () => {
    if (location.key !== "default") navigate(-1);
    else navigate("/documents");
  };

  // Shared autocomplete pools; dedup'd by React Query key so multiple item
  // rows each calling `useAutocomplete("product")` share one request.
  // Product limit is set high enough to include the full catalog (~237
  // SKUs + internal) so client-side filtering (Autocomplete substring)
  // can surface any entry the user starts typing — otherwise lower-ranked
  // SKUs like Silver Wolf / Silver Knight get cut off.
  const { data: merchantOptions = [] } = useAutocomplete("merchant", "", 100);
  const { data: productOptions = [] } = useAutocomplete("product", "", 500);
  const merchantSuggestions = merchantOptions.map((o) => o.value);
  const productSuggestions = productOptions.map((o) => o.value);
  // Lookup of canonical name → catalog SKU code, so saving an Autocomplete
  // pick can attach `product_code` directly instead of relying on the
  // server-side fuzzy resolver.
  const productCodeByName = useMemo(() => {
    const map = new Map<string, string>();
    for (const o of productOptions) {
      if (o.code) map.set(o.value, o.code);
    }
    return map;
  }, [productOptions]);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [reextractModalOpen, setReextractModalOpen] = useState(false);
  const [approveModalOpen, setApproveModalOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<"doc" | "form">("doc");
  const [form, setForm] = useState({
    merchant_name: "",
    document_number: "",
    document_date: "",
    category: "",
    subtotal: null as number | null,
    discount: null as number | null,
    vat: null as number | null,
    grand_total: null as number | null,
    notes: "",
  });

  // Sync form state with the current document whenever it changes.
  useEffect(() => {
    if (!doc) return;
    setForm({
      merchant_name: doc.merchant_name ?? "",
      document_number: doc.document_number ?? "",
      document_date: doc.document_date ?? "",
      category: doc.category ?? "",
      subtotal: doc.subtotal ?? null,
      discount: doc.discount ?? null,
      vat: doc.vat ?? null,
      grand_total: doc.grand_total ?? null,
      notes: doc.notes ?? "",
    });
  }, [doc]);

  useEffect(() => {
    if (error) toast("error", "ไม่สามารถโหลดเอกสารได้");
  }, [error, toast]);

  // Subscribe to SSE stream whenever the document is still processing.
  useDocumentStream(id, {
    enabled: doc?.status === "processing",
    onEvent: (ev) => {
      if (ev.status === "extracted") toast("success", "AI ดึงข้อมูลเสร็จแล้ว");
      else if (ev.status === "error") toast("error", ev.error_message || "เกิดข้อผิดพลาด");
    },
  });

  const handleSaveHeader = async () => {
    if (!id) return;
    try {
      await updateDoc.mutateAsync({
        merchant_name: form.merchant_name || null,
        document_number: form.document_number || null,
        document_date: form.document_date || null,
        category: form.category || null,
        subtotal: form.subtotal,
        discount: form.discount,
        vat: form.vat,
        grand_total: form.grand_total,
        notes: form.notes || null,
      });
      toast("success", "บันทึกเรียบร้อย");
    } catch {
      toast("error", "ไม่สามารถบันทึกได้");
    }
  };

  const applyFix = async (patch: TotalsPatch) => {
    if (!id) return;
    const next = { ...form, ...patch };
    setForm(next);
    try {
      await updateDoc.mutateAsync({
        merchant_name: next.merchant_name || null,
        document_number: next.document_number || null,
        document_date: next.document_date || null,
        category: next.category || null,
        subtotal: next.subtotal,
        discount: next.discount,
        vat: next.vat,
        grand_total: next.grand_total,
        notes: next.notes || null,
      });
      toast("success", "ปรับยอดให้แล้ว");
    } catch {
      toast("error", "ไม่สามารถบันทึกได้");
    }
  };

  // Apply all validation fixes in dependency order: items → vat → totals
  const applyAllFixes = async () => {
    const round2 = (n: number) => Math.round(n * 100) / 100;
    const discount = form.discount ?? 0;

    let newSubtotal = form.subtotal;
    let newVat = form.vat;
    let newGrand = form.grand_total;
    let anyChange = false;

    if (itemsIssue && itemsTotal > 0) {
      // Line items are VAT-inclusive: items_sum ≈ grand_total.
      // If VAT > 0, fix grand_total + recompute pre-VAT subtotal.
      // If no VAT, items_sum ≈ subtotal so just set subtotal.
      if (newVat != null && newVat > 0) {
        newGrand = round2(itemsTotal);
        newSubtotal = round2(itemsTotal / 1.07);
        newVat = round2(newGrand - newSubtotal);
      } else {
        newSubtotal = round2(itemsTotal);
      }
      anyChange = true;
    }
    if (vatIssue && newSubtotal != null) {
      newVat = round2(newSubtotal * 0.07);
      anyChange = true;
    }
    if (totalsIssue || anyChange) {
      newGrand = round2((newSubtotal ?? 0) - discount + (newVat ?? 0));
    }

    await applyFix({
      subtotal: newSubtotal,
      vat: newVat,
      grand_total: newGrand,
    });
  };

  const handleSaveItem = async (item: DocumentItemData, field: string, value: string) => {
    if (!id) return;
    const numFields = ["quantity", "unit_price", "line_total"];
    const val = numFields.includes(field)
      ? value === "" ? null : Number(value)
      : value;
    const data: Record<string, unknown> = { [field]: val };
    // When the user picks a product name from the catalog autocomplete,
    // pin the SKU code so the backend doesn't have to fuzzy-resolve and
    // possibly drop it. Free-text edits (no map hit) still go through the
    // server-side resolver. Empty string clears the code.
    if (field === "product_name_normalized") {
      const trimmed = (value || "").trim();
      if (!trimmed) {
        data.product_code = null;
      } else if (productCodeByName.has(trimmed)) {
        data.product_code = productCodeByName.get(trimmed);
      }
    }
    try {
      await updateItemMut.mutateAsync({ itemId: item.id, data });
    } catch {
      toast("error", "ไม่สามารถบันทึกรายการได้");
    }
  };

  const handleDeleteItem = async (item: DocumentItemData) => {
    if (!id) return;
    try {
      await deleteItemMut.mutateAsync(item.id);
      toast("success", "ลบรายการเรียบร้อย");
    } catch {
      toast("error", "ไม่สามารถลบรายการได้");
    }
  };

  const handleAddItem = async () => {
    if (!id) return;
    try {
      await createItemMut.mutateAsync({
        product_name_normalized: "",
        quantity: 1,
        unit: null,
        unit_price: null,
        line_total: null,
      });
      toast("success", "เพิ่มรายการใหม่");
    } catch {
      toast("error", "ไม่สามารถเพิ่มรายการได้");
    }
  };

  const doApprove = async () => {
    if (!id) return;
    try {
      await approveMut.mutateAsync(id);
      toast("success", "อนุมัติเรียบร้อย");
      setApproveModalOpen(false);
    } catch {
      toast("error", "ไม่สามารถอนุมัติได้");
      setApproveModalOpen(false);
    }
  };

  const handleApprove = async () => {
    if (!id || !doc) return;
    const offCatalog = doc.items.filter(
      (it) => !it.product_code && it.product_name_normalized,
    );
    if (offCatalog.length > 0) {
      setApproveModalOpen(true);
      return;
    }
    await doApprove();
  };

  const handleDelete = async () => {
    if (!id) return;
    try {
      await deleteMut.mutateAsync(id);
      toast("success", "ลบเรียบร้อย");
      navigate("/documents");
    } catch {
      toast("error", "ไม่สามารถลบได้");
    }
  };

  const handleReextract = async () => {
    if (!id) return;
    try {
      await reextractMut.mutateAsync(id);
      toast("info", "กำลังประมวลผลใหม่...");
    } catch {
      toast("error", "ไม่สามารถประมวลผลใหม่ได้");
    }
  };

  if (isPending) return <div className="flex items-center justify-center h-64"><Loader size="lg" /></div>;
  if (!doc) return <div className="p-8 text-center"><Text c="dimmed">ไม่พบเอกสาร</Text></div>;

  const saving = updateDoc.isPending;
  const isProcessing = doc.status === "processing";
  const confColor = (doc.confidence ?? 0) >= 0.9 ? "green" : (doc.confidence ?? 0) >= 0.7 ? "yellow" : "red";
  const { flags: fraudFlags, ai_analysis: aiAnalysis } = parseFraudData(doc.fraud_flags);

  // Live validation on current form state + items sum.
  const itemsTotal = doc.items.reduce(
    (s, it) => s + (typeof it.line_total === "number" ? it.line_total : 0),
    0,
  );
  const validationIssues = validateTotals({
    subtotal: form.subtotal,
    discount: form.discount,
    vat: form.vat,
    grand_total: form.grand_total,
    items_total: itemsTotal || null,
  });

  type HeroVariant = {
    color: string;
    bg: "strong" | "soft";
    icon: React.ReactNode;
    title: string;
    subtitle?: string;
    summary?: string;
    riskPct?: number;
    showFlags?: boolean;
  };

  const heroVariant: HeroVariant | null = (() => {
    const aiRisk = aiAnalysis?.risk_score ?? 0;
    const riskPct = Math.round(aiRisk * 100);

    if (doc.status === "error") {
      return {
        color: "red",
        bg: "strong",
        icon: <AlertTriangle size={22} />,
        title: "เกิดข้อผิดพลาด",
        subtitle: doc.error_message || "ประมวลผลเอกสารไม่สำเร็จ",
      };
    }
    if (doc.status === "processing") {
      return {
        color: "blue",
        bg: "strong",
        icon: <Loader2 size={22} className="animate-spin" />,
        title: "กำลังประมวลผล",
        subtitle: "AI กำลังดึงข้อมูลจากเอกสาร...",
      };
    }

    const highRisk = fraudFlags.length > 0 && aiRisk >= 0.5;
    const lowConf = (doc.confidence ?? 1) < 0.7;

    // B: reviewed + high risk → soft severity (human already approved)
    if (highRisk && doc.status === "reviewed") {
      return {
        color: "red",
        bg: "soft",
        icon: <ShieldCheck size={22} />,
        title: "อนุมัติแล้ว ทั้งที่มีความเสี่ยง",
        summary: aiAnalysis?.summary,
        riskPct,
        showFlags: true,
      };
    }
    if (highRisk) {
      return {
        color: "red",
        bg: "strong",
        icon: <ShieldAlert size={22} />,
        title: "พบความเสี่ยงสูง",
        summary: aiAnalysis?.summary,
        riskPct,
        showFlags: true,
      };
    }
    if (doc.status === "reviewed") {
      return {
        color: "green",
        bg: "strong",
        icon: <CheckCircle2 size={22} />,
        title: "ตรวจสอบเรียบร้อย",
        subtitle: "อนุมัติแล้ว",
      };
    }
    if (fraudFlags.length > 0 || lowConf) {
      return {
        color: "yellow",
        bg: "strong",
        icon: <AlertTriangle size={22} />,
        title: "ควรตรวจทาน",
        summary: aiAnalysis?.summary,
        riskPct: fraudFlags.length > 0 ? riskPct : undefined,
        showFlags: fraudFlags.length > 0,
      };
    }
    // Healthy default — no issues, no need for a hero banner
    return null;
  })();

  const heroSection = heroVariant && (
    <Paper
      withBorder
      p="md"
      radius="md"
      style={{
        background:
          heroVariant.bg === "strong"
            ? `var(--mantine-color-${heroVariant.color}-0)`
            : undefined,
        borderColor: `var(--mantine-color-${heroVariant.color}-${heroVariant.bg === "strong" ? "4" : "3"})`,
      }}
    >
      <Stack gap="md">
        <Group gap="md" wrap="nowrap" align="flex-start">
          <ThemeIcon
            color={heroVariant.color}
            variant="light"
            size={44}
            radius="xl"
          >
            {heroVariant.icon}
          </ThemeIcon>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Group justify="space-between" align="center" wrap="nowrap">
              <Text fw={700} size="md">
                {heroVariant.title}
              </Text>
              {heroVariant.riskPct != null && (
                <Badge
                  color={heroVariant.color}
                  variant={heroVariant.bg === "strong" ? "filled" : "light"}
                  size="sm"
                >
                  RISK {heroVariant.riskPct}%
                </Badge>
              )}
            </Group>
            {heroVariant.subtitle && (
              <Text size="sm" c="dimmed" mt={2}>
                {heroVariant.subtitle}
              </Text>
            )}
            {heroVariant.summary && (
              <Text size="sm" mt={4}>
                {heroVariant.summary}
              </Text>
            )}
          </div>
        </Group>

        {heroVariant.showFlags && fraudFlags.length > 0 && (
          <Stack gap={4}>
            {fraudFlags.map((flag, i) => (
              <div
                key={i}
                style={{
                  paddingLeft: 12,
                  borderLeft: `3px solid var(--mantine-color-${SEVERITY_COLOR[flag.severity] || "gray"}-5)`,
                }}
              >
                <Text size="sm" fw={600} lh={1.3}>
                  {flag.label}
                </Text>
                <Text size="xs" c="dimmed" lh={1.4}>
                  {flag.detail}
                </Text>
              </div>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );

  const imageSection = (
    <div>
      {doc.file_type === "pdf" ? (
        <iframe src={getDocumentImageUrl(doc.id)} className="w-full h-[600px] rounded-lg" title="PDF" />
      ) : (
        <div className="h-[600px] rounded-lg overflow-hidden">
          <ImageCanvas
            src={getDocumentImageUrl(doc.id)}
            alt={doc.filename}
            downloadFilename={doc.filename}
          />
        </div>
      )}
    </div>
  );

  const totalsIssue = validationIssues.find((i) => i.field === "totals");
  const vatIssue = validationIssues.find((i) => i.field === "vat");
  const itemsIssue = validationIssues.find((i) => i.field === "items");

  const expectedVat =
    form.subtotal != null ? form.subtotal * 0.07 : null;
  const expectedGrand =
    form.subtotal != null
      ? form.subtotal - (form.discount ?? 0) + (form.vat ?? 0)
      : null;

  const formSection = (
    <Stack gap="lg">
      <div className="grid grid-cols-2 gap-3">
        <Autocomplete
          label="ร้านค้า"
          value={form.merchant_name}
          onChange={(v) => setForm({ ...form, merchant_name: v })}
          data={merchantSuggestions}
          limit={10}
          disabled={isProcessing}
          placeholder="พิมพ์เพื่อดูชื่อร้านที่เคยใช้..."
        />
        <TextInput
          label="เลขที่เอกสาร"
          value={form.document_number}
          onChange={(e) => setForm({ ...form, document_number: e.currentTarget.value })}
          disabled={isProcessing}
        />
        <DatePickerInput
          label="วันที่"
          locale="th"
          valueFormat="DD/MM/YYYY"
          clearable
          value={form.document_date ? parse(form.document_date, "yyyy-MM-dd", new Date()) : null}
          onChange={(v) => setForm({ ...form, document_date: v ? format(v, "yyyy-MM-dd") : "" })}
          disabled={isProcessing}
        />
        <Select
          label="หมวดหมู่"
          data={CATEGORY_OPTIONS}
          value={form.category}
          onChange={(v) => setForm({ ...form, category: v || "" })}
          disabled={isProcessing}
        />
      </div>

      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed" fw={700} tt="uppercase" lts={1}>
            ยอดเงิน
          </Text>
          {validationIssues.length > 0 && (
            <Button
              size="xs"
              variant="light"
              color="indigo"
              leftSection={<Calculator size={14} />}
              onClick={applyAllFixes}
              disabled={isProcessing || saving}
            >
              แก้อัตโนมัติ
            </Button>
          )}
        </Group>

        <div className="grid grid-cols-2 gap-3">
          <AmountField
            label="ยอดก่อนภาษี"
            value={form.subtotal}
            onChange={(v) => setForm({ ...form, subtotal: v })}
            disabled={isProcessing}
            warning={
              itemsIssue && (form.vat == null || form.vat === 0)
                ? "ไม่ตรงกับผลรวมสินค้า"
                : undefined
            }
          />
          <AmountField
            label="ส่วนลด"
            value={form.discount}
            onChange={(v) => setForm({ ...form, discount: v })}
            disabled={isProcessing}
          />
          <AmountField
            label="VAT 7%"
            value={form.vat}
            onChange={(v) => setForm({ ...form, vat: v })}
            disabled={isProcessing}
            warning={
              vatIssue && expectedVat != null
                ? `ควรเป็น ${fmtBaht(expectedVat)}`
                : undefined
            }
          />
        </div>

        <Paper
          withBorder
          p="md"
          radius="md"
          style={{
            background: "var(--mantine-color-indigo-0)",
            borderColor: totalsIssue
              ? "var(--mantine-color-orange-4)"
              : "var(--mantine-color-indigo-3)",
          }}
        >
          <Group justify="space-between" align="center" wrap="nowrap">
            <Stack gap={0}>
              <Text size="sm" fw={600} c="indigo.7">
                ยอดรวมสุทธิ
              </Text>
              <Text size="xs" c="dimmed">
                รวม VAT · สุทธิ
              </Text>
            </Stack>
            <NumberInput
              prefix="฿"
              thousandSeparator=","
              decimalScale={2}
              value={form.grand_total ?? ""}
              onChange={(v) =>
                setForm({ ...form, grand_total: v === "" ? null : Number(v) })
              }
              disabled={isProcessing}
              variant="unstyled"
              hideControls
              styles={{
                input: {
                  fontSize: 26,
                  fontWeight: 700,
                  textAlign: "right",
                  color: totalsIssue
                    ? "var(--mantine-color-orange-7)"
                    : "var(--mantine-color-indigo-9)",
                  padding: 0,
                  height: "auto",
                  minWidth: 180,
                },
              }}
            />
          </Group>
          {totalsIssue && expectedGrand != null && (
            <Text size="xs" c="orange.7" ta="right" mt={4}>
              ควรเป็น ฿{fmtBaht(expectedGrand)}
            </Text>
          )}
          {itemsIssue && form.vat != null && form.vat > 0 && (
            <Text size="xs" c="orange.7" ta="right" mt={4}>
              ไม่ตรงกับผลรวมสินค้า ฿{fmtBaht(itemsTotal)}
            </Text>
          )}
        </Paper>
      </Stack>

      <div>
        <Group justify="space-between" mb="sm">
          <Group gap="xs">
            <Text fw={600} size="sm">รายการสินค้า ({doc.items.length})</Text>
            {(() => {
              const off = doc.items.filter((it) => !it.product_code);
              const linked = doc.items.length - off.length;
              if (doc.items.length === 0) return null;
              return (
                <Tooltip
                  label={
                    off.length === 0
                      ? "ทุกรายการอยู่ใน catalog"
                      : `${linked} รายการอยู่ใน catalog, ${off.length} รายการนอก catalog`
                  }
                >
                  <Badge
                    size="xs"
                    color={off.length === 0 ? "green" : off.length === doc.items.length ? "gray" : "yellow"}
                    variant="light"
                  >
                    catalog {linked}/{doc.items.length}
                  </Badge>
                </Tooltip>
              );
            })()}
          </Group>
          <Button
            size="xs"
            variant="light"
            leftSection={<Plus size={14} />}
            onClick={handleAddItem}
            loading={createItemMut.isPending}
            disabled={isProcessing}
          >
            เพิ่มรายการ
          </Button>
        </Group>
        {(() => {
          const off = doc.items.filter((it) => !it.product_code && it.product_name_normalized);
          if (off.length === 0) return null;
          return (
            <Alert
              color="yellow"
              icon={<AlertTriangle size={14} />}
              py="xs"
              mb="sm"
              variant="light"
              styles={{ wrapper: { alignItems: "center" } }}
            >
              <Text size="xs">
                <b>{off.length} รายการ</b> ไม่อยู่ใน catalog
              </Text>
            </Alert>
          );
        })()}
        {doc.items.length > 0 ? (
          <Paper withBorder className="overflow-x-auto">
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>สินค้า</Table.Th>
                  <Table.Th ta="right" w={80}>จำนวน</Table.Th>
                  <Table.Th w={70}>หน่วย</Table.Th>
                  <Table.Th ta="right" w={100}>ราคา/หน่วย</Table.Th>
                  <Table.Th ta="right" w={100}>ยอดรวม</Table.Th>
                  <Table.Th w={40} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {doc.items.map((item) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    onSave={handleSaveItem}
                    onDelete={handleDeleteItem}
                    suggestions={productSuggestions}
                  />
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
        ) : (
          <Paper withBorder p="md" ta="center">
            <Text size="sm" c="dimmed">ยังไม่มีรายการสินค้า — กด "เพิ่มรายการ" เพื่อเริ่มต้น</Text>
          </Paper>
        )}
      </div>

      <Textarea
        label="หมายเหตุ"
        value={form.notes}
        onChange={(e) => setForm({ ...form, notes: e.currentTarget.value })}
        rows={3}
        disabled={isProcessing}
        placeholder="เพิ่มหมายเหตุ..."
      />

      {id && <DocumentHistory documentId={id} />}
    </Stack>
  );

  const modals = (
    <>
      <Modal opened={reextractModalOpen} onClose={() => setReextractModalOpen(false)} title="ประมวลผลใหม่" centered>
        <Text size="sm" c="dimmed">ต้องการให้ AI ประมวลผลใหม่? ข้อมูลเดิมจะถูกแทนที่</Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="outline" onClick={() => setReextractModalOpen(false)}>ยกเลิก</Button>
          <Button onClick={() => { setReextractModalOpen(false); handleReextract(); }}>ยืนยัน</Button>
        </Group>
      </Modal>
      <Modal opened={approveModalOpen} onClose={() => setApproveModalOpen(false)} title="ยืนยันการอนุมัติ" centered>
        <Stack gap="sm">
          <Alert color="yellow" icon={<AlertTriangle size={16} />} variant="light" py="xs">
            <Text size="sm">
              มี <b>{doc.items.filter((it) => !it.product_code && it.product_name_normalized).length} รายการ</b> ที่ไม่อยู่ใน catalog
            </Text>
          </Alert>
          <Paper withBorder p="xs" style={{ maxHeight: 200, overflow: "auto" }}>
            <Stack gap={4}>
              {doc.items
                .filter((it) => !it.product_code && it.product_name_normalized)
                .slice(0, 20)
                .map((it) => (
                  <Group key={it.id} gap="xs">
                    <CircleDashed size={12} style={{ color: "var(--mantine-color-gray-6)" }} />
                    <Text size="xs">{it.product_name_normalized}</Text>
                  </Group>
                ))}
            </Stack>
          </Paper>
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setApproveModalOpen(false)}>
              ยกเลิก — แก้ก่อน
            </Button>
            <Button color="green" leftSection={<CheckCircle2 size={14} />} onClick={doApprove} loading={approveMut.isPending}>
              อนุมัติเลย
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal opened={deleteModalOpen} onClose={() => setDeleteModalOpen(false)} title="ลบเอกสาร" centered>
        <Text size="sm" c="dimmed">ต้องการลบเอกสารนี้? การดำเนินการนี้ไม่สามารถย้อนกลับได้</Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="outline" onClick={() => setDeleteModalOpen(false)}>ยกเลิก</Button>
          <Button color="red" leftSection={<Trash2 size={14} />} onClick={() => { setDeleteModalOpen(false); handleDelete(); }}>
            ลบ
          </Button>
        </Group>
      </Modal>
    </>
  );

  // ============================================
  // MOBILE LAYOUT
  // ============================================
  const mobileLayout = (
    <div className="lg:hidden flex flex-col h-full">
      {/* Sticky top bar */}
      <div className="sticky top-0 z-20 px-3 py-2" style={{ background: "var(--mantine-color-body)", borderBottom: "1px solid var(--mantine-color-default-border)" }}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" className="min-w-0">
            <ActionIcon variant="subtle" onClick={handleBack}>
              <ArrowLeft size={18} />
            </ActionIcon>
            <div className="min-w-0">
              <Text size="sm" fw={600} truncate>{doc.filename}</Text>
              <Group gap={4}>
                {doc.confidence != null && <Badge size="xs" color={confColor} variant="light">{(doc.confidence * 100).toFixed(0)}%</Badge>}
                {doc.status === "reviewed" && <Badge size="xs" color="green" variant="light" leftSection={<CheckCircle2 size={10} />}>ตรวจแล้ว</Badge>}
                {doc.status === "extracted" && <Badge size="xs" color="yellow" variant="light">รอตรวจ</Badge>}
                {doc.status === "processing" && <Badge size="xs" color="blue" variant="light" leftSection={<Loader2 size={10} className="animate-spin" />}>ประมวลผล</Badge>}
              </Group>
            </div>
          </Group>
          <Group gap={2} wrap="nowrap">
            <ActionIcon variant="subtle" onClick={() => setReextractModalOpen(true)} disabled={isProcessing}>
              <RotateCcw size={16} />
            </ActionIcon>
            <ActionIcon variant="subtle" color="red" onClick={() => setDeleteModalOpen(true)}>
              <Trash2 size={16} />
            </ActionIcon>
          </Group>
        </Group>
      </div>

      {/* Mobile tab switcher */}
      <Tabs value={mobileTab} onChange={(v) => setMobileTab(v as "doc" | "form")}>
        <Tabs.List grow>
          <Tabs.Tab value="doc">เอกสาร</Tabs.Tab>
          <Tabs.Tab value="form">ข้อมูล</Tabs.Tab>
        </Tabs.List>
      </Tabs>

      {/* Hero status card (fraud detail merged in) */}
      {heroSection && <div className="px-3 pt-2">{heroSection}</div>}

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {mobileTab === "doc" && <div className="p-3">{imageSection}</div>}
        {mobileTab === "form" && <div className="p-4">{formSection}</div>}
      </div>

      {/* Sticky bottom actions */}
      <div className="sticky bottom-0 z-20 px-4 py-3 flex gap-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))]" style={{ background: "var(--mantine-color-body)", borderTop: "1px solid var(--mantine-color-default-border)" }}>
        {mobileTab === "form" && (
          <Button className="flex-1" onClick={handleSaveHeader} disabled={saving || isProcessing} leftSection={saving ? <Loader size="xs" /> : <Save size={16} />}>
            บันทึก
          </Button>
        )}
        {doc.status === "extracted" && (
          <Button color="green" className="flex-1" onClick={handleApprove} leftSection={<CheckCircle2 size={16} />}>
            อนุมัติ
          </Button>
        )}
        {mobileTab === "doc" && doc.status !== "extracted" && (
          <Button variant="outline" className="flex-1" onClick={() => setMobileTab("form")}>
            ดูข้อมูลที่ดึงได้
          </Button>
        )}
      </div>

      {modals}
    </div>
  );

  // ============================================
  // DESKTOP LAYOUT
  // ============================================
  const desktopLayout = (
    <div
      className="hidden lg:flex flex-col"
      style={{
        height:
          "calc(100vh - var(--app-shell-header-offset) - 2 * var(--app-shell-padding))",
      }}
    >
      {/* Top bar */}
      <Group justify="space-between" mb="md">
        <Group gap="md">
          <ActionIcon variant="subtle" size="lg" onClick={handleBack}>
            <ArrowLeft size={20} />
          </ActionIcon>
          <div>
            <Title order={3}>{doc.filename}</Title>
            <Text size="sm" c="dimmed" mt={4}>
              อัปโหลด {new Date(doc.uploaded_at).toLocaleString("th-TH")}
            </Text>
          </div>
        </Group>
        <Group gap="sm">
          <Button variant="subtle" size="sm" leftSection={<RotateCcw size={14} />} onClick={() => setReextractModalOpen(true)} disabled={isProcessing}>
            ประมวลผลใหม่
          </Button>
          {doc.status === "extracted" && (
            <Button color="green" leftSection={<CheckCircle2 size={16} />} onClick={handleApprove}>อนุมัติ</Button>
          )}
          <ActionIcon variant="subtle" color="red" size="lg" onClick={() => setDeleteModalOpen(true)}>
            <Trash2 size={18} />
          </ActionIcon>
        </Group>
      </Group>

      {/* 2-column layout: document (full-height, left) + info (scrollable, right) */}
      <div className="flex-1 grid grid-cols-[2fr_3fr] gap-6 min-h-0">
        <Paper
          withBorder
          p="md"
          className="overflow-hidden"
          style={{ display: "flex", flexDirection: "column" }}
        >
          <div className="flex-1 min-h-0">
            {doc.file_type === "pdf" ? (
              <iframe
                src={getDocumentImageUrl(doc.id)}
                className="w-full h-full rounded-lg"
                title="PDF"
              />
            ) : (
              <div className="h-full rounded-lg overflow-hidden">
                <ImageCanvas
                  src={getDocumentImageUrl(doc.id)}
                  alt={doc.filename}
                  downloadFilename={doc.filename}
                />
              </div>
            )}
          </div>
        </Paper>
        <Paper
          withBorder
          className="overflow-hidden"
          style={{ display: "flex", flexDirection: "column" }}
        >
          <Group
            justify="space-between"
            p="md"
            style={{
              background: "var(--mantine-color-body)",
              borderBottom: "1px solid var(--mantine-color-default-border)",
            }}
          >
            <Group gap="xs" align="baseline">
              <Text fw={600}>ข้อมูลที่ดึงได้</Text>
              {doc.confidence != null && (
                <Text
                  size="xs"
                  c={confColor === "red" ? "red.7" : "dimmed"}
                >
                  AI อ่านได้ {Math.round(doc.confidence * 100)}%
                </Text>
              )}
            </Group>
            <Button size="sm" onClick={handleSaveHeader} disabled={saving || isProcessing} leftSection={saving ? <Loader size="xs" /> : <Save size={14} />}>
              บันทึก
            </Button>
          </Group>
          <div className="flex-1 overflow-auto p-4">
            <Stack gap="md">
              {heroSection}
              {formSection}
            </Stack>
          </div>
        </Paper>
      </div>

      {modals}
    </div>
  );

  return (
    <>
      {mobileLayout}
      {desktopLayout}
    </>
  );
}

function ItemRow({
  item,
  onSave,
  onDelete,
  suggestions,
}: {
  item: DocumentItemData;
  onSave: (item: DocumentItemData, field: string, value: string) => void;
  onDelete: (item: DocumentItemData) => void;
  suggestions: string[];
}) {
  const [values, setValues] = useState({
    product_name_normalized: item.product_name_normalized ?? "",
    quantity: item.quantity ?? "",
    unit: item.unit ?? "",
    unit_price: item.unit_price ?? "",
    line_total: item.line_total ?? "",
  });

  useEffect(() => {
    setValues({
      product_name_normalized: item.product_name_normalized ?? "",
      quantity: item.quantity ?? "",
      unit: item.unit ?? "",
      unit_price: item.unit_price ?? "",
      line_total: item.line_total ?? "",
    });
  }, [item]);

  const handleChange = (field: string, val: string) => {
    const next = { ...values, [field]: val };
    if (field === "quantity" || field === "unit_price") {
      const qty = Number(field === "quantity" ? val : next.quantity) || 0;
      const price = Number(field === "unit_price" ? val : next.unit_price) || 0;
      if (qty > 0 && price > 0) next.line_total = (qty * price).toFixed(2);
    }
    setValues(next);
  };

  const handleBlur = (field: string) => {
    onSave(item, field, String(values[field as keyof typeof values]));
    if ((field === "quantity" || field === "unit_price") && values.line_total !== "") {
      onSave(item, "line_total", String(values.line_total));
    }
  };

  return (
    <Table.Tr>
      <Table.Td p={4}>
        <Group gap={6} wrap="nowrap" align="center">
          <Tooltip
            label={
              item.product_code
                ? `อยู่ใน catalog (SKU ${item.product_code})`
                : "ไม่อยู่ใน catalog"
            }
            withinPortal
          >
            {item.product_code ? (
              <PackageCheck size={14} style={{ color: "var(--mantine-color-green-6)", flexShrink: 0 }} />
            ) : (
              <CircleDashed size={14} style={{ color: "var(--mantine-color-gray-5)", flexShrink: 0 }} />
            )}
          </Tooltip>
          <Autocomplete
            size="xs"
            variant="unstyled"
            value={values.product_name_normalized}
            onChange={(v) => handleChange("product_name_normalized", v)}
            onBlur={() => handleBlur("product_name_normalized")}
            data={suggestions}
            limit={8}
            comboboxProps={{ withinPortal: true }}
            title={
              item.product_name_raw && item.product_name_raw !== values.product_name_normalized
                ? `AI อ่านได้: ${item.product_name_raw}`
                : undefined
            }
            style={{ flex: 1 }}
            styles={{
              input: {
                padding: "2px 6px",
                border: "1px solid transparent",
                borderRadius: 4,
              },
            }}
          />
        </Group>
      </Table.Td>
      <Table.Td p={4}>
        <NumberInput
          size="xs"
          variant="unstyled"
          hideControls
          value={values.quantity === "" ? "" : Number(values.quantity)}
          onChange={(v) => handleChange("quantity", String(v))}
          onBlur={() => handleBlur("quantity")}
          styles={{ input: { textAlign: "right", padding: "2px 6px", border: "1px solid transparent", borderRadius: 4 } }}
        />
      </Table.Td>
      <Table.Td p={4}>
        <TextInput
          size="xs"
          variant="unstyled"
          value={values.unit}
          onChange={(e) => handleChange("unit", e.currentTarget.value)}
          onBlur={() => handleBlur("unit")}
          styles={{ input: { padding: "2px 6px", border: "1px solid transparent", borderRadius: 4 } }}
        />
      </Table.Td>
      <Table.Td p={4}>
        <NumberInput
          size="xs"
          variant="unstyled"
          thousandSeparator=","
          decimalScale={2}
          hideControls
          value={values.unit_price === "" ? "" : Number(values.unit_price)}
          onChange={(v) => handleChange("unit_price", String(v))}
          onBlur={() => handleBlur("unit_price")}
          styles={{ input: { textAlign: "right", padding: "2px 6px", border: "1px solid transparent", borderRadius: 4 } }}
        />
      </Table.Td>
      <Table.Td p={4}>
        <NumberInput
          size="xs"
          variant="unstyled"
          thousandSeparator=","
          decimalScale={2}
          hideControls
          value={values.line_total === "" ? "" : Number(values.line_total)}
          onChange={(v) => handleChange("line_total", String(v))}
          onBlur={() => handleBlur("line_total")}
          styles={{ input: { textAlign: "right", fontWeight: 500, padding: "2px 6px", border: "1px solid transparent", borderRadius: 4 } }}
        />
      </Table.Td>
      <Table.Td p={4} ta="center">
        <ActionIcon
          size="xs"
          variant="subtle"
          color="red"
          onClick={() => onDelete(item)}
          title="ลบรายการ"
        >
          <Trash2 size={14} />
        </ActionIcon>
      </Table.Td>
    </Table.Tr>
  );
}

const fmtBaht = (n: number | null | undefined): string => {
  if (n == null) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

function AmountField({
  label,
  value,
  onChange,
  disabled,
  warning,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  disabled?: boolean;
  warning?: string;
}) {
  const hasWarning = !!warning;
  return (
    <NumberInput
      label={label}
      prefix="฿ "
      thousandSeparator=","
      decimalScale={2}
      value={value ?? ""}
      onChange={(v) => onChange(v === "" ? null : Number(v))}
      disabled={disabled}
      hideControls
      rightSection={
        hasWarning ? (
          <AlertTriangle
            size={14}
            style={{ color: "var(--mantine-color-orange-6)" }}
          />
        ) : undefined
      }
      error={warning}
      styles={{
        input: hasWarning
          ? { borderColor: "var(--mantine-color-orange-5)" }
          : undefined,
        error: { color: "var(--mantine-color-orange-7)" },
      }}
    />
  );
}
