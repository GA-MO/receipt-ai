import { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useNavigate } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Stepper,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { MonthPickerInput } from "@mantine/dates";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileImage,
  FileText,
  Store as StoreIcon,
  Upload,
  User,
} from "lucide-react";
import { uploadDocumentsToVisit, getDocumentImageUrl } from "../api/client";
import { useCreateVisit, useStores, useVisit } from "../api/queries";
import { useToast } from "@/components/Toast";

const MAX_FILE_SIZE = 20 * 1024 * 1024;

type Step = 0 | 1 | 2;

function toPeriod(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

export default function VisitNewPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: stores } = useStores();
  const createMut = useCreateVisit();

  const [step, setStep] = useState<Step>(0);
  const [storeId, setStoreId] = useState<string | null>(null);
  const [periodDate, setPeriodDate] = useState<Date | null>(new Date());
  const [repName, setRepName] = useState("");
  const [visitId, setVisitId] = useState<string | null>(null);

  const storeOptions = useMemo(
    () =>
      (stores ?? []).map((s) => ({
        value: s.id,
        label: s.code ? `${s.name} (${s.code})` : s.name,
      })),
    [stores],
  );

  const handleCreateVisit = async () => {
    if (!storeId || !periodDate) {
      toast("error", "เลือกร้านและเดือนรายงานก่อน");
      return;
    }
    try {
      const visit = await createMut.mutateAsync({
        store_id: storeId,
        report_period: toPeriod(periodDate),
        rep_name: repName.trim() || undefined,
      });
      setVisitId(visit.id);
      setStep(1);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "สร้างไม่สำเร็จ");
    }
  };

  return (
    <div className="max-w-5xl mx-auto">
      <Title order={2} mb="xs">เริ่ม visit ใหม่</Title>
      <Text c="dimmed" mb="lg">
        เลือกร้านและเดือนรายงาน → อัปโหลดใบเสร็จ → ตรวจสอบและสรุป
      </Text>

      <Stepper
        active={step}
        onStepClick={(s) => {
          // Allow clicking back to earlier completed steps; can't skip ahead.
          if (s <= step) setStep(s as Step);
        }}
        mb="xl"
      >
        <Stepper.Step label="ร้านและเดือน" description="เลือกร้านจาก master + เดือนรายงาน">
          <StoreAndPeriodStep
            storeOptions={storeOptions}
            storeId={storeId}
            onStoreId={setStoreId}
            periodDate={periodDate}
            onPeriodDate={setPeriodDate}
            repName={repName}
            onRepName={setRepName}
          />
          <Group justify="flex-end" mt="lg">
            <Button
              variant="default"
              onClick={() => navigate("/visits")}
            >
              ยกเลิก
            </Button>
            <Button
              rightSection={<ChevronRight size={16} />}
              onClick={handleCreateVisit}
              loading={createMut.isPending}
              disabled={!storeId || !periodDate}
            >
              ถัดไป
            </Button>
          </Group>
        </Stepper.Step>

        <Stepper.Step label="อัปโหลด" description="ลากใบเสร็จมาทั้งหมด แล้วรอ AI ประมวลผล">
          {visitId && (
            <UploadStep
              visitId={visitId}
              onDone={() => setStep(2)}
            />
          )}
        </Stepper.Step>

        <Stepper.Step label="ตรวจสอบ + สรุป" description="ไล่ตรวจ AI ทีละใบ แล้วดูยอดสรุป">
          {visitId && <SummaryStep visitId={visitId} />}
        </Stepper.Step>
      </Stepper>
    </div>
  );
}

function StoreAndPeriodStep({
  storeOptions,
  storeId,
  onStoreId,
  periodDate,
  onPeriodDate,
  repName,
  onRepName,
}: {
  storeOptions: { value: string; label: string }[];
  storeId: string | null;
  onStoreId: (v: string | null) => void;
  periodDate: Date | null;
  onPeriodDate: (v: Date | null) => void;
  repName: string;
  onRepName: (v: string) => void;
}) {
  return (
    <Card withBorder radius="md" mt="md">
      <Stack gap="md">
        <Select
          label="ร้าน (เลือกจาก Store master)"
          required
          placeholder={storeOptions.length ? "เลือกร้าน" : "ยังไม่มีร้าน — เพิ่มที่ Store master ก่อน"}
          data={storeOptions}
          value={storeId}
          onChange={onStoreId}
          searchable
          clearable
          leftSection={<StoreIcon size={14} />}
          disabled={storeOptions.length === 0}
        />
        <MonthPickerInput
          label="เดือนรายงาน"
          required
          description="ใบเสร็จที่วันที่นอกเดือนนี้จะถูก flag ให้ตรวจ"
          value={periodDate}
          onChange={(v) => onPeriodDate(v ? new Date(v) : null)}
          maxDate={new Date()}
          minDate={new Date(2020, 0, 1)}
        />
        <TextInput
          label="คนเก็บ (optional)"
          placeholder="ชื่อ sales rep / merchandiser"
          value={repName}
          onChange={(e) => onRepName(e.currentTarget.value)}
          leftSection={<User size={14} />}
        />
      </Stack>
    </Card>
  );
}

