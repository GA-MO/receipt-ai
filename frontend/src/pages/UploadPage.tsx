import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  FileImage,
  Upload,
  XCircle,
} from "lucide-react";
import { Button, Group, Loader, Paper, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { ApiError } from "../api/client";
import { useUploadDocument } from "../api/queries";
import { useToast } from "@/components/Toast";

type Status = "uploading" | "success" | "error";

interface UploadEntry {
  file: File;
  status: Status;
  documentId?: string;
  error?: string;
  existingDocumentId?: string;
}

function readExistingDocId(detail: unknown): string | undefined {
  if (detail && typeof detail === "object" && "existing_document_id" in detail) {
    const id = (detail as { existing_document_id: unknown }).existing_document_id;
    if (typeof id === "string") return id;
  }
  return undefined;
}

const MAX_FILE_SIZE = 20 * 1024 * 1024;

export default function UploadPage() {
  const [uploads, setUploads] = useState<UploadEntry[]>([]);
  const navigate = useNavigate();
  const { toast } = useToast();
  const uploadMut = useUploadDocument();

  const onDrop = useCallback(
    async (accepted: File[], rejected: readonly { file: File; errors: readonly { message: string }[] }[]) => {
      for (const r of rejected) {
        const msg = r.errors.map((e) => e.message).join(", ");
        toast("error", `${r.file.name}: ${msg}`);
      }

      const valid: File[] = [];
      for (const file of accepted) {
        if (file.size > MAX_FILE_SIZE) {
          toast("error", `${file.name}: ไฟล์ใหญ่เกิน 20 MB`);
        } else {
          valid.push(file);
        }
      }

      if (valid.length === 0) return;

      const entries: UploadEntry[] = valid.map((file) => ({
        file,
        status: "uploading" as Status,
      }));
      setUploads((prev) => [...entries, ...prev]);

      for (const file of valid) {
        try {
          const result = await uploadMut.mutateAsync(file);
          setUploads((prev) =>
            prev.map((u) =>
              u.file === file
                ? { ...u, status: "success" as Status, documentId: result.id }
                : u,
            ),
          );
          toast("success", `${file.name}: อัปโหลดสำเร็จ กำลังประมวลผล...`);
        } catch (err: unknown) {
          let msg = "เกิดข้อผิดพลาด";
          let existingDocumentId: string | undefined;
          if (err instanceof ApiError) {
            if (err.status === 409) {
              msg = "เอกสารนี้เคยอัปโหลดแล้ว";
              existingDocumentId = readExistingDocId(err.detail);
            } else if (err.status === 413) msg = "ไฟล์ใหญ่เกินกำหนด";
            else msg = err.message;
          } else if (err instanceof Error) {
            msg = err.message;
          }
          setUploads((prev) =>
            prev.map((u) =>
              u.file === file
                ? { ...u, status: "error" as Status, error: msg, existingDocumentId }
                : u,
            ),
          );
          toast("error", `${file.name}: ${msg}`);
        }
      }
    },
    [toast, uploadMut],
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

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <Title order={2}>อัปโหลดเอกสาร</Title>
        <Text c="dimmed" mt={4}>
          อัปโหลดรูปใบเสร็จ บิล หรือเอกสารการขายภาษาไทย แล้ว AI จะดึงข้อมูลให้อัตโนมัติ
        </Text>
      </div>

      {/* Drop zone */}
      <Paper
        {...getRootProps()}
        withBorder
        p="xl"
        radius="lg"
        className="cursor-pointer transition-colors text-center"
        style={{
          borderStyle: "dashed",
          borderWidth: 2,
          borderColor: isDragActive ? "var(--mantine-color-indigo-4)" : undefined,
          backgroundColor: isDragActive ? "var(--mantine-color-indigo-0)" : undefined,
        }}
      >
        <input {...getInputProps()} />
        <Stack align="center" gap="md">
          <ThemeIcon
            size={64}
            radius="xl"
            variant="light"
            color={isDragActive ? "indigo" : "gray"}
          >
            <Upload size={32} />
          </ThemeIcon>
          <div>
            <Text size="lg" fw={500}>
              {isDragActive ? "วางไฟล์ที่นี่" : "ลากไฟล์มาวางหรือคลิกเพื่อเลือก"}
            </Text>
            <Text size="sm" c="dimmed" mt={4}>
              รองรับ JPG, PNG, WebP, HEIC, PDF (สูงสุด 20 MB)
            </Text>
          </div>
        </Stack>
      </Paper>

      {/* Upload list */}
      {uploads.length > 0 && (
        <div className="mt-8">
          <Title order={4} mb="md">รายการอัปโหลด</Title>
          <Stack gap="sm">
            {uploads.map((entry, idx) => (
              <Paper key={idx} withBorder p="md">
                <Group wrap="nowrap">
                  <FileImage className="w-8 h-8 text-gray-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <Text fw={500} truncate>{entry.file.name}</Text>
                    <Text size="sm" c="dimmed">
                      {(entry.file.size / 1024).toFixed(1)} KB
                    </Text>
                  </div>
                  <div className="shrink-0">
                    {entry.status === "uploading" && (
                      <Group gap="xs">
                        <Loader size="sm" />
                        <Text size="sm" c="indigo">กำลังประมวลผล...</Text>
                      </Group>
                    )}
                    {entry.status === "success" && (
                      <Button
                        variant="subtle"
                        color="green"
                        size="sm"
                        leftSection={<CheckCircle2 size={16} />}
                        onClick={() => navigate(`/documents/${entry.documentId}`)}
                      >
                        ดูผลลัพธ์
                      </Button>
                    )}
                    {entry.status === "error" && (
                      <Group gap="xs">
                        <XCircle className="w-5 h-5 text-red-500" />
                        <Text size="sm" c="red" truncate className="max-w-[200px]">
                          {entry.error || "ผิดพลาด"}
                        </Text>
                        {entry.existingDocumentId && (
                          <Button
                            variant="subtle"
                            color="indigo"
                            size="xs"
                            onClick={() => navigate(`/documents/${entry.existingDocumentId}`)}
                          >
                            ดูเอกสารเดิม
                          </Button>
                        )}
                      </Group>
                    )}
                  </div>
                </Group>
              </Paper>
            ))}
          </Stack>
        </div>
      )}
    </div>
  );
}
