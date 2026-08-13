"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, SendHorizonal, Sparkles, Check } from "lucide-react";
import { parseSuggestions, sendChat } from "@/lib/api";
import type { ChatMessage, Suggestion } from "@/lib/types";

interface LocalMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  suggestions: Suggestion[];
}

export function ChatPanel({
  documentId,
  initialMessages,
  onApplySuggestion,
}: {
  documentId: string;
  initialMessages: ChatMessage[];
  onApplySuggestion: (s: Suggestion) => boolean;
}) {
  const [messages, setMessages] = useState<LocalMessage[]>(() =>
    initialMessages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      suggestions: parseSuggestions(m),
    })),
  );
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [applied, setApplied] = useState<Set<string>>(new Set());
  const [failed, setFailed] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function handleSend() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: "user", content: text, suggestions: [] },
    ]);
    try {
      const res = await sendChat(documentId, text);
      setMessages((prev) => [
        ...prev,
        {
          id: res.message_id,
          role: "assistant",
          content: res.reply,
          suggestions: res.suggestions,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: `⚠ ${err instanceof Error ? err.message : "Error al contactar el modelo"}`,
          suggestions: [],
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleApply(msgId: string, index: number, suggestion: Suggestion) {
    const key = `${msgId}:${index}`;
    if (onApplySuggestion(suggestion)) {
      setApplied((prev) => new Set(prev).add(key));
    } else {
      setFailed((prev) => new Set(prev).add(key));
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div className="mt-8 px-3 text-center text-sm text-ink-faint">
            <Sparkles className="mx-auto mb-2 h-5 w-5" />
            Pregunta lo que quieras sobre tu paper. El asistente conoce el texto y
            todos los hallazgos, y puede proponerte correcciones que tú decides
            aplicar.
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id}>
            <div
              className={`max-w-[92%] rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === "user"
                  ? "ml-auto bg-accent text-[#fdf6ee]"
                  : "bg-paper-sunken text-ink"
              }`}
            >
              {msg.content}
            </div>
            {msg.suggestions.map((s, i) => {
              const key = `${msg.id}:${i}`;
              const isApplied = applied.has(key);
              const isFailed = failed.has(key);
              return (
                <div
                  key={key}
                  className="mt-2 max-w-[92%] rounded-xl border border-line-strong bg-paper-raised p-2.5 text-xs"
                >
                  <p className="mb-1 font-semibold uppercase tracking-wide text-ink-faint">
                    Sugerencia de edición
                  </p>
                  <p className="rounded bg-[#f6dcd7] px-2 py-1 font-serif italic text-ink line-through decoration-danger/60">
                    {s.original}
                  </p>
                  <p className="mt-1 rounded bg-[#dcead9] px-2 py-1 font-serif italic text-ink">
                    {s.suggested}
                  </p>
                  {s.reason && <p className="mt-1.5 text-ink-soft">{s.reason}</p>}
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={() => handleApply(msg.id, i, s)}
                      disabled={isApplied}
                      className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-semibold transition-colors ${
                        isApplied
                          ? "bg-[#dcead9] text-ok"
                          : "bg-ink text-paper hover:bg-accent"
                      }`}
                    >
                      {isApplied ? (
                        <>
                          <Check className="h-3 w-3" /> Aplicada
                        </>
                      ) : (
                        "Aplicar al editor"
                      )}
                    </button>
                    {isFailed && (
                      <span className="text-danger">
                        No se encontró el texto original (quizá ya fue editado)
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2 px-1 text-xs text-ink-faint">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            El asistente está pensando…
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-line p-2.5">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            rows={2}
            placeholder="Pide correcciones, resúmenes, dudas…"
            className="max-h-32 flex-1 resize-none rounded-lg border border-line bg-paper-raised px-3 py-2 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
          />
          <button
            onClick={() => void handleSend()}
            disabled={sending || !input.trim()}
            className="rounded-lg bg-accent p-2.5 text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
            title="Enviar"
          >
            <SendHorizonal className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
