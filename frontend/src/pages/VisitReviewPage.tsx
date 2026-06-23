import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Autocomplete,
  Badge,
  Button,
  Group,
  Loader,
  NumberInput,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarX,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  HelpCircle,
  Plus,
  Store as StoreIcon,
  Trash2,
} from "lucide-react";
import {
  getAutocomplete,
  getDocumentImageUrl,
  type DocumentItemData,
  type DocumentResponse,
} from "../api/client";
import {
  useApproveDocument,
  useCreateItem,
  useDeleteItem,
  useDocument,
  useStores,
  useUpdateDocument,
  useUpdateItem,
  useVisit,
} from "../api/queries";
import { useToast } from "@/components/Toast";
import { ImageCanvas } from "@/components/ImageCanvas";
import { ConfidenceBadge, lineConfidenceMeta } from "@/components/ConfidenceBadge";

const STATUS_LABEL: Record<string, { color: string; label: string }> = {
  pending: { color: "gray", label: "รอ" },
  processing: { color: "blue", label: "ประมวลผล" },
  extracted: { color: "yellow", label: "ดึงข้อมูลแล้ว" },
  reviewed: { color: "green", label: "ตรวจแล้ว" },
  error: { color: "red", label: "ผิดพลาด" },
};

export default function VisitReviewPage() {
  const { visitId, docId } = useParams<{ visitId: string; docId: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: visit } = useVisit(visitId);
  const { data: doc, isPending: docLoading } = useDocument(docId);
  const approveMut = useApproveDocument();

  const docs = visit?.documents ?? [];
  const currentIndex = docs.findIndex((d) => d.id === docId);
  const currentSummary = currentIndex >= 0 ? docs[currentIndex] : null;
  const prevDoc = currentIndex > 0 ? docs[currentIndex - 1] : null;
  const nextDoc =
    currentIndex >= 0 && currentIndex < docs.length - 1
      ? docs[currentIndex + 1]
      : null;

  const goPrev = () =>
    prevDoc && navigate(`/visits/${visitId}/review/${prevDoc.id}`);
  const goNext = () =>
    nextDoc && navigate(`/visits/${visitId}/review/${nextDoc.id}`);
  const goBack = () => navigate(`/visits/${visitId}`);

  // Keyboard nav for fast review
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "ArrowLeft" && prevDoc) goPrev();
      if (e.key === "ArrowRight" && nextDoc) goNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [prevDoc?.id, nextDoc?.id]);

  if (docLoading || !doc || !visit) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader size="lg" />
      </div>
    );
  }

  const isProcessing = doc.status === "processing" || doc.status === "pending";
  const reviewed = doc.status === "reviewed";

  if (isProcessing) {
    return (
      <div className="max-w-md mx-auto mt-12 text-center">
        <Loader size="lg" className="mb-md" />
        <Title order={4} mt="md">AI กำลังประมวลผลใบเสร็จนี้</Title>
        <Text c="dimmed" mt="xs" mb="lg">
          {doc.filename} — รอสักครู่แล้วเปิดใหม่ หรือกดกลับไปดูใบอื่นก่อน
        </Text>
        <Button
          variant="default"
          leftSection={<ArrowLeft size={14} />}
          onClick={goBack}
        >
          กลับเดือน {visit.report_period ?? ""}
        </Button>
      </div>
    );
  }

  const handleApprove = async () => {
    try {
      await approveMut.mutateAsync(doc.id);
      toast("success", "บันทึกว่าตรวจสอบแล้ว");
      // Advance automatically if there's a next doc; otherwise go back to visit page.
      if (nextDoc) {
        navigate(`/visits/${visitId}/review/${nextDoc.id}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "บันทึกไม่สำเร็จ";
      toast("error", msg);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-90px)]">
      {/* Top bar */}
      <Group justify="space-between" mb="md" wrap="nowrap" align="flex-start">
        <div className="min-w-0">
          <Button
            variant="default"
            size="xs"
            leftSection={<ArrowLeft size={14} />}
            onClick={goBack}
            mb="xs"
          >
            กลับเดือน {visit.report_period ?? ""}
          </Button>
          <Group gap="xs" wrap="nowrap">
            <Text fw={600} truncate>
              {visit.store_label || visit.store_key || "(ไม่ระบุร้าน)"}
            </Text>
            {visit.report_period && (
              <Badge variant="light" color="grape">
                {visit.report_period}
              </Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed" truncate>
            {doc.filename}
          </Text>
        </div>
        <Group gap="xs" wrap="nowrap">
          <Button
            variant="default"
            size="sm"
            leftSection={<ChevronLeft size={14} />}
            onClick={goPrev}
            disabled={!prevDoc}
          >
            ก่อนหน้า
          </Button>
          <Text size="sm" c="dimmed" px="xs">
            {currentIndex + 1} / {docs.length}
          </Text>
          <Button
            variant="default"
            size="sm"
            rightSection={<ChevronRight size={14} />}
            onClick={goNext}
            disabled={!nextDoc}
          >
            ถัดไป
          </Button>
          {reviewed ? (
            <Badge color="green" size="lg" leftSection={<CheckCircle2 size={14} />}>
              ตรวจสอบแล้ว
            </Badge>
          ) : (
            <Button
              color="green"
              leftSection={<CheckCircle2 size={16} />}
              onClick={handleApprove}
              loading={approveMut.isPending}
            >
              บันทึกว่าตรวจสอบแล้ว
            </Button>
          )}
        </Group>
      </Group>

      {/* Mismatch warnings — backend flags surface here so the reviewer
          sees them while they have the receipt image open, not just on the
          visit summary. */}
      {currentSummary?.store_mismatch && (
        <Alert
          icon={<StoreIcon size={18} />}
          color="red"
          variant="light"
          mb="sm"
          title="ใบเสร็จคนละร้านกับ visit นี้"
        >
          <Text size="sm">
            ใบเสร็จมาจากร้าน{" "}
            <Text span fw={700}>
              {doc.merchant_name || doc.merchant_normalized || "(ไม่ระบุ)"}
            </Text>
            {" "}แต่ visit ตั้งเป็นร้าน{" "}
            <Text span fw={700}>
              {visit.store_label || visit.store_key}
            </Text>
            {" "}— ย้ายใบนี้ออก หรือยืนยันว่าใบนี้อยู่ visit ถูกต้อง
          </Text>
        </Alert>
      )}
      {currentSummary?.period_mismatch && (
        <Alert
          icon={<CalendarX size={18} />}
          color="orange"
          variant="light"
          mb="sm"
          title="วันที่บนใบเสร็จอยู่นอกเดือนของ visit"
        >
          <Text size="sm">
            ใบเสร็จลงวันที่{" "}
            <Text span fw={700}>
              {doc.document_date}
            </Text>
            {" "}แต่ visit นี้รายงานเดือน{" "}
            <Text span fw={700}>
              {visit.report_period}
            </Text>
            {" "}— ตรวจสอบว่าใบนี้ควรอยู่เดือนถูก
          </Text>
        </Alert>
      )}
      {currentSummary?.needs_review
        && !currentSummary?.period_mismatch
        && !currentSummary?.store_mismatch && (
        <Alert
          icon={<Eye size={18} />}
          color="yellow"
          variant="light"
          mb="sm"
          title="เอกสารนี้ต้องตรวจ"
        >
          <Text size="sm">
            AI อ่านเสร็จแล้วแต่มีสินค้าอย่างน้อย 1 รายการที่ไม่ตรงกับ catalog — ดูว่า
            ควรเพิ่ม SKU ใหม่หรือแก้ชื่อสินค้าให้ตรง catalog
          </Text>
        </Alert>
      )}

      {/* 2-column layout */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-4 min-h-0">
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
          <div
            style={{
              background: "var(--mantine-color-body)",
              borderBottom: "1px solid var(--mantine-color-default-border)",
            }}
          >
            <Group justify="space-between" p="md" pb="xs">
              <Group gap="xs">
                <Text fw={600}>รายการสินค้า ({doc.items.length})</Text>
                {doc.confidence != null && (
                  <Tooltip
                    label="คะแนนที่ AI ประเมินความชัดของทั้งใบเอง — คนละตัวกับแถบความตรงราย
บรรทัด (ที่ระบบคำนวณเทียบกับ catalog)"
                    multiline
                    w={250}
                    withArrow
                  >
                    <Text size="xs" c="dimmed">
                      AI ประเมินทั้งใบ {(doc.confidence * 100).toFixed(0)}%
                    </Text>
                  </Tooltip>
                )}
                <Badge size="sm" color={STATUS_LABEL[doc.status]?.color || "gray"} variant="light">
                  {STATUS_LABEL[doc.status]?.label || doc.status}
                </Badge>
              </Group>
            </Group>
            <DocHeaderEditor
              doc={doc}
              currentVisitId={visit.id}
              onVisitChange={(newId) =>
                navigate(`/visits/${newId}/review/${doc.id}`, { replace: true })
              }
            />
          </div>
          <div className="flex-1 overflow-auto">
            <ItemsTable docId={doc.id} items={doc.items} />
          </div>
        </Paper>
      </div>
    </div>
  );
}

/**
 * Editable header for the doc under review.
 *
 * The merchant + date are not just display — they decide which Visit this
 * receipt belongs to. Saving either triggers the backend to reattach the doc
 * to the correct ``(store × month)`` Visit; if the visit_id moves, the parent
 * navigates to the new visit so subsequent navigation stays consistent.
 */
function DocHeaderEditor({
  doc,
  currentVisitId,
  onVisitChange,
}: {
  doc: DocumentResponse;
  currentVisitId: string;
  onVisitChange: (newVisitId: string) => void;
}) {
  const { toast } = useToast();
  const updateMut = useUpdateDocument(doc.id);
  const stores = useStores();
  const [merchant, setMerchant] = useState(doc.merchant_name ?? "");
  const [date, setDate] = useState(doc.document_date ?? "");

  useEffect(() => {
    setMerchant(doc.merchant_name ?? "");
    setDate(doc.document_date ?? "");
  }, [doc.id, doc.merchant_name, doc.document_date]);

  const save = async (data: Record<string, unknown>) => {
    try {
      const next = await updateMut.mutateAsync(data);
      if (next.visit_id && next.visit_id !== currentVisitId) {
        toast(
          "success",
          `ใบเสร็จนี้ถูกย้ายไป visit ใหม่แล้ว (ตามชื่อร้าน/วันที่ที่แก้)`,
        );
        onVisitChange(next.visit_id);
      }
    } catch (e: unknown) {
      toast("error", e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    }
  };

  const merchantSuggestions = stores.data?.map((s) => s.name) ?? [];

  return (
    <Group p="md" pt={0} gap="md" wrap="wrap" align="flex-end">
      <div style={{ flex: 1, minWidth: 220 }}>
        <Text size="xs" c="dimmed" mb={2}>
          ร้านบนใบเสร็จ
        </Text>
        <Autocomplete
          size="sm"
          value={merchant}
          onChange={setMerchant}
          data={merchantSuggestions}
          placeholder="ชื่อร้าน"
          onBlur={() => {
            if (merchant !== (doc.merchant_name ?? "")) {
              save({ merchant_name: merchant });
            }
          }}
          limit={10}
        />
      </div>
      <div style={{ width: 160 }}>
        <Text size="xs" c="dimmed" mb={2}>
          วันที่บนใบเสร็จ
        </Text>
        <TextInput
          size="sm"
          value={date}
          onChange={(e) => setDate(e.currentTarget.value)}
          placeholder="YYYY-MM-DD"
          onBlur={() => {
            const next = date.trim() || null;
            if (next !== (doc.document_date ?? null)) {
              save({ document_date: next });
            }
          }}
        />
      </div>
      {updateMut.isPending && <Loader size="xs" />}
    </Group>
  );
}

function ItemsTable({
  docId,
  items,
}: {
  docId: string;
  items: DocumentItemData[];
}) {
  const updateMut = useUpdateItem(docId);
  const deleteMut = useDeleteItem(docId);
  const createMut = useCreateItem(docId);
  const { toast } = useToast();

  const matchedCount = items.filter((i) => i.product_code).length;
  const unknownCount = items.length - matchedCount;

  const handleSave = async (itemId: string, data: Record<string, unknown>) => {
    try {
      await updateMut.mutateAsync({ itemId, data });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "บันทึกล้มเหลว";
      toast("error", msg);
    }
  };

  const handleDelete = async (itemId: string) => {
    try {
      await deleteMut.mutateAsync(itemId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "ลบล้มเหลว";
      toast("error", msg);
    }
  };

  const handleAdd = async () => {
    try {
      await createMut.mutateAsync({
        product_name_normalized: "(สินค้าใหม่)",
        quantity: 1,
        unit: "ขวด",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "เพิ่มล้มเหลว";
      toast("error", msg);
    }
  };

  return (
    <div>
      <Group justify="space-between" px="md" pt="sm">
        <Group gap="xs">
          {matchedCount > 0 && (
            <Badge size="sm" color="green" variant="light" leftSection={<CheckCircle2 size={10} />}>
              {matchedCount} matched
            </Badge>
          )}
          {unknownCount > 0 && (
            <Badge size="sm" color="orange" variant="light" leftSection={<HelpCircle size={10} />}>
              {unknownCount} unknown
            </Badge>
          )}
        </Group>
        <Button
          size="xs"
          variant="light"
          leftSection={<Plus size={14} />}
          onClick={handleAdd}
          loading={createMut.isPending}
        >
          เพิ่มสินค้า
        </Button>
      </Group>
      <Table verticalSpacing="sm" striped highlightOnHover stickyHeader>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={28}></Table.Th>
            <Table.Th>สินค้า</Table.Th>
            <Table.Th w={100} ta="right">จำนวน</Table.Th>
            <Table.Th w={90}>หน่วย</Table.Th>
            <Table.Th w={36}></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.length === 0 ? (
            <Table.Tr>
              <Table.Td colSpan={5}>
                <Text c="dimmed" ta="center" py="lg">
                  ยังไม่มีรายการ — กด "เพิ่มสินค้า"
                </Text>
              </Table.Td>
            </Table.Tr>
          ) : (
            items.map((it) => (
              <ItemRow
                key={it.id}
                item={it}
                onSave={(data) => handleSave(it.id, data)}
                onDelete={() => handleDelete(it.id)}
              />
            ))
          )}
        </Table.Tbody>
      </Table>
    </div>
  );
}

function ItemRow({
  item,
  onSave,
  onDelete,
}: {
  item: DocumentItemData;
  onSave: (data: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(item.product_name_normalized ?? "");
  const [qty, setQty] = useState<number | string>(item.quantity ?? "");
  const [unit, setUnit] = useState(item.unit ?? "");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  useEffect(() => {
    setName(item.product_name_normalized ?? "");
    setQty(item.quantity ?? "");
    setUnit(item.unit ?? "");
  }, [item]);

  // Live catalog suggestions while typing.
  useEffect(() => {
    const q = name.trim();
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      getAutocomplete("product", q, 8)
        .then((opts) => {
          if (!cancelled) setSuggestions(opts.map((o) => o.value));
        })
        .catch(() => {});
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [name]);

  const matched = !!item.product_code;
  const conf = lineConfidenceMeta(item);

  const numOrNull = (v: number | string) =>
    typeof v === "string" && v === "" ? null : Number(v);

  return (
    <Table.Tr
      style={{
        background: conf.tint,
        boxShadow: conf.flag ? `inset 3px 0 0 ${conf.color}` : undefined,
      }}
    >
      <Table.Td ta="center">
        {matched ? (
          <Tooltip label={`SKU ${item.product_code}`}>
            <CheckCircle2 size={16} className="text-green-600" />
          </Tooltip>
        ) : (
          <Tooltip label="ยังไม่ match catalog — แก้ชื่อให้ตรง SKU ถ้าทำได้">
            <HelpCircle size={16} className="text-orange-500" />
          </Tooltip>
        )}
      </Table.Td>
      <Table.Td>
        <Autocomplete
          size="sm"
          variant="unstyled"
          value={name}
          onChange={setName}
          data={suggestions}
          onBlur={() => {
            if (name !== (item.product_name_normalized ?? "")) {
              onSave({ product_name_normalized: name });
            }
          }}
          limit={8}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
          <ConfidenceBadge item={item} />
          {item.product_name_raw && item.product_name_raw !== item.product_name_normalized && (
            <Text size="xs" c="dimmed">raw: {item.product_name_raw}</Text>
          )}
        </div>
      </Table.Td>
      <Table.Td>
        <NumberInput
          size="sm"
          variant="unstyled"
          value={qty}
          min={0}
          decimalScale={3}
          hideControls
          styles={{ input: { textAlign: "right" } }}
          onChange={(v) => setQty(v as number | string)}
          onBlur={() => {
            const next = numOrNull(qty);
            if (next !== item.quantity) onSave({ quantity: next });
          }}
        />
      </Table.Td>
      <Table.Td>
        <TextInput
          size="sm"
          variant="unstyled"
          value={unit}
          onChange={(e) => setUnit(e.currentTarget.value)}
          onBlur={() => {
            if (unit !== (item.unit ?? "")) onSave({ unit });
          }}
        />
      </Table.Td>
      <Table.Td>
        <ActionIcon
          color="red"
          variant="subtle"
          size="sm"
          onClick={onDelete}
          aria-label="ลบรายการ"
        >
          <Trash2 size={14} />
        </ActionIcon>
      </Table.Td>
    </Table.Tr>
  );
}
