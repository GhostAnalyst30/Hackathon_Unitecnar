"use client";

import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { AGENT_LABELS } from "@/lib/labels";
import type { ProcessLog } from "@/lib/types";

const AGENT_TONE: Record<string, string> = {
  ingest: "border-[#c4b79d] bg-[#f4eee3] text-ink-soft",
  reader: "border-[var(--hl-importante-border)] bg-[var(--hl-importante)] text-[#1e3a5f]",
  contradictions: "border-[var(--hl-contradiccion-border)] bg-[var(--hl-contradiccion)] text-[#7f1d1d]",
  references: "border-[var(--hl-referencia-border)] bg-[var(--hl-referencia)] text-[#4c1d95]",
  classifier: "border-[var(--hl-alerta-border)] bg-[var(--hl-alerta)] text-[#78350f]",
};

export function AgentProcessFeed({
  logs,
  busy,
}: {
  logs: ProcessLog[];
  busy: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (!logs.length && !busy) return null;

  return (
    <div className="flex max-h-56 min-h-0 flex-col overflow-hidden border-b border-line bg-paper-raised/90">
      <p className="px-4 pt-2.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
        Proceso de los agentes
        {busy && (
          <span className="ml-2 inline-flex items-center gap-1 font-medium normal-case tracking-normal text-warn">
            <Loader2 className="h-3 w-3 animate-spin" /> en curso
          </span>
        )}
      </p>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-4 py-2">
        {logs.map((log) => (
          <div key={log.id} className="flex gap-2 text-xs leading-relaxed">
            <span
              className={`mt-0.5 shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                AGENT_TONE[log.agent] ?? "border-line bg-paper-sunken text-ink-soft"
              }`}
            >
              {AGENT_LABELS[log.agent] ?? log.agent}
            </span>
            <p className="text-ink-soft">{log.message}</p>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
