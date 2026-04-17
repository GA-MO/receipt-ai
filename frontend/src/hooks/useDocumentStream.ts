/**
 * Subscribe to a document's processing status via Server-Sent Events.
 *
 * Automatically closes the EventSource when:
 *  - the component unmounts
 *  - the document reaches a terminal status (extracted / reviewed / error)
 *
 * Each status event invalidates the document query so consumers using
 * `useDocument(id)` see the updated record without extra work.
 */

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { qk } from "../api/queries";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export interface DocumentStatusEvent {
  status: string;
  needs_review?: boolean;
  error_message?: string | null;
}

const TERMINAL = new Set(["extracted", "reviewed", "error"]);

export function useDocumentStream(
  id: string | undefined,
  opts?: {
    enabled?: boolean;
    onEvent?: (event: DocumentStatusEvent) => void;
  },
) {
  const qc = useQueryClient();
  const onEventRef = useRef(opts?.onEvent);
  onEventRef.current = opts?.onEvent;

  useEffect(() => {
    if (!id || opts?.enabled === false) return;

    const source = new EventSource(`${API_BASE}/documents/${id}/events`);
    let closed = false;

    const close = () => {
      if (!closed) {
        closed = true;
        source.close();
      }
    };

    source.addEventListener("status", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as DocumentStatusEvent;
        qc.invalidateQueries({ queryKey: qk.document(id) });
        onEventRef.current?.(data);
        if (TERMINAL.has(data.status)) close();
      } catch {
        /* ignore malformed payload */
      }
    });

    source.onerror = () => {
      // EventSource auto-reconnects; close manually if already terminal.
      if (source.readyState === EventSource.CLOSED) close();
    };

    return () => close();
  }, [id, opts?.enabled, qc]);
}
