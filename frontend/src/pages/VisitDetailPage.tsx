import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { format } from "date-fns";
import {
  ActionIcon,
  Autocomplete,
  Badge,
  Button,
  Card,
  Drawer,
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
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  HelpCircle,
  Plus,
  RefreshCw,
  Store,
  Trash2,
  User,
} from "lucide-react";
import { getAutocomplete, getDocumentImageUrl, type DocumentItemData } from "../api/client";
import {
  useApproveDocument,
  useCreateItem,
  useDeleteItem,
  useDocument,
  useRecomputeVisitLabel,
  useUpdateItem,
  useVisit,
} from "../api/queries";
import { useToast } from "@/components/Toast";

const STATUS_LABEL: Record<string, { color: string; label: string }> = {
  pending: { color: "gray", label: "รอ" },
  processing: { color: "blue", label: "ประมวลผล" },
  extracted: { color: "yellow", label: "ดึงข้อมูลแล้ว" },
  reviewed: { color: "green", label: "ตรวจแล้ว" },
  error: { color: "red", label: "ผิดพลาด" },
};

export default function VisitDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: visit, isPending, isFetching, refetch } = useVisit(id);
  const recomputeMut = useRecomputeVisitLabel(id ?? "");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drawerIndex, setDrawerIndex] = useState<number | null>(null);

  // Auto-poll while any doc is still processing — cheap, demo-friendly.
  const stillProcessing = useMemo(
    () => visit?.documents.some((d) => d.status === "processing" || d.status === "pending"),
    [visit?.documents],
  );
  useEffect(() => {
    if (!stillProcessing) return;
    const t = setInterval(() => refetch(), 2000);
    return () => clearInterval(t);
  }, [stillProcessing, refetch]);

  if (isPending) return <Loader />;
  if (!visit) return <Text c="red">ไม่พบ visit</Text>;

  const docs = visit.documents;
  const docsById = new Map(docs.map((d) => [d.id, d]));
  const drawerDoc =
    drawerIndex !== null && drawerIndex >= 0 && drawerIndex < docs.length
      ? docs[drawerIndex]
      : null;
  const openDocById = (docId: string) => {
    const idx = docs.findIndex((d) => d.id === docId);
    if (idx >= 0) setDrawerIndex(idx);
  };

  const totalQty = visit.aggregate.reduce((sum, r) => sum + r.total_quantity, 0);
  const catalogCount = visit.aggregate.filter((r) => r.is_catalog_match).length;
  const unknownCount = visit.aggregate.length - catalogCount;

  const toggleRow = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="max-w-7xl mx-auto">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Group gap="sm">
            <Title order={2}>{visit.store_label || visit.store_key || "(ไม่ระบุร้าน)"}</Title>
            {stillProcessing && <Badge color="blue">กำลังประมวลผล...</Badge>}
          </Group>
          <Group gap="lg" mt={4}>
            {visit.store_key && (
              <Group gap={4}>
                <Store size={14} className="text-gray-500" />
                <Text size="sm" c="dimmed">{visit.store_key}</Text>
              </Group>
            )}
            {visit.rep_name && (
              <Group gap={4}>
                <User size={14} className="text-gray-500" />
                <Text size="sm" c="dimmed">{visit.rep_name}</Text>
              </Group>
            )}
            <Text size="sm" c="dimmed">
              สร้างเมื่อ {format(new Date(visit.created_at), "yyyy-MM-dd HH:mm")}
            </Text>
          </Group>
        </div>
        <Group>
          <Tooltip label="ดึงชื่อร้านจากใบเสร็จที่ extract แล้ว">
            <Button
              variant="default"
              size="xs"
              leftSection={<RefreshCw size={14} />}
              onClick={() => recomputeMut.mutate()}
              loading={recomputeMut.isPending}
            >
              อัปเดตชื่อร้าน
            </Button>
          </Tooltip>
        </Group>
      </Group>

      {/* Summary chips */}
      <Group gap="sm" mb="md">
        <Badge size="lg" variant="light" color="indigo">
          {docs.length} ใบ
        </Badge>
        <Badge
          size="lg"
          variant="light"
          color={
            docs.length === 0
              ? "gray"
              : visit.reviewed_count === docs.length
                ? "green"
                : "yellow"
          }
        >
          ตรวจสอบแล้ว {visit.reviewed_count}/{docs.length}
        </Badge>
        <Badge size="lg" variant="light" color="grape">
          {visit.aggregate.length} สินค้า
        </Badge>
        <Badge size="lg" variant="light" color="teal">
          รวม {totalQty.toFixed(0)} หน่วย
        </Badge>
        {catalogCount > 0 && (
          <Badge size="lg" variant="light" color="green">
            in catalog: {catalogCount}
          </Badge>
        )}
        {unknownCount > 0 && (
          <Badge size="lg" variant="light" color="orange">
            ไม่อยู่ catalog: {unknownCount}
          </Badge>
        )}
        {isFetching && <Loader size="xs" />}
      </Group>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Aggregate table — main pane */}
        <div className="lg:col-span-2">
          <Card withBorder radius="md" p={0}>
            <Group justify="space-between" p="md" pb="sm">
              <Title order={4}>ยอดสินค้ารวม</Title>
              <Text size="xs" c="dimmed">click เพื่อดู docs ที่นับ</Text>
            </Group>
            {visit.aggregate.length === 0 ? (
              <Paper p="lg">
                <Text c="dimmed" ta="center">
                  ยังไม่มีข้อมูลสินค้า — รอการประมวลผลเสร็จ
                </Text>
              </Paper>
            ) : (
              <Table verticalSpacing="xs" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={32}></Table.Th>
                    <Table.Th>สินค้า</Table.Th>
                    <Table.Th>ผู้ผลิต</Table.Th>
                    <Table.Th ta="right">จำนวน</Table.Th>
                    <Table.Th>หน่วย</Table.Th>
                    <Table.Th ta="right">ใบที่มี</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {visit.aggregate.map((row, idx) => {
                    const key = row.product_code || `name:${row.display_name}:${idx}`;
                    const open = expanded.has(key);
                    const mixedUnit = row.units_seen.length > 1;
                    return (
                      <>
                        <Table.Tr key={key} style={{ cursor: "pointer" }} onClick={() => toggleRow(key)}>
                          <Table.Td>
                            <ActionIcon size="xs" variant="subtle">
                              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </ActionIcon>
                          </Table.Td>
                          <Table.Td>
                            <Group gap={6}>
                              <Text fw={500}>{row.display_name}</Text>
                              {!row.is_catalog_match && (
                                <Badge size="xs" color="orange" variant="light">
                                  ไม่อยู่ catalog
                                </Badge>
                              )}
                            </Group>
                            {row.product_code && (
                              <Text size="xs" c="dimmed">SKU {row.product_code}</Text>
                            )}
                          </Table.Td>
                          <Table.Td>
                            {row.manufacturer ? (
                              <Badge
                                size="sm"
                                color={row.manufacturer.toLowerCase() === "boonrawd" ? "indigo" : "gray"}
                                variant="light"
                              >
                                {row.manufacturer}
                              </Badge>
                            ) : (
                              <Text size="sm" c="dimmed">—</Text>
                            )}
                          </Table.Td>
                          <Table.Td ta="right">
                            <Text fw={600}>{row.total_quantity.toFixed(row.total_quantity % 1 ? 2 : 0)}</Text>
                          </Table.Td>
                          <Table.Td>
                            <Group gap={4}>
                              <Text size="sm">{row.unit || "—"}</Text>
                              {mixedUnit && (
                                <Tooltip label={`หน่วยปน: ${row.units_seen.join(", ")}`}>
                                  <AlertTriangle size={14} className="text-orange-500" />
                                </Tooltip>
                              )}
                            </Group>
                          </Table.Td>
                          <Table.Td ta="right">
                            <Badge variant="default">{row.source_count}</Badge>
                          </Table.Td>
                        </Table.Tr>
                        {open && (
                          <Table.Tr>
                            <Table.Td></Table.Td>
                            <Table.Td colSpan={5}>
                              <Stack gap={4} py="xs">
                                {row.source_doc_ids.map((did) => {
                                  const d = docsById.get(did);
                                  if (!d) return null;
                                  return (
                                    <Group key={did} gap="sm" wrap="nowrap">
                                      <FileText size={14} className="text-gray-500 shrink-0" />
                                      <Text
                                        size="sm"
                                        className="flex-1 truncate cursor-pointer hover:underline"
                                        onClick={() => openDocById(did)}
                                      >
                                        {d.filename}
                                      </Text>
                                      <Badge size="xs" color={STATUS_LABEL[d.status]?.color || "gray"}>
                                        {STATUS_LABEL[d.status]?.label || d.status}
                                      </Badge>
                                    </Group>
                                  );
                                })}
                              </Stack>
                            </Table.Td>
                          </Table.Tr>
                        )}
                      </>
                    );
                  })}
                </Table.Tbody>
              </Table>
            )}
          </Card>
        </div>

        {/* Docs side panel */}
        <div>
          <Card withBorder radius="md" p={0}>
            <Group justify="space-between" p="md" pb="sm">
              <Title order={4}>ใบเสร็จในชุดนี้</Title>
              <Text size="xs" c="dimmed">{docs.length} ใบ</Text>
            </Group>
            {docs.length > 0 && (
              <Group p="md" pt={0}>
                <Button
                  fullWidth
                  variant="filled"
                  color="indigo"
                  size="sm"
                  onClick={() => setDrawerIndex(0)}
                >
                  เริ่มไล่ตรวจสอบ ({docs.length} ใบ)
                </Button>
              </Group>
            )}
            <Stack gap={0}>
              {docs.length === 0 && (
                <Text c="dimmed" p="md" ta="center">ยังไม่มีใบเสร็จ</Text>
              )}
              {docs.map((d, idx) => (
                <Paper
                  key={d.id}
                  p="sm"
                  className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 border-t"
                  onClick={() => setDrawerIndex(idx)}
                  style={{ borderRadius: 0 }}
                >
                  <Group justify="space-between" wrap="nowrap">
                    <div className="min-w-0 flex-1">
                      <Text size="sm" fw={500} truncate>
                        {d.filename}
                      </Text>
                      <Group gap="sm" mt={2}>
                        <Text size="xs" c="dimmed">
                          {d.merchant_name || "—"}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {d.item_count} รายการ
                        </Text>
                      </Group>
                    </div>
                    <Badge size="sm" color={STATUS_LABEL[d.status]?.color || "gray"} variant="light">
                      {STATUS_LABEL[d.status]?.label || d.status}
                    </Badge>
                  </Group>
                </Paper>
              ))}
            </Stack>
          </Card>
        </div>
      </div>

      <Drawer
        opened={drawerDoc !== null}
        onClose={() => setDrawerIndex(null)}
        title={
          drawerDoc ? (
            <Group gap="xs" wrap="nowrap">
              <Text size="sm" c="dimmed">
                ใบที่ {(drawerIndex ?? 0) + 1} จาก {docs.length}
              </Text>
              <Text fw={600} truncate>
                {drawerDoc.filename}
              </Text>
            </Group>
          ) : (
            "เอกสาร"
          )
        }
        position="right"
        size="xl"
      >
        {drawerDoc && drawerIndex !== null && (
          <DocumentDrawerContent
            docId={drawerDoc.id}
            index={drawerIndex}
            total={docs.length}
            onPrev={
              drawerIndex > 0 ? () => setDrawerIndex(drawerIndex - 1) : undefined
            }
            onNext={
              drawerIndex < docs.length - 1
                ? () => setDrawerIndex(drawerIndex + 1)
                : undefined
            }
            onClose={() => setDrawerIndex(null)}
          />
        )}
      </Drawer>
    </div>
  );
}

