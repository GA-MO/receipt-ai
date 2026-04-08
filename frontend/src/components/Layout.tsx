import { NavLink as RouterNavLink, Outlet, useLocation } from "react-router-dom";
import {
  AppShell,
  Burger,
  Group,
  Text,
  ActionIcon,
  useMantineColorScheme,
  useComputedColorScheme,
  ThemeIcon,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { BarChart3, Camera, FileText, Moon, Receipt, Sun, Upload } from "lucide-react";
import classes from "./Layout.module.css";

const links = [
  { to: "/", label: "อัปโหลด", icon: Upload },
  { to: "/documents", label: "เอกสารทั้งหมด", icon: FileText },
  { to: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { to: "/capture", label: "ถ่ายเอกสาร", icon: Camera },
] as const;

export default function Layout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { setColorScheme } = useMantineColorScheme();
  const colorScheme = useComputedColorScheme("light");
  const location = useLocation();

  const toggleColorScheme = () => {
    setColorScheme(colorScheme === "dark" ? "light" : "dark");
  };

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
      </AppShell.Header>

      <AppShell.Navbar className={classes.navbar} p="sm">
        <AppShell.Section grow className={classes.navbarMain}>
          {links.map(({ to, label, icon: Icon }) => {
            const active = to === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(to);
            return (
              <RouterNavLink
                key={to}
                to={to}
                end={to === "/"}
                className={classes.link}
                data-active={active || undefined}
                onClick={close}
                style={{ marginBottom: 4 }}
              >
                <Icon className={classes.linkIcon} />
                <span>{label}</span>
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