interface PendingFile {
  file: File;
  id?: string;
  status: "queued" | "uploaded" | "error";
  error?: string;
}

function UploadStep({
  visitId,
  onDone,
}: {
  visitId: string;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const { data: visit, refetch } = useVisit(visitId);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState(false);

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

  const handleUpload = async () => {
    const queued = files.filter((f) => f.status === "queued");
    if (queued.length === 0) {
      toast("error", "ยังไม่มีไฟล์รอ upload");
      return;
    }
    setUploading(true);
    try {
      const res = await uploadDocumentsToVisit(
        visitId,
        queued.map((f) => f.file),
      );
      // Mark queued files as uploaded (best-effort by filename ordering).
      let i = 0;
      setFiles((prev) =>
        prev.map((f) => {
          if (f.status !== "queued") return f;
          const docId = res.document_ids[i++];
          return docId ? { ...f, id: docId, status: "uploaded" } : { ...f, status: "error" };
        }),
      );
      if (res.duplicates.length) {
        toast(
          "info",
          `ข้าม ${res.duplicates.length} ไฟล์ที่ซ้ำกับเอกสารในระบบ`,
        );
      }
      if (res.failures.length) {
        toast("error", `${res.failures.length} ไฟล์อัปโหลดไม่สำเร็จ`);
      }
      refetch();
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setUploading(false);
    }
  };

  const docs = visit?.documents ?? [];
  const stillProcessing = docs.some(
    (d) => d.status === "processing" || d.status === "pending",
  );

  useEffect(() => {
    if (!stillProcessing) return;
    const t = setInterval(() => refetch(), 2000);
    return () => clearInterval(t);
  }, [stillProcessing, refetch]);

  const queuedCount = files.filter((f) => f.status === "queued").length;
  const canContinue = docs.length > 0 && !stillProcessing && !uploading;

  return (
    <Stack mt="md">
      {/* Dropzone */}
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
            {isDragActive ? "วางไฟล์ที่นี่" : "ลากใบเสร็จมาวางหรือคลิกเพื่อเลือก"}
          </Text>
        </Group>
      </Paper>

      {queuedCount > 0 && (
        <Group justify="flex-end">
          <Button onClick={handleUpload} loading={uploading}>
            อัปโหลด {queuedCount} ไฟล์
          </Button>
        </Group>
      )}

      {/* Queued (not yet uploaded) */}
      {files.filter((f) => f.status === "queued").length > 0 && (
        <Card withBorder p="sm" radius="md">
          <Text size="xs" c="dimmed" mb={4}>รอ upload</Text>
          <Stack gap={4}>
            {files
              .filter((f) => f.status === "queued")
              .map((f, idx) => (
                <Group key={`q-${idx}`} gap="xs" wrap="nowrap">
                  <FileImage size={14} className="text-gray-500 shrink-0" />
                  <Text size="sm" className="flex-1 truncate">
                    {f.file.name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {(f.file.size / 1024).toFixed(0)} KB
                  </Text>
                </Group>
              ))}
          </Stack>
        </Card>
      )}

      {/* Thumbnail grid of uploaded docs */}
      {docs.length > 0 && (
        <div>
          <Group justify="space-between" mb="xs">
            <Text fw={600}>
              อัปโหลดแล้ว {docs.length} ใบ
              {stillProcessing && (
                <Badge ml="xs" color="blue" variant="light">กำลังประมวลผล</Badge>
              )}
            </Text>
            {stillProcessing && <Loader size="xs" />}
          </Group>
          <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 5 }} spacing="sm">
            {docs.map((d) => (
              <DocThumb key={d.id} doc={d} />
            ))}
          </SimpleGrid>
        </div>
      )}

      <Group justify="space-between" mt="lg">
        <Text size="xs" c="dimmed">
          {stillProcessing
            ? "รอ AI ประมวลผลทุกใบ — แล้วค่อยกดถัดไป"
            : docs.length === 0
              ? "อัปโหลดอย่างน้อย 1 ใบก่อน"
              : "พร้อมไปต่อ"}
        </Text>
        <Button
          rightSection={<ChevronRight size={16} />}
          onClick={onDone}
          disabled={!canContinue}
        >
          ไปตรวจสอบ + สรุป
        </Button>
      </Group>
    </Stack>
  );
}

const STATUS_LABEL: Record<string, { color: string; label: string }> = {
  pending: { color: "gray", label: "รอ" },
  processing: { color: "blue", label: "ประมวลผล" },
  extracted: { color: "yellow", label: "ดึงข้อมูลแล้ว" },
  reviewed: { color: "green", label: "ตรวจแล้ว" },
  error: { color: "red", label: "ผิดพลาด" },
};

