"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type Ref,
} from "react";
import { Loader2 } from "lucide-react";
import { originalFileUrl, getPageBoxes, type PageWordBox } from "@/lib/api";
import { KIND_META } from "@/lib/labels";
import { HighlightLegend } from "@/components/HighlightLegend";
import { HighlightPopover } from "@/components/HighlightPopover";
import type { Finding, HighlightRect } from "@/lib/types";

export interface OriginalViewerHandle {
  scrollToFinding: (finding: Finding) => boolean;
}

type PdfDoc = import("pdfjs-dist").PDFDocumentProxy;
type PdfRenderTask = import("pdfjs-dist").RenderTask;

function tokens(text: string): string[] {
  return (
    text
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .match(/[a-z0-9]+/g) ?? []
  );
}

function matchQuoteBoxes(
  page: number,
  boxes: PageWordBox[],
  quote: string,
): HighlightRect[] {
  const q = tokens(quote);
  if (q.length < 3 || !boxes.length) return [];
  const hay: { tok: string; i: number }[] = [];
  boxes.forEach((box, i) => {
    for (const tok of tokens(box.text)) hay.push({ tok, i });
  });
  const htoks = hay.map((h) => h.tok);
  let hit = new Set<number>();
  for (const n of [q.length, 12, 8, 5]) {
    const needle = q.slice(0, Math.min(n, q.length));
    if (needle.length < 3) continue;
    const span = needle.length;
    for (let i = 0; i <= htoks.length - span; i++) {
      let ok = true;
      for (let k = 0; k < span; k++) {
        if (htoks[i + k] !== needle[k]) {
          ok = false;
          break;
        }
      }
      if (ok) {
        hit = new Set(hay.slice(i, i + span).map((h) => h.i));
        break;
      }
    }
    if (hit.size) break;
  }
  return [...hit]
    .sort((a, b) => a - b)
    .map((i) => ({
      page,
      x: boxes[i].x,
      y: boxes[i].y,
      w: boxes[i].w,
      h: boxes[i].h,
    }));
}

function overlaysForPage(
  page: number,
  boxes: PageWordBox[],
  findings: Finding[],
): { finding: Finding; rect: HighlightRect }[] {
  const out: { finding: Finding; rect: HighlightRect }[] = [];
  for (const finding of findings) {
    const rects: HighlightRect[] = [];
    for (const quote of [finding.quote, finding.quote_secondary]) {
      if (!quote) continue;
      rects.push(...matchQuoteBoxes(page, boxes, quote));
    }
    for (const rect of rects) out.push({ finding, rect });
  }
  return out;
}

