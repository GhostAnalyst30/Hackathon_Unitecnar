"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AGENT_LABELS, KIND_META } from "@/lib/labels";
import type { Finding } from "@/lib/types";

const SEVERITY: Record<string, string> = {
  baja: "baja",
  media: "media",
  alta: "alta",
};

export function HighlightPopover({
  finding,
  anchor,
  onEnter,
  onLeave,
}: {
  finding: Finding;
  anchor: DOMRect;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: anchor.bottom + 10, left: anchor.left });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const pad = 12;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let top = anchor.bottom + 10;
    if (top + h > window.innerHeight - pad) {
      top = Math.max(pad, anchor.top - h - 10);
    }
    let left = anchor.left;
    if (left + w > window.innerWidth - pad) left = window.innerWidth - w - pad;
    if (left < pad) left = pad;
    setPos({ top, left });
  }, [anchor, finding.id]);

  const meta = KIND_META[finding.kind];

  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      className="hl-pop"
      style={{ top: pos.top, left: pos.left }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <div className={`hl-pop-bar ${meta?.className ?? "hl-alerta"}`} />
      <div className="hl-pop-body">
        <p className="hl-pop-kicker">
          <span className={`hl-pop-kind ${meta?.className ?? ""}`}>
            {meta?.label ?? finding.kind}
          </span>
          <span>severidad {SEVERITY[finding.severity] ?? finding.severity}</span>
          <span>{AGENT_LABELS[finding.agent] ?? finding.agent}</span>
        </p>
        <p className="hl-pop-quote">“{finding.quote}”</p>
        {finding.quote_secondary && (
          <p className="hl-pop-quote hl-pop-quote-alt">
            vs. “{finding.quote_secondary}”
          </p>
        )}
        <p className="hl-pop-text">{finding.explanation}</p>
      </div>
    </div>,
    document.body,
  );
}
