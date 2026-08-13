"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Download,
  Loader2,
  MessageSquareText,
  PanelRightClose,
  CloudUpload,
  Check,
} from "lucide-react";
import {
  decideDocument,
  exportUrl,
  getDocument,
  reanalyzeDocument,
  updateContent,
} from "@/lib/api";
import { useDocumentEvents } from "@/lib/useDocumentEvents";
import { AGENT_LABELS } from "@/lib/labels";
import { StatusBadge } from "@/components/StatusBadge";
import { AnalysisPanel } from "@/components/AnalysisPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { AgentProcessFeed } from "@/components/AgentProcessFeed";
import { HighlightLegend } from "@/components/HighlightLegend";
import { DocumentEditor, type EditorHandle } from "@/components/Editor";
import type { DocumentDetail, Finding, ProcessLog, Suggestion } from "@/lib/types";

type SaveState = "idle" | "pending" | "saving" | "saved" | "error";

const PIPELINE_STEPS = ["reader", "contradictions", "references", "classifier"];

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [chatOpen, setChatOpen] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [agentsDone, setAgentsDone] = useState<string[]>([]);
  const [editorKey, setEditorKey] = useState(0);

  const editorRef = useRef<EditorHandle>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestHtml = useRef<string>("");

  const refetch = useCallback(
    (remountEditor = false) => {
      getDocument(id)
        .then((d) => {
          setDoc(d);
          if (remountEditor) setEditorKey((k) => k + 1);
        })
        .catch((err) =>
          setLoadError(err instanceof Error ? err.message : "Error al cargar"),
        );
    },
    [id],
  );

  useEffect(() => refetch(true), [refetch]);

  useDocumentEvents(
    useCallback(
      (event) => {
        if (event.document_id !== id) return;
        if (event.status === "agent_log") {
          const entry: ProcessLog = {
            id: event.log_id ?? `local-${Date.now()}-${Math.random()}`,
            agent: event.agent ?? "ingest",
            message: event.message ?? "",
            created_at: event.created_at ?? new Date().toISOString(),
          };
          setDoc((prev) => {
            if (!prev) return prev;
            if ((prev.process_logs ?? []).some((l) => l.id === entry.id)) return prev;
            return { ...prev, process_logs: [...(prev.process_logs ?? []), entry] };
          });
          return;
        }
        if (event.status === "agent_done" && event.agent) {
          setAgentsDone((prev) =>
            prev.includes(event.agent!) ? prev : [...prev, event.agent!],
          );
          return;
        }
        if (event.status === "analyzing") {
          refetch(true);
          return;
        }
        if (["awaiting_review", "error"].includes(event.status)) {
          setAgentsDone([]);
          setReanalyzing(false);
          refetch(true);
        } else {
          setDoc((prev) =>
            prev ? { ...prev, status: event.status as DocumentDetail["status"] } : prev,
          );
        }
      },
      [id, refetch],
    ),
  );

  /* ---------- Autoguardado con debounce ---------- */
  const scheduleSave = useCallback(
    (html: string) => {
      latestHtml.current = html;
      setSaveState("pending");
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        setSaveState("saving");
        try {
          const findings = await updateContent(id, latestHtml.current);
          setDoc((prev) => (prev ? { ...prev, findings } : prev));
          setSaveState("saved");
        } catch {
          setSaveState("error");
        }
      }, 1200);
    },
    [id],
  );

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  /* ---------- Acciones ---------- */
  function handleFindingClick(finding: Finding) {
    editorRef.current?.scrollToFinding(finding);
  }

  function handleApplySuggestion(s: Suggestion): boolean {
    return editorRef.current?.applySuggestion(s.original, s.suggested) ?? false;
  }

  async function handleReanalyze() {
    if (!doc) return;
    setReanalyzing(true);
    setAgentsDone([]);
    setDoc((prev) => (prev ? { ...prev, process_logs: [] } : prev));
    try {
      await reanalyzeDocument(doc.id);
      setDoc((prev) => (prev ? { ...prev, status: "queued" } : prev));
    } catch (err) {
      setReanalyzing(false);
      alert(err instanceof Error ? err.message : "No se pudo re-analizar");
    }
  }

  async function handleDecide(decision: "validated" | "discarded", comment: string) {
    if (!doc) return;
    try {
      await decideDocument(doc.id, decision, comment || undefined);
      refetch();
    } catch (err) {
      alert(err instanceof Error ? err.message : "No se pudo guardar la decisión");
    }
  }

  /* ---------- Render ---------- */
  if (loadError) {
    return (
      <div className="mx-auto max-w-lg px-5 py-20 text-center">
        <p className="text-danger">{loadError}</p>
        <Link href="/" className="mt-4 inline-block text-sm font-semibold text-accent underline">
          Volver a la biblioteca
        </Link>
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="flex flex-1 items-center justify-center py-20 text-ink-faint">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Cargando documento…
      </div>
    );
  }

  const busy = ["queued", "extracting", "analyzing"].includes(doc.status);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Barra del documento */}
      <div className="flex items-center gap-3 border-b border-line bg-paper-raised/70 px-4 py-2">
        <Link
          href="/"
          className="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-paper-sunken hover:text-ink"
          title="Volver a la biblioteca"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <h1 className="min-w-0 truncate font-display text-base font-semibold text-ink">
          {doc.filename}
        </h1>
        <StatusBadge status={doc.status} />

        <span className="ml-auto flex items-center gap-1.5 text-xs text-ink-faint">
          {saveState === "saving" || saveState === "pending" ? (
            <>
              <CloudUpload className="h-3.5 w-3.5 animate-pulse" /> Guardando…
            </>
          ) : saveState === "saved" ? (
            <>
              <Check className="h-3.5 w-3.5 text-ok" /> Guardado
            </>
          ) : saveState === "error" ? (
            <span className="text-danger">Error al guardar</span>
          ) : null}
        </span>

        <div className="relative">
          <button
            onClick={() => setExportOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md border border-line-strong px-2.5 py-1.5 text-xs font-semibold text-ink-soft transition-colors hover:border-accent hover:text-accent"
          >
            <Download className="h-3.5 w-3.5" /> Exportar
          </button>
          {exportOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-36 overflow-hidden rounded-lg border border-line bg-paper-raised shadow-lg">
              {(["docx", "md", "html"] as const).map((fmt) => (
                <a
                  key={fmt}
                  href={exportUrl(doc.id, fmt)}
                  onClick={() => setExportOpen(false)}
                  className="block px-3 py-2 text-xs font-medium text-ink-soft transition-colors hover:bg-paper-sunken hover:text-ink"
                >
                  {fmt === "docx" ? "Word (.docx)" : fmt === "md" ? "Markdown (.md)" : "HTML (.html)"}
                </a>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={() => setChatOpen((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
            chatOpen
              ? "border-accent bg-accent text-white"
              : "border-line-strong text-ink-soft hover:border-accent hover:text-accent"
          }`}
          title={chatOpen ? "Ocultar chat" : "Mostrar chat"}
        >
          {chatOpen ? (
            <PanelRightClose className="h-3.5 w-3.5" />
          ) : (
            <MessageSquareText className="h-3.5 w-3.5" />
          )}
          Asistente
        </button>
      </div>

      {/* Tres zonas */}
      <div className="flex min-h-0 flex-1">
        {/* Panel de análisis */}
        <aside className="hidden w-[340px] shrink-0 border-r border-line bg-paper-raised/50 lg:block">
          <AnalysisPanel
            doc={doc}
            onFindingClick={handleFindingClick}
            onReanalyze={() => void handleReanalyze()}
            onDecide={(d, c) => void handleDecide(d, c)}
            reanalyzing={reanalyzing}
          />
        </aside>

        {/* Editor */}
        <section className="flex min-w-0 flex-1 flex-col">
          <AgentProcessFeed logs={doc.process_logs ?? []} busy={busy} />
          {busy && (
            <div className="z-30 border-b border-[#d9c496] bg-[#efe4cf] px-4 py-2 text-xs font-medium text-warn">
              <span className="pulse-soft mr-2 inline-block h-2 w-2 rounded-full bg-warn" />
              {doc.status === "extracting"
                ? "Extrayendo la estructura del documento…"
                : "Pipeline de agentes en ejecución…"}
              <span className="ml-3 text-ink-faint">
                {PIPELINE_STEPS.map((step) => (
                  <span key={step} className="mr-2">
                    {agentsDone.includes(step) ? "✓" : "·"} {AGENT_LABELS[step]}
                  </span>
                ))}
              </span>
            </div>
          )}
          {doc.status === "error" && (
            <div className="sticky top-0 z-30 border-b border-[#dfa8a0] bg-[#f3d9d5] px-4 py-2 text-xs font-medium text-danger">
              {doc.error ?? "El servidor no pudo leer los datos."} Usa «Re-analizar»
              para intentarlo otra vez.
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {doc.content_html ? (
              <div className="rise-in rounded-sm border border-line bg-paper-raised px-10 py-12 shadow-[0_1px_3px_rgba(34,29,21,0.08),0_8px_28px_rgba(34,29,21,0.06)]">
                <HighlightLegend />
                <DocumentEditor
                  key={editorKey}
                  ref={editorRef}
                  initialContent={doc.content_html}
                  findings={doc.findings}
                  onChange={scheduleSave}
                />
              </div>
            ) : (
              <div className="py-24 text-center text-sm text-ink-faint">
                {busy ? (
                  <>
                    <Loader2 className="mx-auto mb-3 h-6 w-6 animate-spin" />
                    El texto aparecerá aquí en cuanto termine la extracción…
                  </>
                ) : (
                  "Este documento no tiene contenido."
                )}
              </div>
            )}
          </div>
          </div>
        </section>

        {/* Chat */}
        {chatOpen && (
          <aside className="hidden w-[340px] shrink-0 border-l border-line bg-paper-raised/50 md:block">
            <ChatPanel
              documentId={doc.id}
              initialMessages={doc.chat_messages}
              onApplySuggestion={handleApplySuggestion}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
