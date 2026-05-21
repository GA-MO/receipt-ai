import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { format } from "date-fns";
import {
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
} from "@mantine/core";
import { MonthPickerInput } from "@mantine/dates";
import { ArrowLeft, ChevronRight, Plus } from "lucide-react";
import { useCreateVisit, useStore, useVisits } from "../api/queries";
import { useToast } from "@/components/Toast";

function toPeriod(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function formatPeriod(period: string | null): string {
  if (!period) return "—";
  const [y, m] = period.split("-");
  if (!y || !m) return period;
  const monthNames = [
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
  ];
  const monthIdx = Number(m) - 1;
  return `${monthNames[monthIdx] ?? m} ${y}`;
}

export default function StoreDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data: store } = useStore(id);
  const { data: visits, isPending } = useVisits({ store_id: id, limit: 200 });
  const createMut = useCreateVisit();

  const [addOpen, setAddOpen] = useState(false);
  const [pickerDate, setPickerDate] = useState<Date | null>(new Date());

  // Sort by report_period desc (newest first).
  const sortedVisits = [...(visits ?? [])].sort((a, b) => {
    const ap = a.report_period ?? "";
    const bp = b.report_period ?? "";
    return bp.localeCompare(ap);
  });

  const handleAddMonth = async () => {
    if (!id || !pickerDate) return;
    try {
      const visit = await createMut.mutateAsync({
        store_id: id,
        report_period: toPeriod(pickerDate),
      });
      setAddOpen(false);
      navigate(`/visits/${visit.id}`);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : "สร้างไม่สำเร็จ");
    }
  };

  if (!store) {
    return <Loader />;
  }

  return (
    <div className="max-w-5xl mx-auto">
      <Group justify="space-between" mb="md" align="flex-start">
        <div>
          <Button
            variant="default"
            size="xs"
            component={Link}
            to="/stores"
            leftSection={<ArrowLeft size={14} />}
            mb="xs"
          >
            กลับรายการร้าน
          </Button>
          <Title order={2}>{store.name}</Title>
          <Group gap="md" mt={4}>
            {store.code && (
              <Text size="sm" c="dimmed">
                Code <b>{store.code}</b>
              </Text>
            )}
            {store.address && (
              <Text size="sm" c="dimmed">
                {store.address}
              </Text>
            )}
          </Group>
        </div>
        <Button leftSection={<Plus size={16} />} onClick={() => setAddOpen(true)}>
          เพิ่มเดือน
        </Button>
      </Group>

      <Title order={4} mb="sm">
        ยอดขายรายเดือน
      </Title>

      {isPending ? (
        <Loader />
      ) : sortedVisits.length === 0 ? (
        <Paper withBorder p="lg" radius="md">
          <Stack align="center" gap="sm">
            <Text c="dimmed" ta="center">
              ยังไม่มีเดือนรายงานสำหรับร้านนี้
            </Text>
            <Button
              leftSection={<Plus size={14} />}
              size="sm"
              onClick={() => setAddOpen(true)}
            >
              เริ่มเดือนแรก
            </Button>
          </Stack>
        </Paper>
      ) : (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>เดือนรายงาน</Table.Th>
                <Table.Th>คนเก็บ</Table.Th>
                <Table.Th ta="right">ใบ</Table.Th>
                <Table.Th ta="right">ตรวจแล้ว</Table.Th>
                <Table.Th>ช่วงวันที่บนใบ</Table.Th>
                <Table.Th>อัปเดตล่าสุด</Table.Th>
                <Table.Th w={32}></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sortedVisits.map((v) => {
                const dateRange =
                  v.earliest_doc_date && v.latest_doc_date
                    ? v.earliest_doc_date === v.latest_doc_date
                      ? v.earliest_doc_date
                      : `${v.earliest_doc_date} → ${v.latest_doc_date}`
                    : "—";
                return (
                  <Table.Tr
                    key={v.id}
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/visits/${v.id}`)}
                  >
                    <Table.Td>
                      <Group gap="xs">
                        <Badge size="lg" variant="light" color="grape">
                          {v.report_period ?? "—"}
                        </Badge>
                        <Text size="sm" c="dimmed">
                          {formatPeriod(v.report_period)}
                        </Text>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {v.rep_name || <Text c="dimmed">—</Text>}
                    </Table.Td>
                    <Table.Td ta="right">
                      <Badge
                        variant="light"
                        color={v.document_count > 0 ? "indigo" : "gray"}
                      >
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
                    <Table.Td>
                      <Text size="sm">{dateRange}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {format(new Date(v.updated_at), "yyyy-MM-dd HH:mm")}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <ChevronRight size={14} className="text-gray-400" />
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Paper>
      )}

      <Modal
        opened={addOpen}
        onClose={() => setAddOpen(false)}
        title="เพิ่มเดือนรายงาน"
        size="sm"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            ถ้าเดือนนี้มีอยู่แล้ว ระบบจะพาไปที่เดือนเดิมโดยไม่สร้างซ้ำ
          </Text>
          <MonthPickerInput
            label="เดือนรายงาน"
            value={pickerDate}
            onChange={(v) => setPickerDate(v ? new Date(v) : null)}
            maxDate={new Date()}
            minDate={new Date(2020, 0, 1)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAddOpen(false)}>
              ยกเลิก
            </Button>
            <Button
              onClick={handleAddMonth}
              loading={createMut.isPending}
              disabled={!pickerDate}
            >
              ไปที่เดือนนี้
            </Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}
