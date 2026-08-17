"""Ingesta multi-formato: PDF (estructura nativa u OCR), DOCX e imágenes.

Salida: HTML semántico editable (títulos, párrafos, listas, tablas, páginas)
+ texto plano para agentes y anclaje.
"""

from __future__ import annotations

import asyncio
import base64
import html as html_lib
import re
from pathlib import Path
from statistics import median

import pymupdf as fitz
import mammoth
import markdown as md_lib
from bs4 import BeautifulSoup

from ..domain.entities import AppSettings
from .llm import LLMNotConfigured, ocr_image
from .rapid_ocr import pixmap_to_numpy, run_ocr

OCR_PROMPT = (
    "Extrae todo el texto del documento de la imagen en formato Markdown, "
    "conservando la estructura de títulos, párrafos, listas y tablas. "
    "No agregues comentarios ni explicaciones, solo el contenido del documento."
)

MIN_CHARS_PER_PAGE = 40
# page.find_tables() es muy lento y pide pymupdf_layout; se omite por velocidad.
EXTRACT_PDF_TABLES = False
MAX_FIGURES_PER_PAGE = 6
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Encabezados típicos de papers, aunque el tamaño de fuente no destaque
_SECTION_RE = re.compile(
    r"^(abstract|resumen|introduction|introducci[oó]n|background|"
    r"related work|methods?|methodology|metodolog[ií]a|materials|"
    r"results?|resultados|discussion|discusi[oó]n|conclusion(?:es)?|"
    r"references|referencias|bibliography|bibliograf[ií]a|"
    r"acknowledg(?:e)?ments|agradecimientos|appendix|anexo|"
    r"keywords?|palabras\s+clave)\s*$",
    re.I,
)
_NUMBERED_SECTION_RE = re.compile(r"^(\d+(?:\.\d+){0,3})[\.\)]?\s+\S")
_LIST_RE = re.compile(r"^(?:[\u2022\u2023\u25E6•·\-–—]|\d+[\.\)])\s+")
_CAPTION_RE = re.compile(
    r"^(?:fig(?:ure|\.)?|figura|gr[aá]fico(?:s)?|chart|plot|diagrama)\b",
    re.I,
)


def detect_format(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".docx", ".doc"}:
        return "docx"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    raise ValueError(f"Formato no soportado: {ext}. Usa PDF, DOCX o imagen.")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n")


def _markdown_to_html(text: str) -> str:
    return md_lib.markdown(text, extensions=["tables", "fenced_code"])


def _escape(text: str) -> str:
    return html_lib.escape(text)


def _join_lines(lines: list[str]) -> str:
    """Une líneas de un bloque, reparando cortes con guion de justificación."""
    if not lines:
        return ""
    out = lines[0].rstrip()
    for nxt in lines[1:]:
        nxt = nxt.strip()
        if not nxt:
            continue
        if out.endswith("-") and nxt[:1].islower():
            out = out[:-1] + nxt
        else:
            out = f"{out} {nxt}"
    return re.sub(r"[ \t]+", " ", out).strip()


def _wrap_lists(tags: list[str]) -> list[str]:
    out: list[str] = []
    in_ul = False
    for tag in tags:
        is_li = tag.startswith("<li")
        if is_li and not in_ul:
            out.append("<ul>")
            in_ul = True
        elif not is_li and in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(tag)
    if in_ul:
        out.append("</ul>")
    return out


def _ocr_line_tag(text: str) -> str:
    if _CAPTION_RE.match(text) and len(text) < 240:
        return f"<p><em>{_escape(text)}</em></p>"
    if _SECTION_RE.match(text.rstrip(":")) or (
        _NUMBERED_SECTION_RE.match(text) and len(text) < 140
    ):
        return f"<h2>{_escape(text)}</h2>"
    if text.isupper() and 3 < len(text) < 80:
        return f"<h3>{_escape(text)}</h3>"
    if _LIST_RE.match(text):
        return f"<li>{_escape(_LIST_RE.sub('', text))}</li>"
    return f"<p>{_escape(text)}</p>"


