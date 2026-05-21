/**
 * Floating badge + modal showing product-name corrections the system has
 * "learned" from operators. (Merchant-name corrections used to be tracked
 * here too but are now handled via the Store master, so only products
 * remain.) Clicking opens a list where each row can be deleted.
 */

import { useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { Brain, Trash2 } from "lucide-react";
import {
  useAliasStats,
  useDeleteProductAlias,
  useProductAliases,
} from "@/api/queries";
import { useToast } from "@/components/Toast";
import type { MerchantAliasItem } from "@/api/client";

export function LearnedAliasesBadge() {
  const [open, setOpen] = useState(false);
  const { data: stats } = useAliasStats();
  const total = stats?.products.total_aliases ?? 0;
  const hits = stats?.products.total_hits ?? 0;

  if (total === 0) return null;

  return (
    <>
      <Tooltip label={`${total} สินค้า · ใช้ไป ${hits} ครั้ง`}>
        <Badge
          leftSection={<Brain size={12} />}
          size="sm"
          variant="gradient"
          gradient={{ from: "indigo", to: "violet" }}
          style={{ cursor: "pointer" }}
          onClick={() => setOpen(true)}
        >
          เรียนรู้แล้ว {total}
        </Badge>
      </Tooltip>
      <LearnedAliasesModal opened={open} onClose={() => setOpen(false)} />
    </>
  );
}

function LearnedAliasesModal({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <Brain size={18} />
          <Text fw={600}>สินค้าที่ AI เรียนรู้จากคุณ</Text>
        </Group>
      }
      size="lg"
      centered
    >
      <Stack gap="sm">
        <Paper withBorder p="sm" bg="var(--mantine-color-indigo-0)">
          <Text size="xs" c="dimmed">
            เมื่อคุณแก้ชื่อสินค้าในใบเสร็จ ระบบจะจำไว้ — ครั้งถัดไปที่ AI
            เจอข้อความเดิมจะเติมให้อัตโนมัติ
          </Text>
        </Paper>

        <ProductList />

        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>ปิด</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function AliasTable({
  rows,
  loading,
  onDelete,
  emptyHint,
}: {
  rows: MerchantAliasItem[];
  loading: boolean;
  onDelete: (id: string) => void;
  emptyHint: string;
}) {
  if (loading) {
    return <Text c="dimmed" ta="center" py="lg">กำลังโหลด...</Text>;
  }
  if (rows.length === 0) {
    return <Text c="dimmed" ta="center" py="lg">{emptyHint}</Text>;
  }
  return (
    <ScrollArea h={360}>
      <Table striped highlightOnHover stickyHeader>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>AI อ่านได้</Table.Th>
            <Table.Th>คุณแก้เป็น</Table.Th>
            <Table.Th w={100}>หมวดหมู่</Table.Th>
            <Table.Th w={60} ta="right">ใช้ไป</Table.Th>
            <Table.Th w={40} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((a) => (
            <Table.Tr key={a.id}>
              <Table.Td>
                <Text size="sm" c="dimmed" lineClamp={1}>{a.source_text}</Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" fw={500} lineClamp={1}>{a.canonical_name}</Text>
              </Table.Td>
              <Table.Td>
                {a.category ? (
                  <Badge size="xs" variant="light">{a.category}</Badge>
                ) : (
                  <Text size="xs" c="dimmed">-</Text>
                )}
              </Table.Td>
              <Table.Td ta="right">
                <Text size="xs" ff="monospace">{a.hit_count}x</Text>
              </Table.Td>
              <Table.Td>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="red"
                  onClick={() => onDelete(a.id)}
                  aria-label="ลบ"
                >
                  <Trash2 size={14} />
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function ProductList() {
  const { data = [], isPending } = useProductAliases(200);
  const del = useDeleteProductAlias();
  const { toast } = useToast();
  return (
    <AliasTable
      rows={data}
      loading={isPending}
      onDelete={async (id) => {
        try { await del.mutateAsync(id); toast("success", "ลบแล้ว"); }
        catch { toast("error", "ลบไม่สำเร็จ"); }
      }}
      emptyHint="ยังไม่มีสินค้าที่เรียนรู้ — ลองแก้ชื่อสินค้าในรายการ"
    />
  );
}
