import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { format } from "date-fns";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileImage,
  FileText,
  RefreshCw,
  Store,
  Trash2,
  Upload as UploadIcon,
  User,
} from "lucide-react";
import { getDocumentImageUrl, uploadDocumentsToVisit } from "../api/client";
import {
  useDeleteDocument,
  useRecomputeVisitLabel,
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
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: visit, isPending, isFetching, refetch } = useVisit(id);
  const recomputeMut = useRecomputeVisitLabel(id ?? "");
  const deleteDocMut = useDeleteDocument();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [uploadOpen, setUploadOpen] = useState(false);

  const handleDeleteDoc = async (docId: string, filename: string) => {
    if (!confirm(`ลบใบเสร็จ "${filename}" ออกจากเดือนนี้?`)) return;
    try {
      await deleteDocMut.mutateAsync(docId);
      toast("success", "ลบใบเสร็จแล้ว");
      refetch();
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "ลบไม่สำเร็จ");
    }
  };

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
  const openReview = (docId: string) =>
    navigate(`/visits/${id}/review/${docId}`);

  const totalQty = visit.aggregate.reduce((sum, r) => sum + r.total_quantity, 0);
  const catalogCount = visit.aggregate.filter((r) => r.is_catalog_match).length;
  const unknownCount = visit.aggregate.length - catalogCount;
  const periodMismatchCount = docs.filter((d) => d.period_mismatch).length;

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
          {visit.store_id && (
            <Button
              variant="subtle"
              size="xs"
              component={Link}
              to={`/stores/${visit.store_id}`}
              leftSection={<ArrowLeft size={12} />}
              px={4}
              mb={2}
            >
              กลับไป {visit.store_label || "ร้าน"}
            </Button>
          )}
          <Group gap="sm">
            <Title order={2}>{visit.store_label || visit.store_key || "(ไม่ระบุร้าน)"}</Title>
            {visit.report_period && (
              <Badge size="lg" variant="light" color="grape">
                {visit.report_period}
              </Badge>
            )}
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
          <Button
            leftSection={<UploadIcon size={14} />}
            onClick={() => setUploadOpen(true)}
          >
            อัปโหลดใบเสร็จเพิ่ม
          </Button>
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
        {periodMismatchCount > 0 && (
          <Badge
            size="lg"
            variant="light"
            color="orange"
            leftSection={<AlertTriangle size={12} />}
          >
            นอกเดือน: {periodMismatchCount}
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
                                        onClick={() => openReview(did)}
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
                  onClick={() => openReview(docs[0].id)}
                >
                  เริ่มไล่ตรวจสอบ ({docs.length} ใบ)
                </Button>
              </Group>
            )}
            <Stack gap={0}>
              {docs.length === 0 && (
                <Text c="dimmed" p="md" ta="center">ยังไม่มีใบเสร็จ</Text>
              )}
              {docs.map((d) => (
                <Paper
                  key={d.id}
                  p="sm"
                  className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 border-t"
                  onClick={() => openReview(d.id)}
                  style={{ borderRadius: 0 }}
                >
                  <Group gap="sm" wrap="nowrap" align="flex-start">
                    {d.file_type === "pdf" ? (
                      <div className="w-12 h-12 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex items-center justify-center shrink-0">
                        <FileText className="w-5 h-5 text-gray-400" />
                      </div>
                    ) : (
                      <img
                        src={getDocumentImageUrl(d.id)}
                        alt=""
                        loading="lazy"
                        className="w-12 h-12 rounded-md border border-gray-200 dark:border-gray-700 object-cover bg-gray-50 dark:bg-gray-800 shrink-0"
                        onError={(e) => {
                          e.currentTarget.style.visibility = "hidden";
                        }}
                      />
                    )}
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
                    <Stack gap={2} align="flex-end">
                      <Group gap={4} wrap="nowrap">
                        <Badge size="sm" color={STATUS_LABEL[d.status]?.color || "gray"} variant="light">
                          {STATUS_LABEL[d.status]?.label || d.status}
                        </Badge>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="red"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteDoc(d.id, d.filename);
                          }}
                          aria-label="ลบใบเสร็จ"
                        >
                          <Trash2 size={12} />
                        </ActionIcon>
                      </Group>
                      {d.period_mismatch && (
                        <Badge
                          size="xs"
                          color="orange"
                          variant="light"
                          leftSection={<AlertTriangle size={10} />}
                        >
                          นอกเดือน
                        </Badge>
                      )}
                    </Stack>
                  </Group>
                </Paper>
              ))}
            </Stack>
          </Card>
        </div>
      </div>

      <UploadMoreModal
        opened={uploadOpen}
        onClose={() => setUploadOpen(false)}
        visitId={visit.id}
        onUploaded={() => refetch()}
      />
    </div>
  );
}