function DocThumb({
  doc,
}: {
  doc: { id: string; filename: string; status: string; file_type: string; period_mismatch?: boolean };
}) {
  const status = STATUS_LABEL[doc.status] || { color: "gray", label: doc.status };
  return (
    <Card withBorder p="xs" radius="md">
      <Card.Section>
        <div
          className="bg-gray-100 dark:bg-gray-800 flex items-center justify-center"
          style={{ aspectRatio: "3/4", overflow: "hidden" }}
        >
          {doc.file_type === "pdf" ? (
            <FileText size={32} className="text-gray-400" />
          ) : (
            <img
              src={getDocumentImageUrl(doc.id)}
              alt={doc.filename}
              loading="lazy"
              className="w-full h-full object-cover"
              onError={(e) => {
                e.currentTarget.style.visibility = "hidden";
              }}
            />
          )}
        </div>
      </Card.Section>
      <Stack gap={2} mt={6}>
        <Text size="xs" truncate>{doc.filename}</Text>
        <Group gap={4} wrap="nowrap">
          <Badge size="xs" color={status.color} variant="light">{status.label}</Badge>
          {doc.period_mismatch && (
            <Badge size="xs" color="orange" variant="light" leftSection={<AlertTriangle size={10} />}>
              นอกเดือน
            </Badge>
          )}
        </Group>
      </Stack>
    </Card>
  );
}

function SummaryStep({ visitId }: { visitId: string }) {
  const navigate = useNavigate();
  const { data: visit, refetch } = useVisit(visitId);
  const stillProcessing = visit?.documents.some(
    (d) => d.status === "processing" || d.status === "pending",
  );
  useEffect(() => {
    if (!stillProcessing) return;
    const t = setInterval(() => refetch(), 2000);
    return () => clearInterval(t);
  }, [stillProcessing, refetch]);

  if (!visit) return <Loader />;

  const totalQty = visit.aggregate.reduce((s, r) => s + r.total_quantity, 0);
  const matched = visit.aggregate.filter((r) => r.is_catalog_match).length;
  const unknown = visit.aggregate.length - matched;
  const periodMismatchCount = visit.documents.filter((d) => d.period_mismatch).length;

  const firstDoc = visit.documents[0];

  return (
    <Stack mt="md">
      <Group gap="sm">
        <Badge size="lg" variant="light" color="indigo">
          {visit.documents.length} ใบ
        </Badge>
        <Badge
          size="lg"
          variant="light"
          color={visit.reviewed_count === visit.documents.length ? "green" : "yellow"}
        >
          ตรวจแล้ว {visit.reviewed_count}/{visit.documents.length}
        </Badge>
        <Badge size="lg" variant="light" color="grape">
          {visit.aggregate.length} สินค้า
        </Badge>
        <Badge size="lg" variant="light" color="teal">
          รวม {totalQty.toFixed(0)} หน่วย
        </Badge>
        {matched > 0 && (
          <Badge size="lg" variant="light" color="green">
            in catalog: {matched}
          </Badge>
        )}
        {unknown > 0 && (
          <Badge size="lg" variant="light" color="orange">
            ไม่อยู่ catalog: {unknown}
          </Badge>
        )}
        {periodMismatchCount > 0 && (
          <Badge size="lg" variant="light" color="orange" leftSection={<AlertTriangle size={12} />}>
            นอกเดือน: {periodMismatchCount}
          </Badge>
        )}
      </Group>

      {visit.aggregate.length === 0 ? (
        <Paper withBorder p="lg" radius="md">
          <Text c="dimmed" ta="center">
            ยังไม่มีข้อมูลสรุป — รอ AI ประมวลผลเสร็จ
          </Text>
        </Paper>
      ) : (
        <Card withBorder radius="md">
          <Text fw={600} mb="sm">
            สินค้า top 10 (ดูทั้งหมดที่หน้าสรุป)
          </Text>
          <Stack gap={4}>
            {visit.aggregate.slice(0, 10).map((r, idx) => (
              <Group key={`${r.product_code ?? r.display_name}-${idx}`} gap="sm" wrap="nowrap">
                {r.is_catalog_match ? (
                  <ThemeIcon size="xs" color="green" variant="light">
                    <CheckCircle2 size={12} />
                  </ThemeIcon>
                ) : (
                  <ThemeIcon size="xs" color="orange" variant="light">
                    <AlertTriangle size={12} />
                  </ThemeIcon>
                )}
                <Text size="sm" className="flex-1 truncate">{r.display_name}</Text>
                <Text size="sm" fw={600}>
                  {r.total_quantity.toFixed(r.total_quantity % 1 ? 2 : 0)} {r.unit ?? ""}
                </Text>
              </Group>
            ))}
          </Stack>
        </Card>
      )}

      <Group justify="space-between" mt="sm">
        <Button variant="default" onClick={() => navigate("/visits")}>
          กลับไปหน้ารายการ
        </Button>
        <Group>
          <Button variant="light" onClick={() => navigate(`/visits/${visitId}`)}>
            ไปหน้าสรุปเต็ม
          </Button>
          {firstDoc && (
            <Button
              color="indigo"
              onClick={() => navigate(`/visits/${visitId}/review/${firstDoc.id}`)}
              rightSection={<ChevronRight size={16} />}
            >
              เริ่มไล่ตรวจสอบ
            </Button>
          )}
        </Group>
      </Group>
    </Stack>
  );
}
