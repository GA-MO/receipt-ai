import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  Badge,
  Group,
  Loader,
  Paper,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useVisits } from "../api/queries";

export default function VisitsPage() {
  const { data: visits, isPending } = useVisits({ limit: 50 });

  return (
    <div>
      <Group justify="space-between" mb="md">
        <div>
          <Title order={2}>การเยี่ยมร้าน (Visits)</Title>
          <Text c="dimmed" mt={4}>
            แต่ละ visit = ใบเสร็จของร้านในเดือนรายงาน — สร้างอัตโนมัติจากหน้าอัปโหลด & จัดกลุ่ม
          </Text>
        </div>
      </Group>

      {isPending ? (
        <Loader />
      ) : !visits || visits.length === 0 ? (
        <Paper withBorder p="lg" radius="md">
          <Text c="dimmed" ta="center">
            ยังไม่มี visit —{" "}
            <Link to="/inbox" className="text-indigo-600 underline">
              โยนใบเสร็จที่หน้าอัปโหลด & จัดกลุ่ม
            </Link>{" "}
            แล้ว AI จะจัดร้านให้
          </Text>
        </Paper>
      ) : (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ร้านค้า</Table.Th>
                <Table.Th>เดือนรายงาน</Table.Th>
                <Table.Th>คนเก็บ</Table.Th>
                <Table.Th ta="right">ใบ</Table.Th>
                <Table.Th ta="right">ตรวจแล้ว</Table.Th>
                <Table.Th>ช่วงวันที่บนใบ</Table.Th>
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
                    <Table.Td>
                      {v.report_period ? (
                        <Badge variant="light" color="grape">{v.report_period}</Badge>
                      ) : (
                        <Text c="dimmed" size="sm">—</Text>
                      )}
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
