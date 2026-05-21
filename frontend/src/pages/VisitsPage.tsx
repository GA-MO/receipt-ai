import { useCallback, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Link, useNavigate } from "react-router-dom";
import { format } from "date-fns";
import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { FileImage, Plus, Store, Upload, User } from "lucide-react";
import {
  useCreateVisit,
  useStores,
  useVisits,
} from "../api/queries";
import { uploadDocumentsToVisit } from "../api/client";
import { useToast } from "@/components/Toast";

const MAX_FILE_SIZE = 20 * 1024 * 1024;

interface PendingFile {
  file: File;
  status: "queued" | "uploading" | "done" | "error";
  error?: string;
}

export default function VisitsPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: visits, isPending } = useVisits({ limit: 50 });
  const { data: stores } = useStores();
  const createMut = useCreateVisit();

  const [storeId, setStoreId] = useState<string | null>(null);
  const [repName, setRepName] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const storeOptions = useMemo(
    () =>
      (stores ?? []).map((s) => ({
        value: s.id,
        label: s.code ? `${s.name} (${s.code})` : s.name,
      })),
    [stores],
  );

  const onDrop = useCallback(
    (accepted: File[], rejected: readonly { file: File; errors: readonly { message: string }[] }[]) => {
      for (const r of rejected) {
        const msg = r.errors.map((e) => e.message).join(", ");
        toast("error", `${r.file.name}: ${msg}`);
      }
      const valid = accepted.filter((f) => {
        if (f.size > MAX_FILE_SIZE) {
          toast("error", `${f.name}: ไฟล์ใหญ่เกิน 20 MB`);
          return false;
        }
        return true;
      });
      setFiles((prev) => [
        ...prev,
        ...valid.map<PendingFile>((file) => ({ file, status: "queued" })),
      ]);
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

  const handleStartVisit = async () => {
    if (!storeId) {
      toast("error", "เลือกร้านก่อน — ถ้ายังไม่มีให้ไปเพิ่มที่ Store master");
      return;
    }
    if (files.length === 0) {
      toast("error", "เพิ่มไฟล์อย่างน้อย 1 รูปก่อนเริ่ม visit");
      return;
    }
    setSubmitting(true);
    try {
      const visit = await createMut.mutateAsync({
        store_id: storeId,
        rep_name: repName.trim() || undefined,
      });
      const data = await uploadDocumentsToVisit(
        visit.id,
        files.map((f) => f.file),
      );
      toast(
        "success",
        `สร้าง visit สำเร็จ — อัปโหลด ${data.document_ids.length} ไฟล์ กำลังประมวลผล...`,
      );
      navigate(`/visits/${visit.id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "เกิดข้อผิดพลาด";
      toast("error", msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6">
        <Title order={2}>การเยี่ยมร้าน (Visits)</Title>
        <Text c="dimmed" mt={4}>
          เก็บใบเสร็จของร้านเดือนนั้นเป็น 1 visit — ดูยอดสินค้ารวมทั้งร้านได้ทันที
        </Text>
      </div>

      {/* Start-a-new-visit panel */}
      <Card withBorder radius="md" mb="xl">
        <Stack gap="md">
          <Group justify="space-between" wrap="nowrap">
            <Group gap="sm">
              <ThemeIcon size="lg" radius="md" variant="light" color="indigo">
                <Plus size={18} />
              </ThemeIcon>
              <div>
                <Text fw={600}>เริ่ม visit ใหม่</Text>
                <Text size="xs" c="dimmed">
                  ใส่ชื่อร้าน + คนเก็บ แล้วลากใบเสร็จทั้งหมดมาปล่อย
                </Text>
              </div>
            </Group>
            <Button
              onClick={handleStartVisit}
              loading={submitting}
              disabled={files.length === 0}
              size="sm"
            >
              สร้าง visit + อัปโหลด {files.length > 0 ? `(${files.length})` : ""}
            </Button>
          </Group>
          <Group gap="md" grow align="flex-end">
            <Select
              label="ร้าน (เลือกจาก Store master)"
              required
              placeholder={storeOptions.length ? "เลือกร้าน" : "ยังไม่มีร้าน — เพิ่มที่หน้า Store master ก่อน"}
              data={storeOptions}
              value={storeId}
              onChange={setStoreId}
              searchable
              clearable
              nothingFoundMessage="ไม่พบร้าน"
              leftSection={<Store size={14} />}
              disabled={storeOptions.length === 0}
            />
            <TextInput
              label="คนเก็บ (optional)"
              placeholder="ชื่อ sales rep / merchandiser"
              value={repName}
              onChange={(e) => setRepName(e.currentTarget.value)}
              leftSection={<User size={14} />}
            />
          </Group>
          {storeOptions.length === 0 && (
            <Text size="xs" c="orange">
              ยังไม่มีร้านในระบบ —{" "}
              <Link to="/stores" className="underline">
                ไปที่หน้า Store master เพื่อเพิ่มร้าน
              </Link>
            </Text>
          )}

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
              <Upload size={20} />
              <Text size="sm">
                {isDragActive ? "วางไฟล์ที่นี่" : "ลากใบเสร็จมาวางหรือคลิกเพื่อเลือก (เลือกหลายไฟล์ได้)"}
              </Text>
            </Group>
          </Paper>

          {files.length > 0 && (
            <Stack gap="xs">
              {files.map((f, idx) => (
                <Group key={idx} gap="xs" wrap="nowrap">
                  <FileImage size={16} className="text-gray-500 shrink-0" />
                  <Text size="sm" className="flex-1 truncate">{f.file.name}</Text>
                  <Text size="xs" c="dimmed">
                    {(f.file.size / 1024).toFixed(0)} KB
                  </Text>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      {/* Existing visits list */}
      <Title order={4} mb="sm">Visit ที่มีอยู่</Title>
      {isPending ? (
        <Loader />
      ) : !visits || visits.length === 0 ? (
        <Paper withBorder p="lg" radius="md">
          <Text c="dimmed" ta="center">
            ยังไม่มี visit — สร้างอันแรกจากแบบฟอร์มด้านบนเลย
          </Text>
        </Paper>
      ) : (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ร้านค้า</Table.Th>
                <Table.Th>คนเก็บ</Table.Th>
                <Table.Th ta="right">ใบ</Table.Th>
                <Table.Th ta="right">ตรวจแล้ว</Table.Th>
                <Table.Th>ช่วงวันที่</Table.Th>
                <Table.Th>สร้างเมื่อ</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {visits.map((v) => {
                const dateRange =
                  v.earliest_doc_date && v.latest_doc_date
                    ? v.earliest_doc_date === v.latest_doc_date
                      ? v.earliest_doc_date
                      : `${v.earliest_doc_date} → ${v.latest_doc_date}`
                    : "—";
                return (
                  <Table.Tr key={v.id}>
                    <Table.Td>
                      <Link to={`/visits/${v.id}`} className="text-indigo-600 hover:underline">
                        <Text fw={500} component="span">
                          {v.store_label || v.store_key || "(ไม่ระบุ)"}
                        </Text>
                      </Link>
                    </Table.Td>
                    <Table.Td>{v.rep_name || <Text c="dimmed">—</Text>}</Table.Td>
                    <Table.Td ta="right">
                      <Badge variant="light" color={v.document_count > 0 ? "indigo" : "gray"}>
                        {v.document_count}
                      </Badge>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Badge
                        variant="light"
                        color={
                          v.document_count === 0
                            ? "gray"
                            : v.reviewed_count === v.document_count
                              ? "green"
                              : "yellow"
                        }
                      >
                        {v.reviewed_count}/{v.document_count}
                      </Badge>
                    </Table.Td>
                    <Table.Td><Text size="sm">{dateRange}</Text></Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {format(new Date(v.created_at), "yyyy-MM-dd HH:mm")}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
    </div>
  );
}
