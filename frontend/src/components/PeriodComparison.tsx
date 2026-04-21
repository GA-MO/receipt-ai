/**
 * "This period vs previous" card for the Dashboard.
 *
 * Presents totals, document count, and signed deltas (฿ and %) with a small
 * SegmentedControl to switch between 7d / 30d / this month / this year.
 */

import { useState } from "react";
import {
  Group,
  Paper,
  SegmentedControl,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { ArrowDown, ArrowUp, CalendarRange, Minus } from "lucide-react";
import { usePeriodComparison } from "@/api/queries";

type Period = "7d" | "30d" | "month" | "year";

const PERIOD_LABEL: Record<Period, string> = {
  "7d": "7 วัน",
  "30d": "30 วัน",
  month: "เดือนนี้",
  year: "ปีนี้",
};

function formatBaht(n: number): string {
  return `฿${n.toLocaleString("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function DeltaBadge({ pct, absLabel, inverse = false }: { pct: number | null; absLabel: string; inverse?: boolean }) {
  if (pct === null) {
    return (
      <Group gap={4}>
        <ThemeIcon size="sm" radius="xl" variant="light" color="gray">
          <Minus size={12} />
        </ThemeIcon>
        <Text size="xs" c="dimmed">ช่วงก่อนหน้าไม่มีข้อมูล</Text>
      </Group>
    );
  }
  const up = pct > 0;
  const flat = pct === 0;
  const goodIsUp = !inverse;
  const color = flat ? "gray" : up === goodIsUp ? "green" : "red";
  const Icon = flat ? Minus : up ? ArrowUp : ArrowDown;

  return (
    <Group gap={4}>
      <ThemeIcon size="sm" radius="xl" variant="light" color={color}>
        <Icon size={12} />
      </ThemeIcon>
      <Text size="xs" fw={600} c={color}>
        {up ? "+" : ""}{pct}%
      </Text>
      <Text size="xs" c="dimmed">({absLabel})</Text>
    </Group>
  );
}

export function PeriodComparisonCard() {
  const [period, setPeriod] = useState<Period>("month");
  const { data, isPending } = usePeriodComparison(period);

  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="md" wrap="wrap">
        <Group gap="xs">
          <ThemeIcon size="lg" radius="md" variant="light" color="indigo">
            <CalendarRange size={18} />
          </ThemeIcon>
          <div>
            <Text fw={700} size="sm">เทียบช่วงเวลา</Text>
            <Text size="xs" c="dimmed">ช่วงนี้เทียบกับช่วงก่อนหน้า</Text>
          </div>
        </Group>
        <SegmentedControl
          size="xs"
          value={period}
          onChange={(v) => setPeriod(v as Period)}
          data={[
            { value: "7d", label: "7 วัน" },
            { value: "30d", label: "30 วัน" },
            { value: "month", label: "เดือน" },
            { value: "year", label: "ปี" },
          ]}
        />
      </Group>

      {isPending || !data ? (
        <Skeleton h={120} />
      ) : (
        <Group grow align="stretch" wrap="nowrap">
          <Stack gap={4}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              ช่วงนี้ ({PERIOD_LABEL[period]})
            </Text>
            <Text size="xl" fw={700}>{formatBaht(data.current.total)}</Text>
            <Text size="xs" c="dimmed">
              {data.current.count} เอกสาร · {data.current.start} → {data.current.end}
            </Text>
            <DeltaBadge
              pct={data.delta.total_pct}
              absLabel={`${data.delta.total_abs >= 0 ? "+" : ""}${formatBaht(data.delta.total_abs).replace("฿", "฿")}`}
            />
          </Stack>
          <Stack gap={4} style={{ borderLeft: "1px solid var(--mantine-color-default-border)", paddingLeft: "var(--mantine-spacing-md)" }}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              ช่วงก่อนหน้า
            </Text>
            <Text size="xl" fw={700} c="dimmed">{formatBaht(data.previous.total)}</Text>
            <Text size="xs" c="dimmed">
              {data.previous.count} เอกสาร · {data.previous.start} → {data.previous.end}
            </Text>
            <DeltaBadge
              pct={data.delta.count_pct}
              absLabel={`${data.delta.count_abs >= 0 ? "+" : ""}${data.delta.count_abs} เอกสาร`}
            />
          </Stack>
        </Group>
      )}
    </Paper>
  );
}
