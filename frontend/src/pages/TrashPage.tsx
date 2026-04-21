/**
 * Recycle bin: soft-deleted documents. User can restore or permanently purge.
 * Layout mirrors DocumentsPage but with restore/purge actions instead of the
 * usual list actions.
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { FileText, RotateCcw, Trash2 } from "lucide-react";
import { useBulkPurge, useBulkRestore, useTrash } from "../api/queries";
import { getDocumentImageUrl } from "../api/client";
import { useToast } from "@/components/Toast";

export default function TrashPage() {
  const { toast } = useToast();
  const { data: docs = [], isPending } = useTrash({ limit: 100 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmPurge, setConfirmPurge] = useState(false);
  const restoreMut = useBulkRestore();
  const purgeMut = useBulkPurge();

  const ids = useMemo(() => docs.map((d) => d.id), [docs]);
  const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
  const someSelected = ids.some((id) => selected.has(id));

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });

  const list = Array.from(selected);

  const handleRestore = async () => {
    try {
      const res = await restoreMut.mutateAsync(list);
      toast("success", `กู้คืน ${res.succeeded} เอกสาร`);
      setSelected(new Set());
    } catch {
      toast("error", "ไม่สามารถกู้คืนได้");
    }
  };

  const handlePurge = async () => {
    try {
      const res = await purgeMut.mutateAsync(list);
      toast("success", `ลบถาวร ${res.succeeded} เอกสาร`);
      setSelected(new Set());
      setConfirmPurge(false);
    } catch {
      toast("error", "ไม่สามารถลบได้");
      setConfirmPurge(false);
    }
  };

  return (
    <div>
      <Group justify="space-between" mb="lg">
        <div>
          <Title order={2}>ถังขยะ</Title>
          <Text c="dimmed" size="sm">
            {docs.length} เอกสารที่ลบไว้ — กู้คืนได้ก่อนลบถาวร
          </Text>
        </div>
        <Button component={Link} to="/documents" variant="subtle">
          กลับไปหน้าเอกสาร
        </Button>
      </Group>

      {selected.size > 0 && (
        <Paper withBorder p="sm" mb="sm" bg="var(--mantine-color-indigo-0)">
          <Group justify="space-between">
            <Text size="sm" fw={600}>เลือก {selected.size} เอกสาร</Text>
            <Group gap="xs">
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setSelected(new Set())}
              >
                ยกเลิก
              </Button>
              <Button
                size="xs"
                color="green"
                leftSection={<RotateCcw size={14} />}
                onClick={handleRestore}
                loading={restoreMut.isPending}
              >
                กู้คืน
              </Button>
              <Button
                size="xs"
                color="red"
                leftSection={<Trash2 size={14} />}
                onClick={() => setConfirmPurge(true)}
              >
                ลบถาวร
              </Button>
            </Group>
          </Group>
        </Paper>
      )}

      {isPending ? (
        <div className="flex items-center justify-center h-64">
          <Loader size="lg" />
        </div>
      ) : docs.length === 0 ? (
        <Stack align="center" py="xl" gap="md">
          <Trash2 className="w-16 h-16 text-gray-300" />
          <Text c="dimmed" size="lg">ถังขยะว่างเปล่า</Text>
        </Stack>
      ) : (
        <Paper withBorder className="overflow-x-auto">
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={40}>
                  <Checkbox
                    checked={allSelected}
                    indeterminate={!allSelected && someSelected}
                    onChange={toggleAll}
                    aria-label="เลือกทั้งหมด"
                  />
                </Table.Th>
                <Table.Th w={60} />
                <Table.Th>เอกสาร</Table.Th>
                <Table.Th>ร้านค้า</Table.Th>
                <Table.Th ta="right">ยอดรวม</Table.Th>
                <Table.Th ta="right">รายการ</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {docs.map((doc) => {
                const checked = selected.has(doc.id);
                return (
                  <Table.Tr
                    key={doc.id}
                    bg={checked ? "var(--mantine-color-indigo-0)" : undefined}
                    style={{ opacity: 0.85 }}
                  >
                    <Table.Td>
                      <Checkbox checked={checked} onChange={() => toggle(doc.id)} />
                    </Table.Td>
                    <Table.Td>
                      {doc.file_type === "pdf" ? (
                        <div className="w-10 h-10 rounded border border-gray-200 flex items-center justify-center">
                          <FileText className="w-5 h-5 text-gray-400" />
                        </div>
                      ) : (
                        <img
                          src={getDocumentImageUrl(doc.id)}
                          alt=""
                          loading="lazy"
                          className="w-10 h-10 rounded border border-gray-200 object-cover grayscale"
                          onError={(e) => {
                            e.currentTarget.style.visibility = "hidden";
                          }}
                        />
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" lineClamp={1}>{doc.filename}</Text>
                      <Text size="xs" c="dimmed">
                        ลบเมื่อ {new Date(doc.uploaded_at).toLocaleString("th-TH")}
                      </Text>
                    </Table.Td>
                    <Table.Td>{doc.merchant_name || "-"}</Table.Td>
                    <Table.Td ta="right">
                      <Text size="sm" ff="monospace">
                        {doc.grand_total != null
                          ? `฿${doc.grand_total.toLocaleString("th-TH", { minimumFractionDigits: 2 })}`
                          : "-"}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right">{doc.item_count}</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Paper>
      )}

      <Modal
        opened={confirmPurge}
        onClose={() => setConfirmPurge(false)}
        title="ลบถาวร"
        centered
      >
        <Text size="sm" c="dimmed">
          ต้องการลบถาวร {selected.size} เอกสาร? ไฟล์บนดิสก์จะถูกลบและไม่สามารถกู้คืนได้
        </Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="outline" onClick={() => setConfirmPurge(false)}>ยกเลิก</Button>
          <Button
            color="red"
            leftSection={<Trash2 size={14} />}
            onClick={handlePurge}
            loading={purgeMut.isPending}
          >
            ลบถาวร
          </Button>
        </Group>
      </Modal>
    </div>
  );
}