def _ocr_items_to_html(items: list[dict]) -> str:
    """Agrupa cajas RapidOCR en líneas y párrafos HTML."""
    if not items:
        return ""
    heights = [max(it["y1"] - it["y0"], 1.0) for it in items]
    med_h = median(heights)
    line_tol = max(med_h * 0.65, 6.0)
    para_gap = med_h * 1.5
    ordered = sorted(items, key=lambda it: (it["y0"], it["x0"]))
    lines: list[list[dict]] = []
    for it in ordered:
        if lines:
            prev = lines[-1]
            avg_y = sum(p["y0"] for p in prev) / len(prev)
            if abs(it["y0"] - avg_y) <= line_tol:
                prev.append(it)
                continue
        lines.append([it])
    line_rows: list[tuple[float, str]] = []
    for line in lines:
        line.sort(key=lambda it: it["x0"])
        text = re.sub(r"[ \t]+", " ", " ".join(it["text"] for it in line)).strip()
        if text:
            line_rows.append((sum(it["y0"] for it in line) / len(line), text))
    tags: list[str] = []
    para: list[str] = []
    prev_y: float | None = None

    def flush_para() -> None:
        joined = _join_lines(para)
        para.clear()
        if joined:
            tags.append(_ocr_line_tag(joined))

    for y, text in line_rows:
        standalone = bool(
            _CAPTION_RE.match(text)
            or _SECTION_RE.match(text.rstrip(":"))
            or _LIST_RE.match(text)
            or (_NUMBERED_SECTION_RE.match(text) and len(text) < 140)
        )
        if para and (standalone or (prev_y is not None and y - prev_y > para_gap)):
            flush_para()
        if standalone:
            tags.append(_ocr_line_tag(text))
        else:
            para.append(text)
        prev_y = y
    flush_para()
    return "\n".join(_wrap_lists(tags))


def _figure_html(caption: str, labels: list[str]) -> str:
    parts: list[str] = []
    if caption:
        parts.append(f"<p><em>{_escape(caption)}</em></p>")
    else:
        parts.append("<p><em>Figura o gráfica detectada en el original.</em></p>")
    if labels:
        shown = " · ".join(labels[:28])
        parts.append(f"<p>Texto leído en la gráfica: {_escape(shown)}</p>")
    elif not caption:
        parts[0] = (
            "<p><em>Figura o gráfica detectada en el original "
            "(sin texto legible en ejes o leyenda). Revisa el archivo original.</em></p>"
        )
    return "\n".join(parts)


def _ocr_figure_html(
    page: fitz.Page, bbox: tuple[float, float, float, float], caption: str
) -> str:
    pix = page.get_pixmap(
        clip=fitz.Rect(bbox), matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB
    )
    items = run_ocr(pixmap_to_numpy(pix))
    labels: list[str] = []
    cap = caption
    for it in items:
        text = it["text"]
        if not cap and _CAPTION_RE.match(text):
            cap = text
            continue
        if _CAPTION_RE.match(text):
            continue
        labels.append(text)
    return _figure_html(cap, labels)


def _block_plain(block: dict) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        raw = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
        if raw:
            lines.append(raw)
    return _join_lines(lines)


def _caption_for_image(
    text_blocks: list[dict], bbox: tuple[float, float, float, float]
) -> tuple[str, tuple[float, float, float, float] | None]:
    y1 = bbox[3]
    best = ""
    best_bbox: tuple[float, float, float, float] | None = None
    best_d = 56.0
    for block in text_blocks:
        tb = tuple(block["bbox"])
        gap = tb[1] - y1
        if gap < -8 or gap > 56:
            continue
        if tb[2] < bbox[0] - 24 or tb[0] > bbox[2] + 24:
            continue
        text = _block_plain(block)
        if not text or not _CAPTION_RE.match(text):
            continue
        if gap < best_d:
            best_d = gap
            best = text
            best_bbox = tb  # type: ignore[assignment]
    return best, best_bbox


def _collect_figures(
    page: fitz.Page, data: dict, text_blocks: list[dict]
) -> tuple[list[tuple[tuple[float, float, float, float], str]], set[tuple]]:
    pw = page.rect.width or 1.0
    ph = page.rect.height or 1.0
    figures: list[tuple[tuple[float, float, float, float], str]] = []
    skip: set[tuple] = set()
    for block in data.get("blocks", []):
        if len(figures) >= MAX_FIGURES_PER_PAGE:
            break
        if block.get("type") != 1:
            continue
        bbox = tuple(block["bbox"])
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width < pw * 0.22 or height < ph * 0.10:
            continue
        if bbox[1] < ph * 0.04 and height < ph * 0.12:
            continue
        caption, cap_bbox = _caption_for_image(text_blocks, bbox)
        if cap_bbox:
            skip.add(cap_bbox)
        try:
            figures.append((bbox, _ocr_figure_html(page, bbox, caption)))
        except Exception:  # noqa: BLE001
            figures.append((bbox, _figure_html(caption, [])))
    return figures, skip


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, ...], pad: float = 2.0) -> bool:
    return not (
        a[2] < b[0] - pad or a[0] > b[2] + pad or a[3] < b[1] - pad or a[1] > b[3] + pad
    )


