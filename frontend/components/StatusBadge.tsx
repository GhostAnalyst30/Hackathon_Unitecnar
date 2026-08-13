import { STATUS_META } from "@/lib/labels";
import type { DocumentStatus } from "@/lib/types";

const TONE_CLASSES: Record<string, string> = {
  muted: "bg-paper-sunken text-ink-soft border-line",
  busy: "bg-[#efe4cf] text-warn border-[#d9c496]",
  review: "bg-[#e5ddf3] text-[#5b3fa8] border-[#c3b2e6]",
  ok: "bg-[#dcead9] text-ok border-[#a9c8a4]",
  bad: "bg-[#f3d9d5] text-danger border-[#dfa8a0]",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const meta = STATUS_META[status];
  const busy = meta.tone === "busy";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[meta.tone]}`}
    >
      {busy && (
        <span className="pulse-soft inline-block h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {meta.label}
    </span>
  );
}
