import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { format } from "date-fns";
import {
  ActionIcon,
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
  HelpCircle,
  RefreshCw,
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
          <Group gap="sm" align="baseline">
            <Title order={2}>{visit.store_label || visit.store_key || "(ไม่ระบุร้าน)"}</Title>
            {visit.report_period && (
              <Text size="lg" c="dimmed" fw={500}>
                · {visit.report_period}
              </Text>
            )}
            {stillProcessing && (
              <Text size="sm" c="blue">
                กำลังประมวลผล...
              </Text>
            )}
          </Group>
          <Group gap="lg" mt={4}>
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

      {/* Summary — calm stat blocks, no chips */}
      <Card withBorder radius="md" p="md" mb="md">
        <Group gap="xl" align="flex-start" wrap="wrap">
          <Stat value={docs.length} label="ใบเสร็จ" />
          <Stat
            value={`${visit.reviewed_count}/${docs.length}`}
            label="ตรวจสอบแล้ว"
            color={
              docs.length > 0 && visit.reviewed_count === docs.length
                ? "green.7"
                : undefined
            }
          />
          <Stat value={visit.aggregate.length} label="สินค้า" />
          <Stat value={totalQty.toFixed(0)} label="หน่วยรวม" />
          {unknownCount > 0 && (
            <Stat value={unknownCount} label="ไม่อยู่ catalog" color="orange.7" />
          )}
          {periodMismatchCount > 0 && (
            <Stat value={periodMismatchCount} label="นอกเดือน" color="orange.7" />
          )}
          {isFetching && (
            <div className="self-center">
              <Loader size="xs" />
            </div>
          )}
        </Group>
      </Card>

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
                    <Table.Th w={24}></Table.Th>
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
                          <Table.Td ta="center">
                            {row.is_catalog_match ? (
                              <Tooltip
                                label={row.product_code ? `SKU ${row.product_code}` : "อยู่ใน catalog"}
                              >
                                <CheckCircle2 size={14} className="text-green-600" />
                              </Tooltip>
                            ) : (
                              <Tooltip label="ไม่อยู่ใน catalog">
                                <HelpCircle size={14} className="text-orange-500" />
                              </Tooltip>
                            )}
                          </Table.Td>
                          <Table.Td>
                            <Text fw={500}>{row.display_name}</Text>
                            {row.product_code && (
                              <Text size="xs" c="dimmed">SKU {row.product_code}</Text>
                            )}
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm" c="dimmed">
                              {row.manufacturer || "—"}
                            </Text>
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
                            <Text fw={500}>{row.source_count}</Text>
                          </Table.Td>
                        </Table.Tr>
                        {open && (
                          <Table.Tr>
                            <Table.Td></Table.Td>
                            <Table.Td colSpan={6}>
                              <Stack gap={4} py="xs">
                                {row.source_doc_ids.map((did) => {
                                  const d = docsById.get(did);
                                  if (!d) return null;
                                  const sLabel = STATUS_LABEL[d.status];
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
                                      <Tooltip label={sLabel?.label || d.status}>
                                        <span
                                          className="inline-block w-2 h-2 rounded-full shrink-0"
                                          style={{
                                            backgroundColor: `var(--mantine-color-${sLabel?.color || "gray"}-6)`,
                                          }}
                                        />
                                      </Tooltip>
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
                  style={{
                    borderRadius: 0,
                    borderLeft: d.period_mismatch
                      ? "4px solid var(--mantine-color-orange-5)"
                      : "4px solid transparent",
                  }}
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
                      <Group gap="sm" mt={2} wrap="nowrap">
                        <Text size="xs" c="dimmed" truncate>
                          {d.merchant_name || "—"}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {d.item_count} รายการ
                        </Text>
                      </Group>
                      {d.document_date && (
                        <Group gap={4} mt={2} wrap="nowrap">
                          <Text
                            size="xs"
                            ff="monospace"
                            fw={d.period_mismatch ? 700 : 400}
                            c={d.period_mismatch ? "orange.7" : "dimmed"}
                          >
                            {d.document_date}
                          </Text>
                          {d.period_mismatch && (
                            <Tooltip
                              label={`นอกเดือนรายงาน ${visit.report_period ?? ""}`}
                            >
                              <AlertTriangle
                                size={12}
                                className="text-orange-500 shrink-0"
                              />
                            </Tooltip>
                          )}
                        </Group>
                      )}
                    </div>
                    <Group gap={6} wrap="nowrap">
                      <Tooltip label={STATUS_LABEL[d.status]?.label || d.status}>
                        <span
                          className="inline-block w-2 h-2 rounded-full shrink-0"
                          style={{
                            backgroundColor: `var(--mantine-color-${STATUS_LABEL[d.status]?.color || "gray"}-6)`,
                          }}
                        />
                      </Tooltip>
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

function Stat({
  value,
  label,
  color,
}: {
  value: number | string;
  label: string;
  color?: string;
}) {
  return (
    <div>
      <Text size="xl" fw={700} c={color} lh={1.1}>
        {value}
      </Text>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
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
