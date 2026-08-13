"use client";

import { useMemo, useState } from "react";
import {
  BookOpenText,
  GitCompareArrows,
  Library,
  Scale,
  RefreshCw,
  CheckCircle2,
  XCircle,
  MapPinOff,
} from "lucide-react";
import { AGENT_LABELS, CLASSIFICATION_META, KIND_META } from "@/lib/labels";
import { ScoreRing } from "@/components/ScoreRing";
import type { DocumentDetail, Finding, ReferenceEntry } from "@/lib/types";

const SEVERITY_LABEL: Record<string, string> = {
  baja: "baja",
  media: "media",
  alta: "alta",
};

interface ParsedOutputs {
  reader?: Record<string, unknown>;
  contradictions?: Record<string, unknown>;
  references?: Record<string, unknown>;
  classifier?: Record<string, unknown>;
}

function parseOutputs(doc: DocumentDetail): ParsedOutputs {
  const out: ParsedOutputs = {};
  for (const item of doc.agent_outputs) {
    try {
      out[item.agent as keyof ParsedOutputs] = JSON.parse(item.output_json);
    } catch {
      /* salida no parseable */
    }
  }
  return out;
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group border-b border-line" open>
      <summary className="flex cursor-pointer items-center gap-2 py-2.5 text-sm font-semibold text-ink transition-colors hover:text-accent">
        <Icon className="h-4 w-4 text-ink-faint" />
        {title}
        <span className="ml-auto text-ink-faint transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      <div className="space-y-2 pb-3 text-sm leading-relaxed text-ink-soft">
        {children}
      </div>
    </details>
  );
}

