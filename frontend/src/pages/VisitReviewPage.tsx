import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ActionIcon,
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
  ArrowLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  Plus,
  Trash2,
} from "lucide-react";
import {
  getAutocomplete,
  getDocumentImageUrl,
  type DocumentItemData,
} from "../api/client";
import {
  useApproveDocument,
  useCreateItem,
  useDeleteItem,
  useDocument,
  useUpdateItem,
  useVisit,
} from "../api/queries";
import { useToast } from "@/components/Toast";
import { ImageCanvas } from "@/components/ImageCanvas";

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

  const reviewed = doc.status === "reviewed";

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
      <Group justify="space-between" mb="md" wrap="nowrap">
        <Group gap="sm" wrap="nowrap" className="min-w-0">
          <ActionIcon variant="default" onClick={goBack} aria-label="ย้อนกลับไป visit">
            <ArrowLeft size={16} />
          </ActionIcon>
          <div className="min-w-0">
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
        </Group>
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
          <Group
            justify="space-between"
            p="md"
            style={{
              background: "var(--mantine-color-body)",
              borderBottom: "1px solid var(--mantine-color-default-border)",
            }}
          >
            <Group gap="xs">
              <Text fw={600}>รายการสินค้า ({doc.items.length})</Text>
              {doc.confidence != null && (
                <Text size="xs" c="dimmed">
                  AI อ่าน {(doc.confidence * 100).toFixed(0)}%
                </Text>
              )}
              <Badge size="sm" color={STATUS_LABEL[doc.status]?.color || "gray"} variant="light">
                {STATUS_LABEL[doc.status]?.label || doc.status}
              </Badge>
            </Group>
            <DocHeaderSummary
              merchant={doc.merchant_name}
              docDate={doc.document_date}
              grandTotal={doc.grand_total}
            />
          </Group>
          <div className="flex-1 overflow-auto">
            <ItemsTable docId={doc.id} items={doc.items} />
          </div>
        </Paper>
      </div>
    </div>
  );
}

function DocHeaderSummary({
  merchant,
  docDate,
  grandTotal,
}: {
  merchant: string | null;
  docDate: string | null;
  grandTotal: number | null;
}) {
  if (!merchant && !docDate && grandTotal == null) return null;
  return (
    <Group gap="md">
      {merchant && (
        <Text size="xs" c="dimmed">
          ร้าน: <b>{merchant}</b>
        </Text>
      )}
      {docDate && (
        <Text size="xs" c="dimmed">
          วันที่: <b>{docDate}</b>
        </Text>
      )}
      {grandTotal != null && (
        <Text size="xs" c="dimmed">
          ยอด: <b>฿{grandTotal.toLocaleString()}</b>
        </Text>
      )}
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
            <Table.Th w={110} ta="right">ราคา/หน่วย</Table.Th>
            <Table.Th w={110} ta="right">รวม</Table.Th>
            <Table.Th w={36}></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.length === 0 ? (
            <Table.Tr>
              <Table.Td colSpan={7}>
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
  const [unitPrice, setUnitPrice] = useState<number | string>(item.unit_price ?? "");
  const [lineTotal, setLineTotal] = useState<number | string>(item.line_total ?? "");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  useEffect(() => {
    setName(item.product_name_normalized ?? "");
    setQty(item.quantity ?? "");
    setUnit(item.unit ?? "");
    setUnitPrice(item.unit_price ?? "");
    setLineTotal(item.line_total ?? "");
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

  const numOrNull = (v: number | string) =>
    typeof v === "string" && v === "" ? null : Number(v);

  return (
    <Table.Tr>
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
        {item.product_name_raw && item.product_name_raw !== item.product_name_normalized && (
          <Text size="xs" c="dimmed">raw: {item.product_name_raw}</Text>
        )}
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
        <NumberInput
          size="sm"
          variant="unstyled"
          value={unitPrice}
          min={0}
          decimalScale={2}
          hideControls
          styles={{ input: { textAlign: "right" } }}
          onChange={(v) => setUnitPrice(v as number | string)}
          onBlur={() => {
            const next = numOrNull(unitPrice);
            if (next !== item.unit_price) onSave({ unit_price: next });
          }}
        />
      </Table.Td>
      <Table.Td>
        <NumberInput
          size="sm"
          variant="unstyled"
          value={lineTotal}
          min={0}
          decimalScale={2}
          hideControls
          styles={{ input: { textAlign: "right" } }}
          onChange={(v) => setLineTotal(v as number | string)}
          onBlur={() => {
            const next = numOrNull(lineTotal);
            if (next !== item.line_total) onSave({ line_total: next });
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
