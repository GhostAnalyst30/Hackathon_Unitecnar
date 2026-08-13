import type { DocumentStatus, FindingKind } from "./types";

export const STATUS_META: Record<
  DocumentStatus,
  { label: string; tone: "muted" | "busy" | "review" | "ok" | "bad" }
> = {
  queued: { label: "En cola", tone: "busy" },
  extracting: { label: "Extrayendo texto", tone: "busy" },
  analyzing: { label: "Agentes analizando", tone: "busy" },
  awaiting_review: { label: "Esperando tu revisión", tone: "review" },
  validated: { label: "Validado", tone: "ok" },
  discarded: { label: "Descartado", tone: "bad" },
  error: { label: "Error", tone: "bad" },
};

export const KIND_META: Record<
  FindingKind,
  { label: string; className: string; dot: string }
> = {
  importante: {
    label: "Importante",
    className: "hl-importante",
    dot: "bg-[var(--hl-importante-border)]",
  },
  alerta: {
    label: "Alerta",
    className: "hl-alerta",
    dot: "bg-[var(--hl-alerta-border)]",
  },
  contradiccion: {
    label: "Contradicción",
    className: "hl-contradiccion",
    dot: "bg-[var(--hl-contradiccion-border)]",
  },
  inconsistencia: {
    label: "Inconsistencia",
    className: "hl-inconsistencia",
    dot: "bg-[var(--hl-inconsistencia-border)]",
  },
  referencia: {
    label: "Referencia",
    className: "hl-referencia",
    dot: "bg-[var(--hl-referencia-border)]",
  },
};

export const CLASSIFICATION_META: Record<
  string,
  { label: string; className: string }
> = {
  aprobable: { label: "Aprobable", className: "text-ok" },
  revisar: { label: "Revisar con cuidado", className: "text-warn" },
  alto_riesgo: { label: "Alto riesgo", className: "text-danger" },
};

export const AGENT_LABELS: Record<string, string> = {
  ingest: "Extracción",
  reader: "Agente lector",
  contradictions: "Agente de contradicciones",
  references: "Agente de referencias",
  classifier: "Agente clasificador",
};

export const HIGHLIGHT_LEGEND: { kind: FindingKind; label: string }[] = [
  { kind: "importante", label: "Importante" },
  { kind: "alerta", label: "Alerta" },
  { kind: "contradiccion", label: "Contradicción" },
  { kind: "referencia", label: "Referencia" },
];

export function scoreColor(score: number | null): string {
  if (score === null) return "var(--ink-faint)";
  if (score >= 80) return "var(--ok)";
  if (score >= 50) return "var(--warn)";
  return "var(--danger)";
}
