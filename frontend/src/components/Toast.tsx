import { useCallback } from "react";
import { notifications } from "@mantine/notifications";

const COLOR_MAP = {
  success: "green",
  error: "red",
  warning: "yellow",
  info: "blue",
} as const;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function useToast() {
  const toast = useCallback(
    (type: "success" | "error" | "warning" | "info", message: string) => {
      notifications.show({
        message,
        color: COLOR_MAP[type],
        autoClose: 4000,
      });
    },
    [],
  );

  return { toast };
}
