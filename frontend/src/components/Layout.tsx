import { useEffect } from "react";
import { NavLink as RouterNavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  AppShell,
  Badge,
  Burger,
  Group,
  Text,
  ActionIcon,
  Tooltip,
  useMantineColorScheme,
  useComputedColorScheme,
  ThemeIcon,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Bell, BellOff, Calendar, FileText, Inbox, Moon, Receipt, Store, Sun, Trash2 } from "lucide-react";
import classes from "./Layout.module.css";
import { useWebPush } from "@/hooks/useWebPush";
import { useToast } from "@/components/Toast";
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
  const { setColorScheme } = useMantineColorScheme();
  const colorScheme = useComputedColorScheme("light");
  const location = useLocation();
  const navigate = useNavigate();
  const { toast } = useToast();
  const push = useWebPush();
  const dashboard = useDashboard();
  // Sidebar pill: things needing user attention today.
  const inboxCount = dashboard.data
    ? dashboard.data.counts.orphans +
      dashboard.data.counts.unknown_stores +
      dashboard.data.counts.non_receipts +
      dashboard.data.counts.errors +
      dashboard.data.counts.attention
    : 0;

  const toggleColorScheme = () => {
    setColorScheme(colorScheme === "dark" ? "light" : "dark");
  };

  const togglePush = async () => {
    if (push.state === "enabled") {
      const ok = await push.disable();
      if (ok) toast("info", "ปิดการแจ้งเตือนแล้ว");
    } else if (push.state === "unsupported") {
      toast("error", "เบราว์เซอร์ไม่รองรับ Web Push");
    } else if (push.state === "permission-denied") {
      toast("error", "ถูกบล็อกใน browser — ต้องอนุญาตเองในตั้งค่า site");
    } else {
      const ok = await push.enable();
      if (ok) {
        toast("success", "เปิดการแจ้งเตือนแล้ว");
        // Fire a test push so the user confirms the end-to-end path works.
        await push.sendTest();
      } else if (push.error) {
        toast("error", push.error);
      }
    }
  };

  // Listen for SW → window navigation requests (user clicked a notification).
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const handler = (event: MessageEvent) => {
      const data = event.data as { type?: string; url?: string } | undefined;
      if (data?.type === "push-nav" && data.url) navigate(data.url);
    };
    navigator.serviceWorker.addEventListener("message", handler);
    return () => navigator.serviceWorker.removeEventListener("message", handler);
  }, [navigate]);

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
            <Tooltip
              label={
                push.state === "enabled"
                  ? "แจ้งเตือนเปิดอยู่ (คลิกเพื่อปิด)"
                  : push.state === "unsupported"
                    ? "เบราว์เซอร์ไม่รองรับ"
                    : push.state === "permission-denied"
                      ? "ถูกบล็อก — เปิดในตั้งค่า site"
                      : "เปิดการแจ้งเตือน (Web Push)"
              }
            >
              <ActionIcon
                variant={push.state === "enabled" ? "light" : "subtle"}
                color={push.state === "enabled" ? "indigo" : undefined}
                size="lg"
                onClick={togglePush}
                disabled={push.state === "loading" || push.state === "unsupported"}
                aria-label="Toggle web push notifications"
              >
                {push.state === "enabled" ? <Bell size={18} /> : <BellOff size={18} />}
              </ActionIcon>
            </Tooltip>
            <ActionIcon
              variant="subtle"
              size="lg"
              onClick={toggleColorScheme}
              aria-label="Toggle color scheme"
              className={classes.toggleBtn}
            >
              {colorScheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </ActionIcon>
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
