import { NavLink as RouterNavLink, Outlet, useLocation } from "react-router-dom";
import {
  AppShell,
  Badge,
  Burger,
  Group,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Calendar, FileText, Inbox, Receipt, Store, Trash2 } from "lucide-react";
import classes from "./Layout.module.css";
import { LearnedAliasesBadge } from "@/components/LearnedAliasesPanel";
import { useDashboard } from "@/api/queries";

const links = [
  { to: "/inbox", label: "อัปโหลด & จัดกลุ่ม", icon: Inbox, badgeKey: "inbox" as const },
  { to: "/stores", label: "ร้านค้า", icon: Store },
  { to: "/visits", label: "การเยี่ยมร้าน", icon: Calendar },
  { to: "/documents", label: "เอกสารทั้งหมด", icon: FileText },
  { to: "/trash", label: "ถังขยะ", icon: Trash2 },
] as const;

export default function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const dashboard = useDashboard();
  // Sidebar pill: things needing user attention today.
  const inboxCount = dashboard.data
    ? dashboard.data.counts.orphans +
      dashboard.data.counts.unknown_stores +
      dashboard.data.counts.non_receipts +
      dashboard.data.counts.errors +
      dashboard.data.counts.attention
    : 0;

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{
        width: 260,
        breakpoint: "lg",
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <AppShell.Header className={classes.headerBar}>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="lg"
              size="sm"
            />
            <ThemeIcon size="lg" radius="md" variant="gradient" gradient={{ from: "indigo", to: "violet" }}>
              <Receipt size={20} />
            </ThemeIcon>
            <div>
              <Text fw={700} size="sm" lh={1.2}>
                Receipt AI
              </Text>
              <Text size="xs" c="dimmed" lh={1.2}>
                Thai Receipt Intelligence
              </Text>
            </div>
          </Group>
          <Group gap="xs">
            <LearnedAliasesBadge />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className={classes.navbar} p="sm">
        <AppShell.Section grow className={classes.navbarMain}>
          {links.map((link) => {
            const { to, label, icon: Icon } = link;
            const active =
              to === "/inbox"
                ? location.pathname === "/" || location.pathname.startsWith("/inbox")
                : location.pathname.startsWith(to);
            const showBadge =
              "badgeKey" in link && link.badgeKey === "inbox" && inboxCount > 0;
            return (
              <RouterNavLink
                key={to}
                to={to}
                className={classes.link}
                data-active={active || undefined}
                onClick={close}
                style={{ marginBottom: 4 }}
              >
                <Icon className={classes.linkIcon} />
                <span style={{ flex: 1 }}>{label}</span>
                {showBadge && (
                  <Badge size="sm" variant="filled" color="indigo" radius="sm">
                    {inboxCount}
                  </Badge>
                )}
              </RouterNavLink>
            );
          })}
        </AppShell.Section>
        <AppShell.Section className={classes.footer}>
          <Text size="xs" ta="center" className={classes.footerText}>
            SBP AI Hackathon 2026
          </Text>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
