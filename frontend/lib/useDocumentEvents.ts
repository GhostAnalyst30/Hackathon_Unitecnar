"use client";

import { useEffect, useRef } from "react";
import { API_BASE } from "./api";
import type { DocumentEvent } from "./types";

/** Se suscribe al stream SSE del backend y llama al callback con cada evento. */
export function useDocumentEvents(onEvent: (event: DocumentEvent) => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/api/events`);
    source.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as DocumentEvent;
        if (parsed.type === "document") handlerRef.current(parsed);
      } catch {
        /* keepalive u otro formato */
      }
    };
    return () => source.close();
  }, []);
}
