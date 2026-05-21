import { useState } from "react";
import {
  ActionIcon,
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
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import {
  useCreateStore,
  useDeleteStore,
  useStores,
  useUpdateStore,
} from "../api/queries";
import type { StoreListItem } from "../api/client";
import { useToast } from "@/components/Toast";

export default function StoresPage() {
  const [q, setQ] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const { data: stores, isPending } = useStores({
    q: q || undefined,
    include_inactive: includeInactive,
  });
  const [editing, setEditing] = useState<StoreListItem | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <div className="max-w-5xl mx-auto">
      <Group justify="space-between" mb="md">
        <div>
          <Title order={2}>Store master</Title>
          <Text c="dimmed" mt={4}>
            รายชื่อร้านค้าในระบบ — ใช้ตอนสร้าง visit เพื่อแมตช์ใบเสร็จเข้าร้านที่ถูกต้อง
          </Text>
        </div>
        <Button leftSection={<Plus size={16} />} onClick={() => setCreating(true)}>
          เพิ่มร้านใหม่
        </Button>
      </Group>

      <Card withBorder radius="md" mb="md">
        <Group>
          <TextInput
            flex={1}
            placeholder="ค้นหาด้วยชื่อ, code, หรือชื่อ normalized"
            leftSection={<Search size={14} />}
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
          />
          <Button
            variant={includeInactive ? "filled" : "light"}
            size="sm"
            onClick={() => setIncludeInactive((v) => !v)}
          >
            {includeInactive ? "รวม inactive" : "เฉพาะ active"}
          </Button>
        </Group>
      </Card>

      {isPending ? (
        <Loader />
      ) : !stores || stores.length === 0 ? (
        <Paper withBorder p="lg" radius="md">
          <Text c="dimmed" ta="center">
            ไม่พบร้าน — กด "เพิ่มร้านใหม่" ด้านบน
          </Text>
        </Paper>
      ) : (
        <Paper withBorder radius="md">
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>ชื่อร้าน</Table.Th>
                <Table.Th>Code</Table.Th>
                <Table.Th>Normalized</Table.Th>
                <Table.Th ta="right">Visits</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th w={80}></Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {stores.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    <Text fw={500}>{s.name}</Text>
                    {s.address && (
                      <Text size="xs" c="dimmed">
                        {s.address}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{s.code || <Text c="dimmed">—</Text>}</Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed">
                      {s.normalized_name || "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td ta="right">
                    <Badge variant="light" color={s.visit_count > 0 ? "indigo" : "gray"}>
                      {s.visit_count}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={s.active ? "green" : "gray"} variant="light">
                      {s.active ? "active" : "inactive"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <ActionIcon variant="subtle" onClick={() => setEditing(s)} aria-label="แก้ไข">
                        <Pencil size={14} />
                      </ActionIcon>
                      <DeleteButton store={s} />
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}

      <StoreFormModal
        opened={creating}
        onClose={() => setCreating(false)}
        title="เพิ่มร้านใหม่"
        mode="create"
      />
      <StoreFormModal
        opened={editing !== null}
        onClose={() => setEditing(null)}
        title="แก้ไขร้าน"
        mode="edit"
        store={editing ?? undefined}
      />
    </div>
  );
}

function DeleteButton({ store }: { store: StoreListItem }) {
  const deleteMut = useDeleteStore();
  const { toast } = useToast();

  const handleClick = async () => {
    const msg = store.visit_count
      ? `ร้านนี้มี ${store.visit_count} visit — จะถูกตั้งเป็น inactive แทนการลบ ต้องการดำเนินการต่อหรือไม่?`
      : `ลบร้าน "${store.name}" ทันที?`;
    if (!confirm(msg)) return;
    try {
      const res = await deleteMut.mutateAsync(store.id);
      toast(
        "success",
        res.status === "deleted" ? "ลบร้านสำเร็จ" : "ตั้งเป็น inactive แล้ว",
      );
    } catch (err) {
      const m = err instanceof Error ? err.message : "ลบล้มเหลว";
      toast("error", m);
    }
  };

  return (
    <ActionIcon
      variant="subtle"
      color="red"
      onClick={handleClick}
      loading={deleteMut.isPending}
      aria-label="ลบ"
    >
      <Trash2 size={14} />
    </ActionIcon>
  );
}

function StoreFormModal({
  opened,
  onClose,
  title,
  mode,
  store,
}: {
  opened: boolean;
  onClose: () => void;
  title: string;
  mode: "create" | "edit";
  store?: StoreListItem;
}) {
  const { toast } = useToast();
  const createMut = useCreateStore();
  const updateMut = useUpdateStore(store?.id ?? "");

  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [normalized, setNormalized] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");

  // Initialize form on open.
  const setFromStore = () => {
    setName(store?.name ?? "");
    setCode(store?.code ?? "");
    setNormalized(store?.normalized_name ?? "");
    setAddress(store?.address ?? "");
    setNotes(store?.notes ?? "");
  };

  // Reset whenever modal opens.
  const handleEnter = () => {
    if (mode === "edit") setFromStore();
    else {
      setName("");
      setCode("");
      setNormalized("");
      setAddress("");
      setNotes("");
    }
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast("error", "กรุณากรอกชื่อร้าน");
      return;
    }
    try {
      if (mode === "create") {
        await createMut.mutateAsync({
          name: name.trim(),
          code: code.trim() || null,
          normalized_name: normalized.trim() || null,
          address: address.trim() || null,
          notes: notes.trim() || null,
        });
        toast("success", "เพิ่มร้านสำเร็จ");
      } else {
        await updateMut.mutateAsync({
          name: name.trim(),
          code: code.trim() || null,
          normalized_name: normalized.trim() || null,
          address: address.trim() || null,
          notes: notes.trim() || null,
        });
        toast("success", "บันทึกแล้ว");
      }
      onClose();
    } catch (err) {
      const m = err instanceof Error ? err.message : "บันทึกล้มเหลว";
      toast("error", m);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      onEnterTransitionEnd={handleEnter}
      title={title}
      size="md"
    >
      <Stack>
        <TextInput
          label="ชื่อร้าน"
          required
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Group grow>
          <TextInput
            label="Code (optional)"
            placeholder="เช่น RT-001"
            value={code}
            onChange={(e) => setCode(e.currentTarget.value)}
          />
          <TextInput
            label="Normalized name"
            description="ใช้แมตช์กับ merchant_normalized จากใบเสร็จ"
            value={normalized}
            onChange={(e) => setNormalized(e.currentTarget.value)}
          />
        </Group>
        <TextInput
          label="ที่อยู่ (optional)"
          value={address}
          onChange={(e) => setAddress(e.currentTarget.value)}
        />
        <Textarea
          label="โน้ต (optional)"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            ยกเลิก
          </Button>
          <Button
            onClick={handleSubmit}
            loading={createMut.isPending || updateMut.isPending}
          >
            บันทึก
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
