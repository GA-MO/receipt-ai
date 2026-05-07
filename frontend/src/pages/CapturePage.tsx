import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Camera,
  CheckCircle2,
  Image,
  Loader2,
  RotateCcw,
  Send,
  X,
} from "lucide-react";
import { ActionIcon, Button, Loader, Stack, Text, ThemeIcon } from "@mantine/core";
import { ApiError, uploadDocument } from "../api/client";
import { useToast } from "@/components/Toast";

type Step = "ready" | "preview" | "uploading" | "done";

export default function CapturePage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>("ready");
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [docId, setDocId] = useState<string>("");

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const handleCapture = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
    setStep("preview");
  };

  const handleRetake = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(null);
    setPreviewUrl("");
    setStep("ready");
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (cameraInputRef.current) cameraInputRef.current.value = "";
  };

  const handleUpload = async () => {
    if (!file) return;
    setStep("uploading");
    try {
      const result = await uploadDocument(file);
      setDocId(result.id);
      setStep("done");
      toast("success", "อัปโหลดสำเร็จ กำลังประมวลผล...");
    } catch (err) {
      setStep("preview");
      if (err instanceof ApiError && err.status === 409) {
        const existingId =
          err.detail &&
          typeof err.detail === "object" &&
          "existing_document_id" in err.detail &&
          typeof (err.detail as { existing_document_id: unknown }).existing_document_id === "string"
            ? (err.detail as { existing_document_id: string }).existing_document_id
            : undefined;
        toast("warning", "เอกสารนี้เคยอัปโหลดแล้ว");
        if (existingId) navigate(`/documents/${existingId}`);
      } else if (err instanceof ApiError && err.status === 413) {
        toast("error", "ไฟล์ใหญ่เกินกำหนด");
      } else {
        toast("error", "เกิดข้อผิดพลาด");
      }
    }
  };

  return (
    <div className="flex flex-col h-[100dvh] bg-gray-950">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900">
        <Text c="white" fw={600}>ถ่ายเอกสาร</Text>
        <ActionIcon
          variant="filled"
          color="dark.5"
          size="lg"
          radius="xl"
          onClick={() => navigate("/")}
        >
          <X size={20} />
        </ActionIcon>
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col items-center justify-center p-4">
        {step === "ready" && (
          <Stack align="center" gap="lg" className="w-full max-w-sm">
            <div className="w-24 h-24 rounded-full bg-gray-800 flex items-center justify-center">
              <Camera className="w-12 h-12 text-gray-400" />
            </div>
            <Text c="dimmed" ta="center">
              ถ่ายรูปใบเสร็จหรือเลือกจากคลังภาพ
            </Text>

            <input
              ref={cameraInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
              capture="environment"
              onChange={handleCapture}
              className="hidden"
            />
            <Button
              size="xl"
              fullWidth
              radius="xl"
              leftSection={<Camera size={20} />}
              onClick={() => cameraInputRef.current?.click()}
            >
              เปิดกล้อง
            </Button>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
              onChange={handleCapture}
              className="hidden"
            />
            <Button
              size="xl"
              fullWidth
              radius="xl"
              variant="light"
              color="gray"
              leftSection={<Image size={20} />}
              onClick={() => fileInputRef.current?.click()}
            >
              เลือกจากคลังภาพ
            </Button>
          </Stack>
        )}

        {step === "preview" && previewUrl && (
          <Stack align="center" gap="md" className="w-full max-w-sm">
            <div className="w-full rounded-2xl overflow-hidden bg-gray-900 border border-gray-700">
              <img
                src={previewUrl}
                alt="Preview"
                className="w-full max-h-[60dvh] object-contain"
              />
            </div>
            <div className="flex gap-3 w-full">
              <Button
                size="lg"
                radius="xl"
                variant="light"
                color="gray"
                className="flex-1"
                leftSection={<RotateCcw size={16} />}
                onClick={handleRetake}
              >
                ถ่ายใหม่
              </Button>
              <Button
                size="lg"
                radius="xl"
                className="flex-1"
                leftSection={<Send size={16} />}
                onClick={handleUpload}
              >
                ส่งประมวลผล
              </Button>
            </div>
          </Stack>
        )}

        {step === "uploading" && (
          <Stack align="center" gap="md">
            <Loader size="xl" color="indigo" />
            <Text c="dimmed">กำลังอัปโหลด...</Text>
          </Stack>
        )}

        {step === "done" && (
          <Stack align="center" gap="lg" className="w-full max-w-sm">
            <ThemeIcon size={80} radius="xl" color="green" variant="light">
              <CheckCircle2 size={40} />
            </ThemeIcon>
            <div className="text-center">
              <Text c="white" fw={600} size="lg">อัปโหลดสำเร็จ</Text>
              <Text c="dimmed" size="sm" mt={4}>
                AI กำลังประมวลผลเอกสาร
              </Text>
            </div>
            <Stack gap="sm" className="w-full">
              <Button
                size="lg"
                radius="xl"
                fullWidth
                onClick={() => navigate(`/documents/${docId}`)}
              >
                ดูผลลัพธ์
              </Button>
              <Button
                size="lg"
                radius="xl"
                variant="light"
                color="gray"
                fullWidth
                onClick={handleRetake}
              >
                ถ่ายเอกสารเพิ่ม
              </Button>
            </Stack>
          </Stack>
        )}
      </div>
    </div>
  );
}
