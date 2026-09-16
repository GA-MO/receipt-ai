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
  Switch,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { Brain, Trash2 } from "lucide-react";
import {
  useAliasSettings,
  useAliasStats,
  useSetAliasSettings,
  useDeleteProductAlias,
  useProductAliases,
} from "@/api/queries";
import { useToast } from "@/components/Toast";
import type { MerchantAliasItem } from "@/api/client";

export function LearnedAliasesBadge() {
  const [open, setOpen] = useState(false);
  const { data: stats } = useAliasStats();
  const { data: settings } = useAliasSettings();
  const total = stats?.products.total_aliases ?? 0;
  const hits = stats?.products.total_hits ?? 0;
  const off = settings?.use_learned === false;

  if (total === 0) return null;

  return (
    <>
      <Tooltip label={off ? "ปิดการใช้สิ่งที่เรียนรู้อยู่ — แตะเพื่อเปิด" : `${total} สินค้า · ใช้ไป ${hits} ครั้ง`}>
        <Badge
          leftSection={<Brain size={12} />}
          size="sm"
          variant={off ? "outline" : "gradient"}
          color={off ? "gray" : undefined}
          gradient={{ from: "indigo", to: "violet" }}
          style={{ cursor: "pointer" }}
          onClick={() => setOpen(true)}
        >
          เรียนรู้แล้ว {total}{off ? " · ปิดอยู่" : ""}
        </Badge>
      </Tooltip>
      <LearnedAliasesModal opened={open} onClose={() => setOpen(false)} />
    </>
  );
}

export function LearnedAliasesModal({
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

        <UseLearnedSwitch />

        <ProductList />

        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>ปิด</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Demo switch — read receipts with or without what has been learned, so
 *  the difference is visible on the same image. Learning itself stays on. */
function UseLearnedSwitch() {
  const { data } = useAliasSettings();
  const set = useSetAliasSettings();
  const on = data?.use_learned ?? true;
  return (
    <Paper withBorder p="sm">
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text size="sm" fw={600}>ใช้สิ่งที่เรียนรู้ตอนอ่านใบเสร็จ</Text>
          <Text size="xs" c="dimmed">
            {on
              ? "เปิดอยู่ — AI เห็นคำย่อเหล่านี้ตอนอ่าน และบรรทัดที่ตรงจะขึ้น ✓"
              : "ปิดอยู่ — AI อ่านจาก catalog ล้วน ๆ (ไว้เทียบให้เห็นความต่าง) ระบบยังจำสิ่งที่คุณแก้ต่อไป"}
          </Text>
        </div>
        <Switch
          checked={on}
          disabled={set.isPending || data == null}
          onChange={(e) => set.mutate(e.currentTarget.checked)}
          size="md"
          onLabel="เปิด"
          offLabel="ปิด"
        />
      </Group>
    </Paper>
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