function PdfPage({
  pdf,
  pageNumber,
  width,
  documentId,
  findings,
  backendOverlays,
  activeId,
}: {
  pdf: PdfDoc;
  pageNumber: number;
  width: number;
  documentId: string;
  findings: Finding[];
  backendOverlays: { finding: Finding; rect: HighlightRect }[];
  activeId: string | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: width, h: Math.round(width * 1.294) });
  const [visible, setVisible] = useState(pageNumber <= 2);
  const [locating, setLocating] = useState(false);
  const [ocrOverlays, setOcrOverlays] = useState<
    { finding: Finding; rect: HighlightRect }[]
  >([]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setVisible(true);
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: PdfRenderTask | null = null;
    (async () => {
      const page = await pdf.getPage(pageNumber);
      if (cancelled) return;
      const unscaled = page.getViewport({ scale: 1 });
      const scale = width / unscaled.width;
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setSize({ w: viewport.width, h: viewport.height });
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const transform = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined;
      task = page.render({
        canvas,
        viewport,
        transform,
      });
      try {
        await task.promise;
      } catch (err) {
        const name = (err as { name?: string }).name;
        if (name !== "RenderingCancelledException") throw err;
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, pageNumber, width]);

  const findingsKey = findings.map((f) => f.id).join(",");

  useEffect(() => {
    if (!visible || backendOverlays.length || !findings.length) return;
    let cancelled = false;
    setLocating(true);
    getPageBoxes(documentId, pageNumber)
      .then((res) => {
        if (cancelled) return;
        setOcrOverlays(overlaysForPage(pageNumber, res.words, findings));
      })
      .catch(() => {
        if (!cancelled) setOcrOverlays([]);
      })
      .finally(() => {
        if (!cancelled) setLocating(false);
      });
    return () => {
      cancelled = true;
    };
    // findingsKey avoids re-OCR on cada render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, backendOverlays.length, documentId, pageNumber, findingsKey]);

  const overlays = backendOverlays.length ? backendOverlays : ocrOverlays;

  return (
    <div
      ref={hostRef}
      id={`pdf-page-${pageNumber}`}
      className="relative mx-auto mb-5 bg-white shadow-[0_1px_3px_rgba(34,29,21,0.08),0_8px_28px_rgba(34,29,21,0.06)]"
      style={{ width: size.w, height: size.h }}
    >
      <canvas ref={canvasRef} className="block" />
      <div className="absolute inset-0 z-2">
        {overlays.map((o, i) => (
          <div
            key={`${o.finding.id}-${i}`}
            data-finding-id={o.finding.id}
            className={`hl-page ${KIND_META[o.finding.kind]?.className ?? "hl-alerta"} ${
              o.finding.id === activeId ? "hl-active" : ""
            }`}
            style={{
              left: `${o.rect.x * 100}%`,
              top: `${o.rect.y * 100}%`,
              width: `${o.rect.w * 100}%`,
              height: `${o.rect.h * 100}%`,
            }}
          />
        ))}
      </div>
      {locating && (
        <div className="absolute bottom-2 left-2 z-3 rounded bg-paper-raised/90 px-2 py-1 text-[10px] font-medium text-ink-faint">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
          Subrayando hallazgos…
        </div>
      )}
    </div>
  );
}

function PdfOriginal({
  documentId,
  findings,
  viewerRef,
}: {
  documentId: string;
  findings: Finding[];
  viewerRef: Ref<OriginalViewerHandle>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<PdfDoc | null>(null);
  const [pdf, setPdf] = useState<PdfDoc | null>(null);
  const [pages, setPages] = useState(0);
  const [width, setWidth] = useState(720);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tip, setTip] = useState<{ finding: Finding; rect: DOMRect } | null>(null);
  const tipRef = useRef(tip);
  tipRef.current = tip;
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const findingsRef = useRef(findings);
  findingsRef.current = findings;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const apply = () => {
      const next = Math.max(280, Math.floor(el.clientWidth));
      setWidth((w) => (Math.abs(w - next) > 2 ? next : w));
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
      const res = await fetch(originalFileUrl(documentId));
      if (!res.ok) throw new Error("No se pudo cargar el archivo original");
      const data = await res.arrayBuffer();
      const task = pdfjs.getDocument({ data });
      const loaded = await task.promise;
      if (cancelled) {
        void loaded.cleanup();
        void loaded.loadingTask.destroy();
        return;
      }
      pdfRef.current = loaded;
      setPdf(loaded);
      setPages(loaded.numPages);
    })()
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "No se pudo abrir el PDF");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      const current = pdfRef.current;
      pdfRef.current = null;
      if (current) {
        void current.cleanup();
        void current.loadingTask.destroy();
      }
    };
  }, [documentId]);

  const rectsOf = useCallback(
    (finding: Finding) => finding.rects ?? [],
    [],
  );

  useImperativeHandle(
    viewerRef,
    () => ({
      scrollToFinding(finding: Finding) {
        const el = document.querySelector(`[data-finding-id="${finding.id}"]`);
        if (!el) return false;
        setActiveId(finding.id);
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      },
    }),
    [rectsOf],
  );

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
    if (!el) return;
    const id = el.getAttribute("data-finding-id");
    const finding = findingsRef.current.find((f) => f.id === id);
    if (!finding) return;
    clearHide();
    setTip({ finding, rect: el.getBoundingClientRect() });
  }

  const overlaysByPage = useMemo(() => {
    const map = new Map<number, { finding: Finding; rect: HighlightRect }[]>();
    for (const finding of findings) {
      for (const rect of rectsOf(finding)) {
        const list = map.get(rect.page) ?? [];
        list.push({ finding, rect });
        map.set(rect.page, list);
      }
    }
    return map;
  }, [findings, rectsOf]);

  return (
    <div
      ref={wrapRef}
      className="mx-auto max-w-4xl px-4 py-6"
      onMouseOver={(e) => {
        const el = (e.target as HTMLElement | null)?.closest?.("[data-finding-id]");
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
      <HighlightLegend />
      {findings.length > 0 && (
        <p className="mb-4 text-[11px] text-ink-faint">
          En papers escaneados los subrayados tardan unos segundos en cada página visible.
        </p>
      )}
      {loading && (
        <div className="flex items-center justify-center py-24 text-sm text-ink-faint">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Cargando el paper original…
        </div>
      )}
      {error && <p className="py-8 text-center text-sm text-danger">{error}</p>}
      {pdf &&
        Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
          <PdfPage
            key={n}
            pdf={pdf}
            pageNumber={n}
            width={width}
            documentId={documentId}
            findings={findings}
            backendOverlays={overlaysByPage.get(n) ?? []}
            activeId={activeId}
          />
        ))}
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
}

const ImageOriginal = forwardRef<OriginalViewerHandle, { documentId: string }>(
  function ImageOriginal({ documentId }, ref) {
    useImperativeHandle(ref, () => ({ scrollToFinding: () => false }), []);
    return (
      <div className="mx-auto max-w-4xl px-4 py-6">
        <HighlightLegend />
        <p className="mb-4 text-xs text-ink-faint">
          Vista del archivo subido. Los subrayados de los agentes están en la vista de texto
          extraído.
        </p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={originalFileUrl(documentId)}
          alt="Documento original"
          className="mx-auto max-w-full bg-white shadow-[0_1px_3px_rgba(34,29,21,0.08),0_8px_28px_rgba(34,29,21,0.06)]"
        />
      </div>
    );
  },
);

export const OriginalViewer = forwardRef<
  OriginalViewerHandle,
  {
    documentId: string;
    fileFormat: "pdf" | "docx" | "image";
    findings: Finding[];
  }
>(function OriginalViewer({ documentId, fileFormat, findings }, ref) {
  if (fileFormat === "image") {
    return <ImageOriginal ref={ref} documentId={documentId} />;
  }
  return <PdfOriginal documentId={documentId} findings={findings} viewerRef={ref} />;
});