def _table_to_html(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""
    parts = ["<table>"]
    for i, row in enumerate(rows):
        cells = [c.strip() if c else "" for c in row]
        if not any(cells):
            continue
        tag = "th" if i == 0 else "td"
        inner = "".join(f"<{tag}>{_escape(c)}</{tag}>" for c in cells)
        parts.append(f"<tr>{inner}</tr>")
    parts.append("</table>")
    return "\n".join(parts) if len(parts) > 2 else ""


def _extract_tables(page: fitz.Page) -> list[tuple[tuple[float, float, float, float], str]]:
    try:
        finder = page.find_tables()
    except Exception:  # noqa: BLE001
        return []
    found: list[tuple[tuple[float, float, float, float], str]] = []
    for tab in getattr(finder, "tables", []) or []:
        try:
            html = _table_to_html(tab.extract())
        except Exception:  # noqa: BLE001
            continue
        if html:
            found.append((tuple(tab.bbox), html))
    return found


def _heading_level(text: str, size: float, body: float, bold: bool) -> int | None:
    if not text or not body:
        return None
    ratio = size / body
    short = len(text) < 140
    numbered = bool(_NUMBERED_SECTION_RE.match(text))
    named = bool(_SECTION_RE.match(text.rstrip(":")))
    all_caps = text.isupper() and 3 < len(text) < 80

    if ratio >= 1.55 and short:
        return 1
    if named or (ratio >= 1.28 and short) or (all_caps and ratio >= 1.05):
        return 2
    if numbered or (ratio >= 1.14 and bold and short) or (bold and all_caps and short):
        return 3
    return None


def _sort_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    if not blocks:
        return []
    mid = page_width / 2
    left = [b for b in blocks if b["bbox"][0] < mid - 24]
    right = [b for b in blocks if b["bbox"][0] >= mid - 24]
    # Dos columnas: primero la izquierda (arriba→abajo), luego la derecha
    if len(left) >= 3 and len(right) >= 3:
        return sorted(left, key=lambda b: b["bbox"][1]) + sorted(right, key=lambda b: b["bbox"][1])
    return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))


def _pdf_page_to_html(page: fitz.Page, page_number: int) -> str:
    """Convierte una página a HTML semántico a partir de bloques y tamaños de fuente."""
    data = page.get_text("dict")
    text_blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]
    text_blocks = _sort_blocks(text_blocks, page.rect.width)

    sizes: list[float] = []
    for block in text_blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(float(span.get("size") or 0))
    body = median(sizes) if sizes else 11.0

    # find_tables() es muy lento sin pymupdf_layout; se omite a propósito.
    tables = _extract_tables(page) if EXTRACT_PDF_TABLES else []
    figures, skip_captions = _collect_figures(page, data, text_blocks)
    floaters = list(tables) + list(figures)
    table_rects = [t[0] for t in tables]
    figure_rects = [f[0] for f in figures]
    used_floaters: set[int] = set()

    tags: list[str] = [
        "<hr>",
        f"<p><em>— Página {page_number} —</em></p>",
    ]

    def flush_table_before(y: float) -> None:
        for i, (bbox, html) in enumerate(floaters):
            if i in used_floaters:
                continue
            if bbox[1] <= y:
                tags.append(html)
                used_floaters.add(i)

    for block in text_blocks:
        bbox = tuple(block["bbox"])
        if bbox in skip_captions:
            continue
        if any(_overlaps(bbox, r) for r in table_rects):
            continue
        if any(_overlaps(bbox, r, pad=4.0) for r in figure_rects):
            continue

        flush_table_before(bbox[1])

        lines: list[str] = []
        max_size = 0.0
        bold = False
        for line in block.get("lines", []):
            raw = "".join(span.get("text", "") for span in line.get("spans", []))
            if raw.strip():
                lines.append(raw.strip())
            for span in line.get("spans", []):
                max_size = max(max_size, float(span.get("size") or 0))
                if int(span.get("flags") or 0) & 16:
                    bold = True

        text = _join_lines(lines)
        if not text:
            continue

        level = _heading_level(text, max_size, body, bold)
        if _CAPTION_RE.match(text) and len(text) < 240:
            tags.append(f"<p><em>{_escape(text)}</em></p>")
        elif level:
            tags.append(f"<h{level}>{_escape(text)}</h{level}>")
        elif _LIST_RE.match(text):
            item = _LIST_RE.sub("", text)
            tags.append(f"<li>{_escape(item)}</li>")
        else:
            tags.append(f"<p>{_escape(text)}</p>")

    for i, (_, html) in enumerate(floaters):
        if i not in used_floaters:
            tags.append(html)

    return "\n".join(_wrap_lists(tags))


