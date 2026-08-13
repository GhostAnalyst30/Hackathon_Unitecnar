"""Ingesta multi-formato: PDF (texto nativo u OCR), DOCX e imágenes.

Salida normalizada: HTML editable (para TipTap) + texto plano (para agentes y anclaje).
"""

import asyncio
import base64
import html as html_lib
from pathlib import Path

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

# Umbral de caracteres por página para considerar que un PDF tiene capa de texto útil
MIN_CHARS_PER_PAGE = 40

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


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


def _plain_text_to_html(text: str) -> str:
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    parts = []
    for block in blocks:
        escaped = html_lib.escape(block).replace("\n", "<br/>")
        parts.append(f"<p>{escaped}</p>")
    return "\n".join(parts)


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
    """Devuelve (html, ocr_usado). Usa texto nativo y OCR solo en páginas escaneadas."""
    doc = fitz.open(path)
    try:
        html_parts: list[str] = []
        ocr_used = False
        for page in doc:
            text = page.get_text("text").strip()
            if len(text) >= MIN_CHARS_PER_PAGE:
                html_parts.append(_plain_text_to_html(text))
            else:
                # Página escaneada o solo imágenes: OCR
                data_url = await asyncio.to_thread(_pixmap_data_url, page)
                md_text = await ocr_image(settings, data_url, OCR_PROMPT)
                html_parts.append(_markdown_to_html(md_text))
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
