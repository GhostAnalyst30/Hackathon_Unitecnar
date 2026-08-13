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
from .llm import ocr_image

OCR_PROMPT = (
    "Extrae todo el texto del documento de la imagen en formato Markdown, "
    "conservando la estructura de títulos, párrafos, listas y tablas. "
    "No agregues comentarios ni explicaciones, solo el contenido del documento."
)

MIN_CHARS_PER_PAGE = 40
# page.find_tables() es muy lento y pide pymupdf_layout; se omite por velocidad.
EXTRACT_PDF_TABLES = False
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
    table_rects = [t[0] for t in tables]
    used_tables: set[int] = set()

    tags: list[str] = [
        "<hr>",
        f"<p><em>— Página {page_number} —</em></p>",
    ]

    def flush_table_before(y: float) -> None:
        for i, (bbox, html) in enumerate(tables):
            if i in used_tables:
                continue
            if bbox[1] <= y:
                tags.append(html)
                used_tables.add(i)

    for block in text_blocks:
        bbox = tuple(block["bbox"])
        if any(_overlaps(bbox, r) for r in table_rects):
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
        if level:
            tags.append(f"<h{level}>{_escape(text)}</h{level}>")
        elif _LIST_RE.match(text):
            item = _LIST_RE.sub("", text)
            tags.append(f"<li>{_escape(item)}</li>")
        else:
            tags.append(f"<p>{_escape(text)}</p>")

    for i, (_, html) in enumerate(tables):
        if i not in used_tables:
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


async def _ingest_pdf(path: Path, settings: AppSettings) -> tuple[str, bool]:
    """Devuelve (html, ocr_usado). Estructura nativa; OCR solo en páginas escaneadas."""
    doc = fitz.open(path)
    try:
        html_parts: list[str] = []
        ocr_used = False
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) >= MIN_CHARS_PER_PAGE:
                html_parts.append(_pdf_page_to_html(page, index))
            else:
                data_url = await asyncio.to_thread(_pixmap_data_url, page)
                md_text = await ocr_image(settings, data_url, OCR_PROMPT)
                page_html = _markdown_to_html(md_text)
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
    data_url = await asyncio.to_thread(_image_file_data_url, path)
    md_text = await ocr_image(settings, data_url, OCR_PROMPT)
    return _markdown_to_html(md_text)


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