def _pixmap_data_url(page: fitz.Page) -> str:
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    png_bytes = pix.tobytes("png")
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _image_file_data_url(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mime = "jpeg" if ext in {"jpg", "jpeg"} else ext
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


async def _vision_ocr_html(settings: AppSettings, data_url: str) -> str:
    try:
        md_text = await ocr_image(settings, data_url, OCR_PROMPT)
    except LLMNotConfigured:
        return ""
    except Exception:  # noqa: BLE001
        return ""
    return _markdown_to_html(md_text or "")


def _rapid_page_html(page: fitz.Page) -> str:
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB)
        return _ocr_items_to_html(run_ocr(pixmap_to_numpy(pix)))
    except Exception:  # noqa: BLE001
        return ""


def _empty_scan_note() -> str:
    return (
        "<p><em>Página o imagen sin texto legible "
        "(posible gráfica, foto o escaneo de baja calidad). "
        "Revisa el archivo original.</em></p>"
    )


async def _ingest_pdf(path: Path, settings: AppSettings) -> tuple[str, bool]:
    """Devuelve (html, ocr_usado). Estructura nativa; OCR local solo en páginas escaneadas."""
    doc = fitz.open(path)
    try:
        html_parts: list[str] = []
        ocr_used = False
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) >= MIN_CHARS_PER_PAGE:
                html_parts.append(await asyncio.to_thread(_pdf_page_to_html, page, index))
            else:
                page_html = await asyncio.to_thread(_rapid_page_html, page)
                if not html_to_text(page_html).strip():
                    data_url = await asyncio.to_thread(_pixmap_data_url, page)
                    page_html = await _vision_ocr_html(settings, data_url)
                if not html_to_text(page_html).strip():
                    page_html = _empty_scan_note()
                html_parts.append(
                    f"<hr>\n<p><em>— Página {index} —</em></p>\n{page_html}"
                )
                ocr_used = True
        return "\n".join(html_parts), ocr_used
    finally:
        doc.close()


def _ingest_docx(path: Path) -> str:
    with open(path, "rb") as f:
        result = mammoth.convert_to_html(f)
    return result.value


async def _ingest_image(path: Path, settings: AppSettings) -> str:
    def _local() -> str:
        doc = fitz.open(path)
        try:
            parts: list[str] = []
            for i, page in enumerate(doc, start=1):
                html = _rapid_page_html(page)
                if doc.page_count > 1:
                    parts.append(f"<hr>\n<p><em>— Página {i} —</em></p>\n{html}")
                else:
                    parts.append(html)
            return "\n".join(parts)
        finally:
            doc.close()

    html = await asyncio.to_thread(_local)
    if html_to_text(html).strip():
        return html
    data_url = await asyncio.to_thread(_image_file_data_url, path)
    fallback = await _vision_ocr_html(settings, data_url)
    return fallback if html_to_text(fallback).strip() else _empty_scan_note()


async def ingest_file(
    path: Path, file_format: str, settings: AppSettings
) -> tuple[str, str, bool]:
    """Procesa el archivo y devuelve (content_html, content_text, ocr_usado)."""
    ocr_used = False
    if file_format == "pdf":
        html, ocr_used = await _ingest_pdf(path, settings)
    elif file_format == "docx":
        html = await asyncio.to_thread(_ingest_docx, path)
    elif file_format == "image":
        html = await _ingest_image(path, settings)
        ocr_used = True
    else:
        raise ValueError(f"Formato desconocido: {file_format}")

    text = html_to_text(html)
    if not text.strip():
        raise ValueError("No se pudo extraer texto del documento.")
    return html, text, ocr_used
