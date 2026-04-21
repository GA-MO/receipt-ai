/* Service Worker for Web Push notifications.
 * Keep this file framework-free: the browser executes it outside the Vite bundle.
 */

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { title: "แจ้งเตือน", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Receipt AI";
  const options = {
    body: data.body || "",
    icon: data.icon || "/vite.svg",
    badge: data.badge || "/vite.svg",
    tag: data.tag || undefined,
    data: { url: data.url || "/" },
    requireInteraction: data.requireInteraction === true,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        try {
          const clientUrl = new URL(client.url);
          if (client.focus) {
            client.postMessage({ type: "push-nav", url });
            client.focus();
            return;
          }
        } catch (_) {
          // ignore
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    }),
  );
});
