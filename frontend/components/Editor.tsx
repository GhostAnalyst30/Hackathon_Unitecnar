"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { EditorContent, useEditor, type Editor as TiptapEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { TableKit } from "@tiptap/extension-table";
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as PMNode } from "@tiptap/pm/model";
import { KIND_META } from "@/lib/labels";
import { HighlightPopover } from "@/components/HighlightPopover";
import type { Finding } from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Búsqueda de citas dentro del documento ProseMirror                   */
/* ------------------------------------------------------------------ */

interface FlatDoc {
  text: string;
  /** posición PM de cada carácter; -1 = separador sintético entre bloques */
  pos: number[];
}

function flattenDoc(doc: PMNode): FlatDoc {
  let text = "";
  const pos: number[] = [];
  doc.descendants((node, nodePos) => {
    if (node.isText && node.text) {
      for (let i = 0; i < node.text.length; i++) {
        text += node.text[i];
        pos.push(nodePos + i);
      }
      return false;
    }
    if (node.isBlock && text.length && !text.endsWith("\n")) {
      text += "\n";
      pos.push(-1);
    }
    return true;
  });
  return { text, pos };
}

function rangeFromMatch(
  flat: FlatDoc,
  start: number,
  end: number,
): { from: number; to: number } | null {
  let from = -1;
  let to = -1;
  for (let i = start; i < end && i < flat.pos.length; i++) {
    const p = flat.pos[i];
    if (p >= 0) {
      if (from === -1) from = p;
      to = p + 1;
    }
  }
  if (from === -1 || to <= from) return null;
  return { from, to };
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function looseTokens(s: string): string[] {
  return s.toLowerCase().match(/[a-záéíóúüñ0-9]+/gi) ?? [];
}

function tryMatch(
  flat: FlatDoc,
  quote: string,
): { from: number; to: number } | null {
  const trimmed = quote.trim().replace(/^[«»""''“”‘’]+|[«»""''“”‘’]+$/g, "");
  if (!trimmed) return null;

  const hay = flat.text;
  for (const candidate of [quote.trim(), trimmed]) {
    const exact = hay.indexOf(candidate);
    if (exact !== -1) return rangeFromMatch(flat, exact, exact + candidate.length);
    const lower = hay.toLowerCase().indexOf(candidate.toLowerCase());
    if (lower !== -1) return rangeFromMatch(flat, lower, lower + candidate.length);
  }

  const tokens = trimmed.split(/\s+/).filter(Boolean);
  const attempts: string[] = [];
  if (tokens.length) {
    attempts.push(tokens.map(escapeRegex).join("[\\s\\u00A0]+"));
  }
  const loose = looseTokens(trimmed);
  if (loose.length >= 3) {
    attempts.push(loose.map(escapeRegex).join("[\\W_]*"));
  }
  for (const n of [10, 7, 5]) {
    if (tokens.length > n) {
      attempts.push(tokens.slice(0, n).map(escapeRegex).join("[\\s\\u00A0]+"));
    }
    if (loose.length > n) {
      attempts.push(loose.slice(0, n).map(escapeRegex).join("[\\W_]*"));
    }
  }

  for (const source of attempts) {
    try {
      const match = new RegExp(source, "i").exec(hay);
      if (match) return rangeFromMatch(flat, match.index, match.index + match[0].length);
    } catch {
      /* patrón inválido */
    }
  }
  return null;
}

/** Busca una cita textual en el documento. Exacta primero, luego tolerante. */
export function findQuoteRange(
  doc: PMNode,
  quote: string,
): { from: number; to: number } | null {
  if (!quote.trim()) return null;
  return tryMatch(flattenDoc(doc), quote);
}

function findingRangesFromFlat(
  flat: FlatDoc,
  finding: Finding,
): { from: number; to: number }[] {
  const ranges: { from: number; to: number }[] = [];
  const seen = new Set<string>();
  for (const quote of [finding.quote, finding.quote_secondary]) {
    if (!quote) continue;
    const range = tryMatch(flat, quote);
    if (!range) continue;
    const key = `${range.from}:${range.to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    ranges.push(range);
  }
  return ranges;
}

function buildDecorations(
  doc: PMNode,
  findings: Finding[],
  activeId: string | null,
): DecorationSet {
  const decorations: Decoration[] = [];
  const flat = flattenDoc(doc);
  for (const finding of findings) {
    const meta = KIND_META[finding.kind];
    const classes = [
      "hl",
      meta?.className ?? "hl-alerta",
      finding.id === activeId ? "hl-active" : "",
    ]
      .filter(Boolean)
      .join(" ");
    for (const range of findingRangesFromFlat(flat, finding)) {
      decorations.push(
        Decoration.inline(range.from, range.to, {
          class: classes,
          "data-finding-id": finding.id,
        }),
      );
    }
  }
  return DecorationSet.create(doc, decorations);
}

const highlightKey = new PluginKey<{
  findings: Finding[];
  activeId: string | null;
  decorations: DecorationSet;
}>("finding-highlights");

const FindingHighlights = Extension.create({
  name: "findingHighlights",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: highlightKey,
        state: {
          init: (_, state) => ({
            findings: [] as Finding[],
            activeId: null as string | null,
            decorations: DecorationSet.create(state.doc, []),
          }),
          apply(tr, value, _old, newState) {
            const meta = tr.getMeta(highlightKey) as
              | { findings?: Finding[]; activeId?: string | null }
              | undefined;
            if (meta || tr.docChanged) {
              const findings = meta?.findings ?? value.findings;
              const activeId =
                meta?.activeId !== undefined ? meta.activeId : value.activeId;
              return {
                findings,
                activeId,
                decorations: buildDecorations(newState.doc, findings, activeId),
              };
            }
            return value;
          },
        },
        props: {
          decorations(state) {
            return highlightKey.getState(state)?.decorations;
          },
        },
      }),
    ];
  },
});

/* ------------------------------------------------------------------ */
/* Componente                                                           */
/* ------------------------------------------------------------------ */

export interface EditorHandle {
  /** Reemplaza el texto original por el sugerido. Devuelve false si no lo encontró. */
  applySuggestion: (original: string, suggested: string) => boolean;
  /** Hace scroll hasta la cita del hallazgo y la marca como activa. */
  scrollToFinding: (finding: Finding) => boolean;
  getHTML: () => string;
}

export const DocumentEditor = forwardRef<
  EditorHandle,
  {
    initialContent: string;
    findings: Finding[];
    onChange: (html: string) => void;
  }
>(function DocumentEditor({ initialContent, findings, onChange }, ref) {
  const findingsRef = useRef(findings);
  findingsRef.current = findings;
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [tip, setTip] = useState<{ finding: Finding; rect: DOMRect } | null>(null);
  const tipRef = useRef(tip);
  tipRef.current = tip;

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      TableKit.configure({ table: { resizable: false } }),
      FindingHighlights,
    ],
    content: initialContent,
    immediatelyRender: false,
    onUpdate({ editor }) {
      onChange(editor.getHTML());
    },
  });

  useEffect(() => {
    if (!editor) return;
    const tr = editor.state.tr.setMeta(highlightKey, { findings });
    editor.view.dispatch(tr);
  }, [editor, findings]);

  function clearHide() {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }

  function scheduleHide() {
    clearHide();
    hideTimer.current = setTimeout(() => setTip(null), 140);
  }

  function showFromEvent(target: EventTarget | null) {
    const el = (target as HTMLElement | null)?.closest?.("[data-finding-id]") as
      | HTMLElement
      | null;
    if (!el) return false;
    const id = el.getAttribute("data-finding-id");
    const finding = findingsRef.current.find((f) => f.id === id);
    if (!finding) return false;
    clearHide();
    setTip({ finding, rect: el.getBoundingClientRect() });
    return true;
  }

  useImperativeHandle(
    ref,
    () => ({
      applySuggestion(original: string, suggested: string) {
        if (!editor) return false;
        const range = findQuoteRange(editor.state.doc, original);
        if (!range) return false;
        editor.chain().focus().insertContentAt(range, suggested).run();
        return true;
      },
      scrollToFinding(finding: Finding) {
        if (!editor) return false;
        const range =
          findQuoteRange(editor.state.doc, finding.quote) ??
          (finding.quote_secondary
            ? findQuoteRange(editor.state.doc, finding.quote_secondary)
            : null);
        if (!range) return false;
        const tr = editor.state.tr
          .setMeta(highlightKey, { activeId: finding.id })
          .setSelection(TextSelection.create(editor.state.doc, range.from))
          .scrollIntoView();
        editor.view.dispatch(tr);
        const dom = editor.view.domAtPos(range.from).node;
        const el = dom instanceof Element ? dom : dom.parentElement;
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      },
      getHTML() {
        return editor?.getHTML() ?? "";
      },
    }),
    [editor],
  );

  return (
    <div
      className="manuscript"
      onMouseOver={(e) => {
        const el = (e.target as HTMLElement | null)?.closest?.(
          "[data-finding-id]",
        ) as HTMLElement | null;
        if (!el) return;
        const id = el.getAttribute("data-finding-id");
        if (tipRef.current?.finding.id === id) {
          clearHide();
          return;
        }
        showFromEvent(e.target);
      }}
      onMouseOut={(e) => {
        const next = e.relatedTarget as HTMLElement | null;
        if (next?.closest?.("[data-finding-id]") || next?.closest?.(".hl-pop")) return;
        scheduleHide();
      }}
    >
      <EditorContent editor={editor} />
      {tip && (
        <HighlightPopover
          finding={tip.finding}
          anchor={tip.rect}
          onEnter={clearHide}
          onLeave={scheduleHide}
        />
      )}
    </div>
  );
});

export function editorFindingAnchored(editor: TiptapEditor, finding: Finding) {
  return (
    findQuoteRange(editor.state.doc, finding.quote) !== null ||
    (!!finding.quote_secondary &&
      findQuoteRange(editor.state.doc, finding.quote_secondary) !== null)
  );
}
