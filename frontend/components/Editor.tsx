"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
} from "react";
import { EditorContent, useEditor, type Editor as TiptapEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as PMNode } from "@tiptap/pm/model";
import { KIND_META } from "@/lib/labels";
import type { Finding } from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Búsqueda de citas dentro del documento ProseMirror                   */
/* ------------------------------------------------------------------ */

interface Segment {
  strStart: number;
  docFrom: number;
  length: number;
}

interface BlockIndex {
  text: string;
  segments: Segment[];
}

function indexBlock(node: PMNode, pos: number): BlockIndex {
  const segments: Segment[] = [];
  let text = "";
  node.forEach((child, offset) => {
    if (child.isText && child.text) {
      segments.push({
        strStart: text.length,
        docFrom: pos + 1 + offset,
        length: child.text.length,
      });
      text += child.text;
    } else {
      // Nodos inline no textuales (saltos de línea, etc.)
      text += "\n";
    }
  });
  return { text, segments };
}

function strIndexToDocPos(block: BlockIndex, index: number): number | null {
  for (const seg of block.segments) {
    if (index >= seg.strStart && index <= seg.strStart + seg.length) {
      return seg.docFrom + (index - seg.strStart);
    }
  }
  return null;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Busca una cita textual en el documento. Exacta primero, luego tolerante. */
export function findQuoteRange(
  doc: PMNode,
  quote: string,
): { from: number; to: number } | null {
  const trimmed = quote.trim();
  if (!trimmed) return null;

  const tokens = trimmed.split(/\s+/);
  const pattern = new RegExp(
    tokens.map(escapeRegex).join("[\\s\\u00A0]+"),
    "i",
  );

  let result: { from: number; to: number } | null = null;
  doc.descendants((node, pos) => {
    if (result || !node.isTextblock) return result === null;
    const block = indexBlock(node, pos);
    if (!block.text) return false;

    let start = block.text.indexOf(trimmed);
    let end = start === -1 ? -1 : start + trimmed.length;
    if (start === -1) {
      const match = pattern.exec(block.text);
      if (match) {
        start = match.index;
        end = match.index + match[0].length;
      }
    }
    if (start !== -1) {
      const from = strIndexToDocPos(block, start);
      const to = strIndexToDocPos(block, end);
      if (from !== null && to !== null && to > from) {
        result = { from, to };
      }
    }
    return false;
  });
  return result;
}

/* ------------------------------------------------------------------ */
/* Plugin de decoraciones para resaltar hallazgos                      */
/* ------------------------------------------------------------------ */

const highlightKey = new PluginKey<{
  findings: Finding[];
  activeId: string | null;
  decorations: DecorationSet;
}>("finding-highlights");

function buildDecorations(
  doc: PMNode,
  findings: Finding[],
  activeId: string | null,
): DecorationSet {
  const decorations: Decoration[] = [];
  for (const finding of findings) {
    const range = findQuoteRange(doc, finding.quote);
    if (!range) continue;
    const meta = KIND_META[finding.kind];
    const classes = [
      "hl",
      meta?.className ?? "hl-alerta",
      finding.id === activeId ? "hl-active" : "",
    ]
      .filter(Boolean)
      .join(" ");
    decorations.push(
      Decoration.inline(range.from, range.to, {
        class: classes,
        "data-finding-id": finding.id,
        title: `${meta?.label ?? finding.kind} · ${finding.explanation}`,
      }),
    );
  }
  return DecorationSet.create(doc, decorations);
}

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
  const editor = useEditor({
    extensions: [StarterKit, FindingHighlights],
    content: initialContent,
    immediatelyRender: false,
    onUpdate({ editor }) {
      onChange(editor.getHTML());
    },
  });

  // Sincronizar hallazgos con el plugin de resaltado
  useEffect(() => {
    if (!editor) return;
    const tr = editor.state.tr.setMeta(highlightKey, { findings });
    editor.view.dispatch(tr);
  }, [editor, findings]);

  useImperativeHandle(
    ref,
    () => ({
      applySuggestion(original: string, suggested: string) {
        if (!editor) return false;
        const range = findQuoteRange(editor.state.doc, original);
        if (!range) return false;
        editor
          .chain()
          .focus()
          .insertContentAt(range, suggested)
          .run();
        return true;
      },
      scrollToFinding(finding: Finding) {
        if (!editor) return false;
        const range = findQuoteRange(editor.state.doc, finding.quote);
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
    <div className="manuscript">
      <EditorContent editor={editor} />
    </div>
  );
});

export function editorFindingAnchored(editor: TiptapEditor, finding: Finding) {
  return findQuoteRange(editor.state.doc, finding.quote) !== null;
}
