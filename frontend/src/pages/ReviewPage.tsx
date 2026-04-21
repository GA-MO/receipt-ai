import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Loader2,
  PackageCheck,
  Plus,
  RotateCcw,
  Save,
  ShieldAlert,
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
import { parseFraudData, riskScoreColor, riskScoreLabel } from "@/lib/fraud";
import { validateTotals } from "@/lib/validation";
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

  const handleSaveItem = async (item: DocumentItemData, field: string, value: string) => {
    if (!id) return;
    const numFields = ["quantity", "unit_price", "line_total"];
    const val = numFields.includes(field)
      ? value === "" ? null : Number(value)
      : value;
    try {
      await updateItemMut.mutateAsync({ itemId: item.id, data: { [field]: val } });
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
  const hasRisk = fraudFlags.length > 0 || (aiAnalysis && aiAnalysis.risk_score >= 0.3);

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

  const fraudSection = hasRisk && (
    <Paper withBorder p="md" radius="md" style={{ borderColor: "var(--mantine-color-red-4)" }}>
      <Stack gap="sm">
        {aiAnalysis && (
          <Group justify="space-between" align="center">
            <Group gap="xs">
              <ShieldAlert size={18} />
              <Text fw={700} size="sm">AI Fraud Analysis</Text>
            </Group>
            <Badge
              color={riskScoreColor(aiAnalysis.risk_score)}
              variant="filled"
              size="lg"
            >
              Risk: {(aiAnalysis.risk_score * 100).toFixed(0)}% — {riskScoreLabel(aiAnalysis.risk_score)}
            </Badge>
          </Group>
        )}

        {aiAnalysis?.summary && (
          <Alert color={riskScoreColor(aiAnalysis.risk_score)} variant="light" icon={<ShieldAlert size={16} />}>
            <Text size="sm">{aiAnalysis.summary}</Text>
          </Alert>
        )}

        {fraudFlags.length > 0 && (
          <Stack gap={4}>
            <Text size="xs" c="dimmed" fw={600} tt="uppercase">
              รายการที่ตรวจพบ ({fraudFlags.length})
            </Text>
            {fraudFlags.map((flag, i) => (
              <Paper key={i} withBorder p="xs" radius="sm" style={{
                borderLeftWidth: 3,
                borderLeftColor: `var(--mantine-color-${SEVERITY_COLOR[flag.severity] || "gray"}-5)`,
              }}>
                <Group gap="xs" wrap="nowrap">
                  <Badge color={SEVERITY_COLOR[flag.severity] || "gray"} variant="filled" size="xs" style={{ flexShrink: 0 }}>
                    {flag.severity === "high" ? "สูง" : flag.severity === "medium" ? "กลาง" : "ต่ำ"}
                  </Badge>
                  <div>
                    <Text size="xs" fw={600}>{flag.label}</Text>
                    <Text size="xs" c="dimmed">{flag.detail}</Text>
                  </div>
                </Group>
              </Paper>
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

  const formSection = (
    <Stack gap="md">
      {validationIssues.length > 0 && (
        <Stack gap={6}>
          {validationIssues.map((issue, i) => (
            <Alert
              key={i}
              color={issue.severity === "error" ? "red" : "yellow"}
              icon={<AlertTriangle size={16} />}
              py="xs"
              variant="light"
            >
              <Text size="xs">{issue.message}</Text>
            </Alert>
          ))}
        </Stack>
      )}
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
        <NumberInput
          label="ยอดก่อนภาษี"
          prefix="฿"
          thousandSeparator=","
          decimalScale={2}
          value={form.subtotal ?? ""}
          onChange={(v) => setForm({ ...form, subtotal: v === "" ? null : Number(v) })}
          disabled={isProcessing}
          error={itemsIssue ? "ไม่ตรงกับผลรวมสินค้า" : undefined}
        />
        <NumberInput
          label="ส่วนลด"
          prefix="฿"
          thousandSeparator=","
          decimalScale={2}
          value={form.discount ?? ""}
          onChange={(v) => setForm({ ...form, discount: v === "" ? null : Number(v) })}
          disabled={isProcessing}
        />
        <NumberInput
          label="VAT"
          prefix="฿"
          thousandSeparator=","
          decimalScale={2}
          value={form.vat ?? ""}
          onChange={(v) => setForm({ ...form, vat: v === "" ? null : Number(v) })}
          disabled={isProcessing}
          error={vatIssue ? "VAT ไม่ใช่ 7%" : undefined}
        />
        <div className="col-span-2">
          <NumberInput
            label="ยอดรวมสุทธิ"
            prefix="฿"
            thousandSeparator=","
            decimalScale={2}
            value={form.grand_total ?? ""}
            onChange={(v) => setForm({ ...form, grand_total: v === "" ? null : Number(v) })}
            disabled={isProcessing}
            size="lg"
            styles={{ input: { fontWeight: 600 } }}
            error={totalsIssue ? "ยอดรวมไม่ตรง" : undefined}
          />
        </div>
      </div>

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
            <ActionIcon variant="subtle" onClick={() => navigate("/documents")}>
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

      {/* Banners */}
      {isProcessing && (
        <Alert color="blue" icon={<Loader2 size={16} className="animate-spin" />} py="xs" mx="sm" mt="sm">
          <Text size="sm">AI กำลังประมวลผล...</Text>
        </Alert>
      )}
      {doc.error_message && (
        <Alert color="red" icon={<AlertTriangle size={16} />} py="xs" mx="sm" mt="sm">
          <Text size="sm">{doc.error_message}</Text>
        </Alert>
      )}
      {fraudSection && <div className="px-3 pt-2">{fraudSection}</div>}

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
    <div className="hidden lg:flex flex-col h-full p-6">
      {/* Top bar */}
      <Group justify="space-between" mb="md">
        <Group gap="md">
          <ActionIcon variant="subtle" size="lg" onClick={() => navigate("/documents")}>
            <ArrowLeft size={20} />
          </ActionIcon>
          <div>
            <Title order={3}>{doc.filename}</Title>
            <Group gap="xs" mt={2}>
              <Text size="sm" c="dimmed">{new Date(doc.uploaded_at).toLocaleString("th-TH")}</Text>
              {doc.confidence != null && <Badge color={confColor} variant="light">Confidence: {(doc.confidence * 100).toFixed(0)}%</Badge>}
              {doc.status === "reviewed" && <Badge color="green" variant="light" leftSection={<CheckCircle2 size={12} />}>ตรวจสอบแล้ว</Badge>}
              {doc.status === "extracted" && <Badge color="yellow" variant="light">รอตรวจสอบ</Badge>}
              {doc.status === "processing" && <Badge color="blue" variant="light" leftSection={<Loader2 size={12} className="animate-spin" />}>กำลังประมวลผล</Badge>}
              {doc.status === "error" && <Badge color="red" variant="light" leftSection={<AlertTriangle size={12} />}>เกิดข้อผิดพลาด</Badge>}
              {fraudFlags.length > 0 && <Badge color="red" variant="light" leftSection={<ShieldAlert size={12} />}>Fraud: {fraudFlags.length}</Badge>}
            </Group>
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

      {isProcessing && (
        <Alert color="blue" icon={<Loader2 size={18} className="animate-spin" />} mb="md">
          AI กำลังประมวลผลเอกสาร...
        </Alert>
      )}
      {doc.error_message && (
        <Alert color="red" icon={<AlertTriangle size={18} />} mb="md">
          {doc.error_message}
        </Alert>
      )}
      {fraudSection && <div className="mb-4">{fraudSection}</div>}

      {/* 2-column layout */}
      <div className="flex-1 grid grid-cols-2 gap-6 min-h-0">
        <Paper withBorder p="md" className="overflow-auto">
          {imageSection}
        </Paper>
        <Paper withBorder className="overflow-auto flex flex-col">
          <Group justify="space-between" p="md" className="sticky top-0 z-10" style={{ background: "var(--mantine-color-body)", borderBottom: "1px solid var(--mantine-color-default-border)" }}>
            <Text fw={600}>ข้อมูลที่ดึงได้</Text>
            <Button size="sm" onClick={handleSaveHeader} disabled={saving || isProcessing} leftSection={saving ? <Loader size="xs" /> : <Save size={14} />}>
              บันทึก
            </Button>
          </Group>
          <div className="p-4 flex-1">
            {formSection}
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