const MAX_FILE_SIZE = 20 * 1024 * 1024;

function UploadMoreModal({
  opened,
  onClose,
  visitId,
  onUploaded,
}: {
  opened: boolean;
  onClose: () => void;
  visitId: string;
  onUploaded: () => void;
}) {
  const { toast } = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);

  const reset = () => setFiles([]);

  const onDrop = useCallback(
    (accepted: File[], rejected: readonly { file: File; errors: readonly { message: string }[] }[]) => {
      for (const r of rejected) {
        toast("error", `${r.file.name}: ${r.errors.map((e) => e.message).join(", ")}`);
      }
      const valid = accepted.filter((f) => {
        if (f.size > MAX_FILE_SIZE) {
          toast("error", `${f.name}: ไฟล์ใหญ่เกิน 20 MB`);
          return false;
        }
        return true;
      });
      setFiles((prev) => [...prev, ...valid]);
    },
    [toast],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
      "image/webp": [".webp"],
      "image/heic": [".heic"],
      "image/heif": [".heif"],
      "application/pdf": [".pdf"],
    },
    maxSize: MAX_FILE_SIZE,
  });

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    try {
      const res = await uploadDocumentsToVisit(visitId, files);
      const summary = [
        `อัปโหลด ${res.document_ids.length} ไฟล์`,
        res.duplicates.length ? `ซ้ำ ${res.duplicates.length}` : null,
        res.failures.length ? `พลาด ${res.failures.length}` : null,
      ]
        .filter(Boolean)
        .join(", ");
      toast("success", summary || "อัปโหลดสำเร็จ");
      reset();
      onUploaded();
      onClose();
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={() => {
        if (!uploading) {
          reset();
          onClose();
        }
      }}
      title="อัปโหลดใบเสร็จเพิ่ม"
      size="md"
    >
      <Stack>
        <Paper
          {...getRootProps()}
          withBorder
          p="md"
          radius="md"
          className="cursor-pointer text-center"
          style={{
            borderStyle: "dashed",
            borderWidth: 2,
            borderColor: isDragActive ? "var(--mantine-color-indigo-4)" : undefined,
            backgroundColor: isDragActive ? "var(--mantine-color-indigo-0)" : undefined,
          }}
        >
          <input {...getInputProps()} />
          <Group justify="center" gap="sm">
            <UploadIcon size={20} />
            <Text size="sm">
              {isDragActive
                ? "วางไฟล์ที่นี่"
                : "ลากใบเสร็จมาวางหรือคลิกเพื่อเลือก (เลือกหลายไฟล์ได้)"}
            </Text>
          </Group>
        </Paper>
        {files.length > 0 && (
          <Stack gap={4}>
            {files.map((f, idx) => (
              <Group key={idx} gap="xs" wrap="nowrap">
                <FileImage size={14} className="text-gray-500 shrink-0" />
                <Text size="sm" className="flex-1 truncate">{f.name}</Text>
                <Text size="xs" c="dimmed">{(f.size / 1024).toFixed(0)} KB</Text>
              </Group>
            ))}
          </Stack>
        )}
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            {files.length} ไฟล์รออัปโหลด
          </Text>
          <Group>
            <Button variant="default" onClick={onClose} disabled={uploading}>
              ยกเลิก
            </Button>
            <Button
              onClick={handleUpload}
              loading={uploading}
              disabled={files.length === 0}
            >
              อัปโหลด
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
