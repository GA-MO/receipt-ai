/**
 * Web Push registration hook.
 *
 * Lifecycle:
 *   1. On mount, check browser support + existing subscription → set `state`.
 *   2. `enable()` — request permission, register SW, subscribe, POST to backend.
 *   3. `disable()` — unsubscribe locally + tell backend to delete.
 *   4. `sendTest()` — trigger a test push (only useful when enabled).
 */

import { useCallback, useEffect, useState } from "react";
import {
  getPushPublicKey,
  sendTestPush,
  subscribePush,
  unsubscribePush,
} from "@/api/client";

export type PushState =
  | "unsupported"
  | "unregistered"
  | "permission-denied"
  | "enabled"
  | "disabled"
  | "loading";

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function isSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function useWebPush() {
  const [state, setState] = useState<PushState>("loading");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isSupported()) {
      setState("unsupported");
      return;
    }
    if (Notification.permission === "denied") {
      setState("permission-denied");
      return;
    }
    const reg = await navigator.serviceWorker.getRegistration("/sw.js");
    if (!reg) {
      setState("unregistered");
      return;
    }
    const sub = await reg.pushManager.getSubscription();
    setState(sub ? "enabled" : "disabled");
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const enable = useCallback(async () => {
    if (!isSupported()) {
      setError("เบราว์เซอร์ไม่รองรับ Web Push");
      return false;
    }
    setError(null);
    setState("loading");
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState("permission-denied");
        setError("ไม่ได้รับอนุญาตให้ส่งแจ้งเตือน");
        return false;
      }
      const reg =
        (await navigator.serviceWorker.getRegistration("/sw.js")) ??
        (await navigator.serviceWorker.register("/sw.js"));
      const { public_key } = await getPushPublicKey();
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(public_key),
        });
      }
      await subscribePush(sub.toJSON() as PushSubscriptionJSON);
      setState("enabled");
      return true;
    } catch (err) {
      console.error("Push enable failed", err);
      setError(err instanceof Error ? err.message : String(err));
      setState("disabled");
      return false;
    }
  }, []);

  const disable = useCallback(async () => {
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await unsubscribePush(sub.endpoint);
        await sub.unsubscribe();
      }
      setState("disabled");
      return true;
    } catch (err) {
      console.error("Push disable failed", err);
      setError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }, []);

  const sendTest = useCallback(async () => {
    try {
      await sendTestPush({
        title: "ทดสอบ Web Push",
        body: "หากเห็นข้อความนี้ แสดงว่าตั้งค่าสำเร็จ 🎉",
        url: "/",
      });
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }, []);

  return { state, error, enable, disable, sendTest, refresh };
}