export function AnalysisPanel({
  doc,
  onFindingClick,
  onReanalyze,
  onDecide,
  reanalyzing,
}: {
  doc: DocumentDetail;
  onFindingClick: (finding: Finding) => void;
  onReanalyze: () => void;
  onDecide: (decision: "validated" | "discarded", comment: string) => void;
  reanalyzing: boolean;
}) {
  const outputs = useMemo(() => parseOutputs(doc), [doc]);
  const [comment, setComment] = useState("");
  const cls = doc.classification ? CLASSIFICATION_META[doc.classification] : null;
  const busy = ["queued", "extracting", "analyzing"].includes(doc.status);

  const findingsByKind = useMemo(() => {
    const groups = new Map<string, Finding[]>();
    for (const f of doc.findings) {
      const list = groups.get(f.kind) ?? [];
      list.push(f);
      groups.set(f.kind, list);
    }
    return groups;
  }, [doc.findings]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Puntaje y clasificación */}
      <div className="flex items-center gap-4 border-b border-line px-4 py-4">
        <ScoreRing score={doc.score} size={64} />
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
            Puntaje de validación
          </p>
          {cls ? (
            <p className={`font-display text-lg font-semibold ${cls.className}`}>
              {cls.label}
            </p>
          ) : (
            <p className="text-sm text-ink-faint">
              {busy ? "Análisis en curso…" : "Sin clasificar"}
            </p>
          )}
        </div>
        <button
          onClick={onReanalyze}
          disabled={busy || reanalyzing}
          title="Volver a ejecutar los agentes sobre el texto actual"
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-paper-raised px-2.5 py-1.5 text-xs font-semibold text-ink-soft transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${busy || reanalyzing ? "animate-spin" : ""}`} />
          Re-analizar
        </button>
      </div>

      {/* Salidas de los agentes + hallazgos */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        {outputs.reader && (
          <Section icon={BookOpenText} title={AGENT_LABELS.reader}>
            <p>{String(outputs.reader.resumen ?? "")}</p>
            {Array.isArray(outputs.reader.estructura) &&
              outputs.reader.estructura.length > 0 && (
                <p className="text-xs text-ink-faint">
                  Estructura: {(outputs.reader.estructura as string[]).join(" · ")}
                </p>
              )}
          </Section>
        )}
        {outputs.contradictions && (
          <Section icon={GitCompareArrows} title={AGENT_LABELS.contradictions}>
            <p>{String(outputs.contradictions.evaluacion_general ?? "")}</p>
          </Section>
        )}
        {outputs.references && (
          <Section icon={Library} title={AGENT_LABELS.references}>
            <p>{String(outputs.references.analisis ?? "")}</p>
            {outputs.references.verificacion_crossref != null && (
              <p className="rounded-md bg-paper-sunken px-2.5 py-1.5 text-xs">
                <span className="font-semibold text-ink">Verificación Crossref: </span>
                {String(
                  (outputs.references.verificacion_crossref as { verificadas?: number })
                    .verificadas ?? 0,
                )}{" "}
                verificadas ·{" "}
                {String(
                  (
                    outputs.references.verificacion_crossref as {
                      no_encontradas?: number;
                    }
                  ).no_encontradas ?? 0,
                )}{" "}
                no encontradas de{" "}
                {String(
                  (outputs.references.verificacion_crossref as { total?: number })
                    .total ?? 0,
                )}
              </p>
            )}
            {Array.isArray(outputs.references.referencias) &&
              outputs.references.referencias.length > 0 && (
                <ul className="space-y-1.5">
                  {(outputs.references.referencias as ReferenceEntry[]).map((r, i) => (
                    <li key={i} className="rounded-md bg-paper-sunken px-2.5 py-1.5 text-xs">
                      <span className="font-medium text-ink">{r.referencia}</span>
                      <span
                        className={`ml-2 font-semibold uppercase ${
                          r.relevancia === "alta"
                            ? "text-ok"
                            : r.relevancia === "baja"
                              ? "text-danger"
                              : "text-warn"
                        }`}
                      >
                        {r.relevancia}
                      </span>
                      <span className="mt-1 flex flex-wrap items-center gap-1.5">
                        {r.verificada === true && (
                          <span className="inline-flex items-center rounded-full bg-[#dcead9] px-1.5 py-0.5 font-semibold text-ok">
                            ✓ Verificada en Crossref
                            {r.anio ? ` · ${r.anio}` : ""}
                          </span>
                        )}
                        {r.verificada === false && (
                          <span className="inline-flex items-center rounded-full bg-[#f3d9d5] px-1.5 py-0.5 font-semibold text-danger">
                            ✗ No encontrada en Crossref
                          </span>
                        )}
                        {(r.verificada === null || r.verificada === undefined) && (
                          <span className="inline-flex items-center rounded-full bg-paper px-1.5 py-0.5 font-semibold text-ink-faint">
                            Sin verificar
                          </span>
                        )}
                        {r.verificada === true && r.doi && (
                          <a
                            href={`https://doi.org/${r.doi}`}
                            target="_blank"
                            rel="noreferrer"
                            className="font-mono text-accent underline"
                          >
                            doi:{r.doi}
                          </a>
                        )}
                      </span>
                      {r.comentario && (
                        <p className="mt-0.5 text-ink-soft">{r.comentario}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
          </Section>
        )}
        {outputs.classifier && (
          <Section icon={Scale} title={AGENT_LABELS.classifier}>
            {outputs.classifier.ejes != null &&
              typeof outputs.classifier.ejes === "object" && (
                <div className="space-y-1.5 rounded-md bg-paper-sunken px-2.5 py-2 text-xs">
                  {(
                    [
                      ["contenido", "Contenido"],
                      ["coherencia", "Coherencia"],
                      ["referencias", "Referencias"],
                    ] as const
                  ).map(([key, label]) => {
                    const value = Number(
                      (outputs.classifier?.ejes as Record<string, unknown>)[key] ?? 0,
                    );
                    const weightPct = Math.round(
                      Number(
                        (outputs.classifier?.pesos as Record<string, unknown> | undefined)?.[
                          key
                        ] ?? (key === "contenido" ? 0.65 : key === "coherencia" ? 0.3 : 0.05),
                      ) * 100,
                    );
                    return (
                      <div key={key} className="flex items-center gap-2">
                        <span className="w-[7.2rem] shrink-0 text-ink-soft">
                          {label} · {weightPct}%
                        </span>
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-paper">
                          <span
                            className="block h-full rounded-full bg-accent"
                            style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                          />
                        </span>
                        <span className="w-8 text-right font-semibold text-ink">{value}</span>
                      </div>
                    );
                  })}
                  <p className="pt-1 text-[10px] text-ink-faint">
                    Crossref es residual (5%): no marca un paper como malo.
                  </p>
                </div>
              )}
            <p>{String(outputs.classifier.justificacion ?? "")}</p>
            {Array.isArray(outputs.classifier.recomendaciones) &&
              outputs.classifier.recomendaciones.length > 0 && (
                <ul className="list-disc space-y-1 pl-4 text-xs">
                  {(outputs.classifier.recomendaciones as string[]).map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
          </Section>
        )}

        {/* Hallazgos resaltables */}
        {doc.findings.length > 0 && (
          <div className="py-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
              Hallazgos resaltados ({doc.findings.length})
            </p>
            <div className="space-y-1.5">
              {[...findingsByKind.entries()].map(([kind, list]) => (
                <div key={kind}>
                  <p className="mb-1 mt-2 flex items-center gap-1.5 text-xs font-semibold text-ink">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${KIND_META[kind as keyof typeof KIND_META]?.dot ?? ""}`}
                    />
                    {KIND_META[kind as keyof typeof KIND_META]?.label ?? kind} ·{" "}
                    {list.length}
                  </p>
                  {list.map((f) => (
                    <button
                      key={f.id}
                      onClick={() => onFindingClick(f)}
                      className="mb-1.5 block w-full rounded-lg border border-line bg-paper-raised px-2.5 py-2 text-left transition-colors hover:border-accent/50"
                      title={
                        f.anchored
                          ? "Clic para ir al fragmento en el editor"
                          : "No se pudo ubicar este fragmento en el texto actual"
                      }
                    >
                      <p className="line-clamp-2 font-serif text-xs italic text-ink">
                        “{f.quote}”
                      </p>
                      <p className="mt-1 line-clamp-3 text-xs text-ink-soft">
                        {f.explanation}
                      </p>
                      <p className="mt-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-ink-faint">
                        <span>severidad {SEVERITY_LABEL[f.severity]}</span>
                        <span>{AGENT_LABELS[f.agent]}</span>
                        {!f.anchored && (
                          <span className="inline-flex items-center gap-0.5 text-danger">
                            <MapPinOff className="h-3 w-3" /> sin ubicar
                          </span>
                        )}
                      </p>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Decisión humana */}
      <div className="border-t-2 border-line-strong bg-paper-sunken/60 px-4 py-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-faint">
          Tu decisión — el humano tiene la última palabra
        </p>
        {doc.status === "validated" || doc.status === "discarded" ? (
          <div
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${
              doc.status === "validated"
                ? "bg-[#dcead9] text-ok"
                : "bg-[#f3d9d5] text-danger"
            }`}
          >
            {doc.status === "validated" ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <XCircle className="h-4 w-4" />
            )}
            {doc.status === "validated" ? "Documento validado" : "Documento descartado"}
            {doc.decision_comment && (
              <span className="ml-1 truncate font-normal opacity-80">
                — {doc.decision_comment}
              </span>
            )}
          </div>
        ) : (
          <>
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Comentario opcional…"
              className="mb-2 w-full rounded-md border border-line bg-paper-raised px-2.5 py-1.5 text-sm outline-none placeholder:text-ink-faint focus:border-accent"
            />
            <div className="flex gap-2">
              <button
                onClick={() => onDecide("validated", comment)}
                disabled={doc.status !== "awaiting_review"}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-ok px-3 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <CheckCircle2 className="h-4 w-4" /> Validar
              </button>
              <button
                onClick={() => onDecide("discarded", comment)}
                disabled={doc.status !== "awaiting_review"}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <XCircle className="h-4 w-4" /> Descartar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
