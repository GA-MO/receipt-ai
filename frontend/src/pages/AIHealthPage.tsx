/**
 * Admin/observability page surfacing self-monitoring signals from the
 * extraction pipeline:
 *   - Catalog Gaps   — Gemini-emitted product_codes not found in catalog
 *   - Typo Recoveries — codes that smart-fallback recovered via name match
 *
 * End-users should not need this view. It lives outside the dashboard so
 * the dashboard stays focused on business analytics.
 */

import { useState } from "react";
import {
  Badge,
  Group,
  Loader,
  Paper,
  Stack,
  Tabs,
  Table,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { AlertCircle, Brain, CheckCircle2, PackageSearch } from "lucide-react";
import { useCatalogGaps, useTypoRecoveries } from "@/api/queries";

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (!then) return "ไม่ทราบ";
  const now = Date.now();
  const sec = Math.max(1, Math.round((now - then) / 1000));
  if (sec < 60) return `${sec} วินาทีที่แล้ว`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} นาทีที่แล้ว`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ชั่วโมงที่แล้ว`;
  const day = Math.round(hr / 24);
  return `${day} วันที่แล้ว`;
}

export default function AIHealthPage() {
  const [tab, setTab] = useState<"gaps" | "typos">("gaps");
  const catalogGapsQuery = useCatalogGaps(30);
  const typoRecoveriesQuery = useTypoRecoveries(30);

  const gapCount = catalogGapsQuery.data?.gaps.length ?? 0;
  const gapHits = (catalogGapsQuery.data?.gaps ?? []).reduce((s, g) => s + g.hit_count, 0);
  const typoPatterns = typoRecoveriesQuery.data?.recoveries.length ?? 0;
  const typoHits = (typoRecoveriesQuery.data?.recoveries ?? []).reduce((s, r) => s + r.hit_count, 0);

  return (
    <>
      <Group gap="sm" mb="xs">
        <ThemeIcon size="lg" radius="md" color="indigo" variant="light">
          <Brain size={20} />
        </ThemeIcon>
        <div>
          <Title order={2}>AI Health</Title>
          <Text c="dimmed" size="sm">
            ระบบเฝ้าตัวเอง 30 วันล่าสุด — ใช้ข้อมูลที่นี่ตัดสินว่าควรเพิ่ม SKU หรือปรับ prompt
          </Text>
        </div>
      </Group>

      <Group grow mb="lg" wrap="wrap">
        <Paper withBorder p="md">
          <Group gap="md" wrap="nowrap">
            <ThemeIcon
              size={42}
              radius="md"
              color={gapCount > 0 ? "orange" : "green"}
              variant="light"
            >
              <PackageSearch size={20} />
            </ThemeIcon>
            <div style={{ flex: 1 }}>
              <Group gap={6} align="baseline">
                <Text size="xl" fw={700} c={gapCount > 0 ? "orange" : "green"}>
                  {gapCount}
                </Text>
                {gapHits > 0 && (
                  <Text size="sm" c="dimmed">({gapHits} hits)</Text>
                )}
              </Group>
              <Text size="sm" fw={500}>Catalog Gaps</Text>
              <Text size="xs" c="dimmed">SKU code ที่ AI เห็นแต่ระบบไม่มี</Text>
            </div>
          </Group>
        </Paper>

        <Paper withBorder p="md">
          <Group gap="md" wrap="nowrap">
            <ThemeIcon
              size={42}
              radius="md"
              color={typoPatterns > 0 ? "yellow" : "green"}
              variant="light"
            >
              <AlertCircle size={20} />
            </ThemeIcon>
            <div style={{ flex: 1 }}>
              <Group gap={6} align="baseline">
                <Text size="xl" fw={700} c={typoPatterns > 0 ? "yellow.7" : "green"}>
                  {typoPatterns}
                </Text>
                {typoHits > 0 && (
                  <Text size="sm" c="dimmed">({typoHits} hits)</Text>
                )}
              </Group>
              <Text size="sm" fw={500}>Typo Recoveries</Text>
              <Text size="xs" c="dimmed">AI พิมพ์ code ผิด แต่กู้ได้จากชื่อ</Text>
            </div>
          </Group>
        </Paper>
      </Group>

      <Paper withBorder p="md">
        <Tabs value={tab} onChange={(v) => v && setTab(v as "gaps" | "typos")}>
          <Tabs.List grow>
            <Tabs.Tab value="gaps" leftSection={<PackageSearch size={14} />}>
              Catalog Gaps ({gapCount})
            </Tabs.Tab>
            <Tabs.Tab value="typos" leftSection={<AlertCircle size={14} />}>
              Typo Recoveries ({typoPatterns})
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="gaps" pt="md">
            <Text c="dimmed" size="xs" mb="sm">
              SKU code ที่ AI ตอบมาแต่ไม่อยู่ในระบบ — เพิ่ม SKU แล้วรายการนี้จะหายอัตโนมัติ
            </Text>
            {catalogGapsQuery.isLoading ? (
              <Group justify="center" py="md"><Loader size="sm" /></Group>
            ) : !catalogGapsQuery.data || catalogGapsQuery.data.gaps.length === 0 ? (
              <Stack align="center" py="xl" gap="xs">
                <ThemeIcon size={48} radius="xl" color="green" variant="light">
                  <CheckCircle2 size={24} />
                </ThemeIcon>
                <Text c="green" fw={500}>ไม่พบ catalog gap</Text>
                <Text c="dimmed" size="sm">AI ทุกครั้งตรงกับ catalog ในระบบ</Text>
              </Stack>
            ) : (
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>SKU code</Table.Th>
                    <Table.Th>ชื่อสินค้าที่ AI อ่าน</Table.Th>
                    <Table.Th ta="right">เจอ</Table.Th>
                    <Table.Th>ล่าสุด</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {catalogGapsQuery.data.gaps.map((g) => (
                    <Table.Tr key={`${g.emitted_code}-${g.product_name ?? ""}`}>
                      <Table.Td><Text size="sm" ff="monospace">{g.emitted_code}</Text></Table.Td>
                      <Table.Td><Text size="sm">{g.product_name ?? "-"}</Text></Table.Td>
                      <Table.Td ta="right">
                        <Badge color={g.hit_count >= 3 ? "orange" : "gray"} variant="light">{g.hit_count}</Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">{g.last_seen ? formatRelativeTime(g.last_seen) : "-"}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Tabs.Panel>

          <Tabs.Panel value="typos" pt="md">
            <Text c="dimmed" size="xs" mb="sm">
              AI พิมพ์ SKU code ผิด แต่ระบบกู้คืนจากชื่อ — pattern ซ้ำๆ = ควรเพิ่ม hint ใน prompt
            </Text>
            {typoRecoveriesQuery.isLoading ? (
              <Group justify="center" py="md"><Loader size="sm" /></Group>
            ) : !typoRecoveriesQuery.data || typoRecoveriesQuery.data.recoveries.length === 0 ? (
              <Stack align="center" py="xl" gap="xs">
                <ThemeIcon size={48} radius="xl" color="green" variant="light">
                  <CheckCircle2 size={24} />
                </ThemeIcon>
                <Text c="green" fw={500}>ไม่พบ typo</Text>
                <Text c="dimmed" size="sm">AI พิมพ์รหัสตรงทุกครั้ง</Text>
              </Stack>
            ) : (
              <Table highlightOnHover verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>AI พิมพ์ผิด</Table.Th>
                    <Table.Th>กู้เป็น</Table.Th>
                    <Table.Th>สินค้า</Table.Th>
                    <Table.Th ta="right">เจอ</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {typoRecoveriesQuery.data.recoveries.map((r) => (
                    <Table.Tr key={`${r.emitted_code}-${r.recovered_code}-${r.product_name ?? ""}`}>
                      <Table.Td><Text size="sm" ff="monospace" c="red.7">{r.emitted_code}</Text></Table.Td>
                      <Table.Td><Text size="sm" ff="monospace" c="green.7">{r.recovered_code}</Text></Table.Td>
                      <Table.Td><Text size="sm">{r.product_name ?? "-"}</Text></Table.Td>
                      <Table.Td ta="right">
                        <Badge color={r.hit_count >= 3 ? "yellow" : "gray"} variant="light">{r.hit_count}</Badge>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Tabs.Panel>
        </Tabs>
      </Paper>
    </>
  );
}
