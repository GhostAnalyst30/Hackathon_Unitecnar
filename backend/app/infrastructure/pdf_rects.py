"""Ancla citas de hallazgos a rectángulos del PDF original (coordenadas 0–1).

PDFs nativos: usa la capa de texto de PyMuPDF.
PDFs escaneados: OCR local (RapidOCR) por página, con caché en disco.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

import pymupdf as fitz

from ..config import OCR_BOXES_DIR
from ..domain.entities import Finding
from ..domain.services import find_quote
from .rapid_ocr import pixmap_to_numpy, run_ocr

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_SOFT_HYPHEN = re.compile(r"-\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
MIN_NATIVE_WORDS = 8


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(_fold(text))


def _norm_box(x0: float, y0: float, x1: float, y1: float, pw: float, ph: float) -> dict | None:
    pw = pw or 1.0
    ph = ph or 1.0
    w = (x1 - x0) / pw
    h = (y1 - y0) / ph
    if w <= 0 or h <= 0:
        return None
    return {
        "text": "",
        "x": round(x0 / pw, 4),
        "y": round(y0 / ph, 4),
        "w": round(min(w, 1.0), 4),
        "h": round(min(max(h, 0.008), 1.0), 4),
    }


def _native_boxes(page: fitz.Page) -> list[dict]:
    pw = page.rect.width or 1.0
    ph = page.rect.height or 1.0
    out: list[dict] = []
    for item in page.get_text("words") or []:
        if len(item) < 5:
            continue
        x0, y0, x1, y1, text = item[:5]
        if not str(text).strip():
            continue
        box = _norm_box(float(x0), float(y0), float(x1), float(y1), pw, ph)
        if not box:
            continue
        box["text"] = str(text)
        out.append(box)
    return out


def _ocr_cache_path(pdf_path: Path, page_no: int) -> Path:
    folder = OCR_BOXES_DIR / pdf_path.stem
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{page_no}.json"


def _ocr_boxes(page: fitz.Page, cache_path: Path) -> list[dict]:
    if cache_path.is_file():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), colorspace=fitz.csRGB)
    items = run_ocr(pixmap_to_numpy(pix))
    out: list[dict] = []
    for item in items:
        box = _norm_box(
            item["x0"], item["y0"], item["x1"], item["y1"], float(pix.w), float(pix.h)
        )
        if not box:
            continue
        box["text"] = item["text"]
        out.append(box)
    cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def get_page_boxes(path: Path, page_no: int) -> list[dict]:
    """Palabras/líneas de una página (1-based) con coordenadas 0–1."""
    if not path.is_file():
        raise FileNotFoundError(str(path))
    doc = fitz.open(path)
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise ValueError(f"Página {page_no} fuera de rango")
        page = doc[page_no - 1]
        native = _native_boxes(page)
        if len(native) >= MIN_NATIVE_WORDS:
            return native
        return _ocr_boxes(page, _ocr_cache_path(path, page_no))
    finally:
        doc.close()


def match_quote_boxes(boxes: list[dict], quote: str) -> list[dict]:
    """Devuelve copias de cajas (sin text) que cubren la cita."""
    quote = (quote or "").strip()
    if not quote or not boxes:
        return []
    hay: list[tuple[str, int]] = []
    for i, box in enumerate(boxes):
        for tok in _tokens(box.get("text") or ""):
            hay.append((tok, i))
    if not hay:
        return []
    q = _tokens(quote)
    if len(q) < 3:
        return []
    htoks = [t for t, _ in hay]
    hit: set[int] = set()
    for n in (len(q), 12, 8, 5):
        needle = q[:n] if n < len(q) else q
        if len(needle) < 3:
            continue
        span = len(needle)
        for i in range(len(htoks) - span + 1):
            if htoks[i : i + span] == needle:
                hit = {hay[j][1] for j in range(i, i + span)}
                break
        if hit:
            break
    out: list[dict] = []
    for i in sorted(hit):
        b = boxes[i]
        out.append(
            {
                "x": b["x"],
                "y": b["y"],
                "w": b["w"],
                "h": b["h"],
            }
        )
    return out


def _norm_rect(page_no: int, rect: fitz.Rect, page: fitz.Page) -> dict | None:
    box = _norm_box(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1), page.rect.width, page.rect.height)
    if not box:
        return None
    return {
        "page": page_no,
        "x": box["x"],
        "y": box["y"],
        "w": box["w"],
        "h": box["h"],
    }


def _needles_from_snippet(snippet: str) -> list[str]:
    cleaned = _SOFT_HYPHEN.sub("", snippet)
    cleaned = _WS.sub(" ", cleaned).strip()
    if len(cleaned) < 4:
        return []
    needles = [cleaned]
    if len(cleaned) > 140:
        needles.append(cleaned[:140].rsplit(" ", 1)[0] or cleaned[:140])
    words = cleaned.split()
    if len(words) > 12:
        needles.append(" ".join(words[:12]))
    elif len(words) > 7:
        needles.append(" ".join(words[:7]))
    seen: set[str] = set()
    out: list[str] = []
    for n in needles:
        if n not in seen and len(n) >= 4:
            seen.add(n)
            out.append(n)
    return out


def _rects_for_quote_native(doc: fitz.Document, quote: str) -> list[dict]:
    quote = (quote or "").strip()
    if not quote:
        return []
    found: list[dict] = []
    for page_no, page in enumerate(doc, start=1):
        boxes = _native_boxes(page)
        if len(boxes) >= MIN_NATIVE_WORDS:
            for item in match_quote_boxes(boxes, quote):
                found.append({"page": page_no, **item})
            if found:
                return found
        text = page.get_text("text") or ""
        loc = find_quote(text, quote)
        if not loc:
            continue
        snippet = text[loc[0] : loc[1]]
        hits: list[fitz.Rect] = []
        for needle in _needles_from_snippet(snippet):
            try:
                hits = page.search_for(needle) or []
            except Exception:  # noqa: BLE001
                hits = []
            if hits:
                break
        for rect in hits[:8]:
            item = _norm_rect(page_no, rect, page)
            if item:
                found.append(item)
        if found:
            break
    return found


def anchor_pdf_rects(path: Path, findings: list[Finding]) -> None:
    """Escribe `rects_json` cuando hay capa de texto. Los escaneados se anclan en el visor."""
    if not findings:
        return
    if not path.is_file():
        for finding in findings:
            finding.rects_json = "[]"
        return
    try:
        doc = fitz.open(path)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo abrir el PDF para anclar subrayados")
        for finding in findings:
            finding.rects_json = "[]"
        return
    try:
        sample = " ".join((p.get_text("text") or "")[:200] for p in list(doc)[:3])
        if len(sample.strip()) < 40:
            return
        for finding in findings:
            rects: list[dict] = []
            seen: set[tuple] = set()
            for quote in (finding.quote, finding.quote_secondary):
                if not quote:
                    continue
                for item in _rects_for_quote_native(doc, quote):
                    key = (item["page"], item["x"], item["y"], item["w"], item["h"])
                    if key in seen:
                        continue
                    seen.add(key)
                    rects.append(item)
            finding.rects_json = json.dumps(rects[:32])
    finally:
        doc.close()
