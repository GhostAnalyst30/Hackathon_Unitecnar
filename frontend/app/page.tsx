"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  FileText,
  FileImage,
  FileType2,
  Trash2,
  ScanText,
  AlertTriangle,
} from "lucide-react";
import { deleteDocument, listDocuments } from "@/lib/api";
import { useDocumentEvents } from "@/lib/useDocumentEvents";
import { CLASSIFICATION_META, scoreColor } from "@/lib/labels";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadZone } from "@/components/UploadZone";
import type { DocumentSummary } from "@/lib/types";

const FORMAT_ICONS = {
  pdf: FileText,
  docx: FileType2,
  image: FileImage,
};

export default function LibraryPage() {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [banner, setBanner] = useState<{ message: string; needsConfig: boolean } | null>(null);

  const refresh = useCallback(() => {
    listDocuments()
      .then(setDocs)
      .catch(() =>
        setBanner({
          message: "No se pudo conectar con el backend (puerto 8000).",
          needsConfig: false,
        }),
      );
  }, []);

  useEffect(refresh, [refresh]);
  useDocumentEvents(
    useCallback((event) => {
      if (event.status === "agent_log") return;
      refresh();
    }, [refresh]),
  );

  async function handleDelete(id: string, filename: string) {
    if (!confirm(`¿Eliminar "${filename}" y todo su análisis?`)) return;
    await deleteDocument(id);
    refresh();
  }

  return (
    <div className="mx-auto w-full max-w-7xl flex-1 px-5 py-8">
      <div className="rise-in mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-semibold tracking-tight text-ink">
            Biblioteca
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-soft">
            Sube un paper y el pipeline de agentes lo leerá, buscará contradicciones,
            revisará sus referencias y lo clasificará.{" "}
            <span className="font-medium text-ink">Tú siempre tienes la última palabra.</span>
          </p>
        </div>
      </div>

      {banner && (
        <div className="rise-in mb-6 flex items-center gap-3 rounded-lg border border-[#dfa8a0] bg-[#f3d9d5] px-4 py-3 text-sm text-danger">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{banner.message}</span>
          {banner.needsConfig && (
            <Link href="/settings" className="ml-auto shrink-0 font-semibold underline">
              Ir a Configuración
            </Link>
          )}
          <button
            onClick={() => setBanner(null)}
            className="ml-2 shrink-0 font-semibold opacity-60 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      <div className="rise-in" style={{ animationDelay: "60ms" }}>
        <UploadZone
          onUploaded={() => {
            setBanner(null);
            refresh();
          }}
          onError={(message, needsConfig) => setBanner({ message, needsConfig })}
        />
      </div>

      <div className="mt-8 space-y-2">
        {docs === null && (
          <p className="py-8 text-center text-sm text-ink-faint">Cargando documentos…</p>
        )}
        {docs?.length === 0 && (
          <p className="py-8 text-center text-sm text-ink-faint">
            Aún no hay documentos. Sube tu primer paper para empezar.
          </p>
        )}
        {docs?.map((doc, i) => {
          const Icon = FORMAT_ICONS[doc.file_format] ?? FileText;
          const cls = doc.classification
            ? CLASSIFICATION_META[doc.classification]
            : null;
          return (
            <div
              key={doc.id}
              className="rise-in group flex items-center gap-4 rounded-xl border border-line bg-paper-raised px-4 py-3 transition-shadow hover:shadow-[0_2px_12px_rgba(34,29,21,0.08)]"
              style={{ animationDelay: `${90 + i * 40}ms` }}
            >
              <Icon className="h-5 w-5 shrink-0 text-ink-faint" />
              <Link href={`/documents/${doc.id}`} className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium text-ink group-hover:text-accent">
                    {doc.filename}
                  </span>
                  {doc.ocr_used && (
                    <span
                      title="Se usó OCR para extraer el texto"
                      className="inline-flex items-center gap-1 rounded bg-paper-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-soft"
                    >
                      <ScanText className="h-3 w-3" /> OCR
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-ink-faint">
                  <span className="uppercase">{doc.file_format}</span>
                  <span>{new Date(doc.created_at).toLocaleString("es")}</span>
                  {doc.error && (
                    <span className="truncate text-danger">{doc.error}</span>
                  )}
                </div>
              </Link>
              {cls && (
                <span className={`hidden text-xs font-semibold sm:block ${cls.className}`}>
                  {cls.label}
                </span>
              )}
              {doc.score !== null && (
                <span
                  className="font-display text-lg font-semibold"
                  style={{ color: scoreColor(doc.score) }}
                  title={`Puntaje de validación: ${doc.score}/100`}
                >
                  {doc.score}
                </span>
              )}
              <StatusBadge status={doc.status} />
              <button
                onClick={() => void handleDelete(doc.id, doc.filename)}
                title="Eliminar documento"
                className="rounded-md p-1.5 text-ink-faint opacity-0 transition-all hover:bg-[#f3d9d5] hover:text-danger group-hover:opacity-100"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