function DocumentImagePreview({ docId }: { docId: string }) {
  const url = getDocumentImageUrl(docId);
  return (
    <Paper withBorder radius="md" className="overflow-hidden">
      <img src={url} alt="receipt" style={{ width: "100%", display: "block" }} />
    </Paper>
  );
}

function DocumentDrawerContent({
  docId,
  index,
  total,
  onPrev,
  onNext,
  onClose,
}: {
  docId: string;
  index: number;
  total: number;
  onPrev?: () => void;
  onNext?: () => void;
  onClose: () => void;
}) {
  const { data: doc, isPending } = useDocument(docId);
  const approveMut = useApproveDocument();
  const { toast } = useToast();
  const reviewed = doc?.status === "reviewed";

  const handleApprove = async () => {
    try {
      await approveMut.mutateAsync(docId);
      toast("success", "บันทึกว่าตรวจสอบแล้ว");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "บันทึกไม่สำเร็จ";
      toast("error", msg);
    }
  };

  if (isPending || !doc) {
    return <Loader />;
  }

  return (
    <Stack>
      {/* Nav strip: prev/next + position */}
      <Group justify="space-between" wrap="nowrap">
        <Button
          variant="default"
          size="xs"
          leftSection={<ChevronLeft size={14} />}
          onClick={onPrev}
          disabled={!onPrev}
        >
          ก่อนหน้า
        </Button>
        <Text size="sm" c="dimmed">
          {index + 1} / {total}
        </Text>
        <Button
          variant="default"
          size="xs"
          rightSection={<ChevronRight size={14} />}
          onClick={onNext}
          disabled={!onNext}
        >
          ถัดไป
        </Button>
      </Group>

      <Group justify="space-between">
        <Group gap="xs">
          <Badge color={STATUS_LABEL[doc.status]?.color || "gray"}>
            {STATUS_LABEL[doc.status]?.label || doc.status}
          </Badge>
          {doc.confidence != null && (
            <Badge variant="default">
              confidence {(doc.confidence * 100).toFixed(0)}%
            </Badge>
          )}
        </Group>
        <Button
          component={Link}
          to={`/documents?search=${doc.id}`}
          variant="subtle"
          size="xs"
          rightSection={<ExternalLink size={14} />}
        >
          ดูในรายการเอกสาร
        </Button>
      </Group>
      <DocumentImagePreview docId={doc.id} />
      <Card withBorder radius="md">
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            ร้านค้า: <b>{doc.merchant_name || "—"}</b>
          </Text>
          {doc.document_date && (
            <Text size="sm" c="dimmed">
              วันที่: <b>{doc.document_date}</b>
            </Text>
          )}
          {doc.grand_total != null && (
            <Text size="sm" c="dimmed">
              ยอดรวม: <b>{doc.grand_total.toLocaleString()} บาท</b>
            </Text>
          )}
        </Stack>
      </Card>
      <EditableItemsTable docId={doc.id} items={doc.items} />

      {/* Sticky-feel action bar at the bottom of the drawer body */}
      <Group justify="space-between" mt="sm">
        <Button variant="subtle" onClick={onClose}>
          ปิด
        </Button>
        {reviewed ? (
          <Group gap="xs">
            <Badge color="green" leftSection={<CheckCircle2 size={14} />}>
              ตรวจสอบแล้ว
            </Badge>
            {onNext && (
              <Button size="sm" onClick={onNext} rightSection={<ChevronRight size={14} />}>
                ใบถัดไป
              </Button>
            )}
          </Group>
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
    </Stack>
  );
}

function EditableItemsTable({
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

  const matchedCount = items.filter((i) => i.product_code).length;
  const unknownCount = items.length - matchedCount;

  return (
    <Card withBorder radius="md" p={0}>
      <Group justify="space-between" p="md" pb="sm">
        <Group gap="xs">
          <Text fw={600}>รายการสินค้า ({items.length})</Text>
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
      <Table verticalSpacing="xs" striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={28}></Table.Th>
            <Table.Th>สินค้า</Table.Th>
            <Table.Th w={90} ta="right">จำนวน</Table.Th>
            <Table.Th w={80}>หน่วย</Table.Th>
            <Table.Th w={36}></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((it) => (
            <EditableItemRow
              key={it.id}
              item={it}
              onSave={(data) => handleSave(it.id, data)}
              onDelete={() => handleDelete(it.id)}
            />
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

function EditableItemRow({
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

  // Keep local state in sync if the row is replaced by a server refetch.
  useEffect(() => {
    setName(item.product_name_normalized ?? "");
    setQty(item.quantity ?? "");
    setUnit(item.unit ?? "");
  }, [item.product_name_normalized, item.quantity, item.unit]);

  // Live-fetch catalog suggestions as the user types. Debounce-light via the
  // server query being cached for 60s in queries.ts.
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
        .catch(() => {
          /* ignore — autocomplete is best-effort */
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [name]);

  const saveIfChanged = (patch: Record<string, unknown>) => {
    onSave(patch);
  };

  const matched = !!item.product_code;

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
          size="xs"
          variant="unstyled"
          value={name}
          onChange={setName}
          data={suggestions}
          onBlur={() => {
            if (name !== (item.product_name_normalized ?? "")) {
              saveIfChanged({ product_name_normalized: name });
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
          size="xs"
          variant="unstyled"
          value={qty}
          min={0}
          decimalScale={3}
          hideControls
          styles={{ input: { textAlign: "right" } }}
          onChange={(v) => setQty(v as number | string)}
          onBlur={() => {
            const next = typeof qty === "string" && qty === "" ? null : Number(qty);
            if (next !== item.quantity) {
              saveIfChanged({ quantity: next });
            }
          }}
        />
      </Table.Td>
      <Table.Td>
        <TextInput
          size="xs"
          variant="unstyled"
          value={unit}
          onChange={(e) => setUnit(e.currentTarget.value)}
          onBlur={() => {
            if (unit !== (item.unit ?? "")) {
              saveIfChanged({ unit });
            }
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
