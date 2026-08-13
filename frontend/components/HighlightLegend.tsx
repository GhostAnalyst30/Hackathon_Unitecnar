import { HIGHLIGHT_LEGEND, KIND_META } from "@/lib/labels";

export function HighlightLegend() {
  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-soft">
      <span className="font-semibold uppercase tracking-[0.12em] text-ink-faint">
        Resaltados
      </span>
      {HIGHLIGHT_LEGEND.map(({ kind, label }) => (
        <span key={kind} className="inline-flex items-center gap-1.5">
          <span className={`hl ${KIND_META[kind].className} px-1.5`}>{label}</span>
        </span>
      ))}
    </div>
  );
}
