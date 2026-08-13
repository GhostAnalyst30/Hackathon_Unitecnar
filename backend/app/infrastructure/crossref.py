"""Adaptador de la Crossref REST API para verificar referencias bibliográficas.

Por cada referencia extraída por el agente se consulta
https://api.crossref.org/works (query.bibliographic) y se decide si la fuente
existe realmente, devolviendo DOI y metadatos. API pública, sin key.
"""

import asyncio
import logging
import re

import httpx

from ..config import CROSSREF_MAILTO

logger = logging.getLogger("crossref")

CROSSREF_URL = "https://api.crossref.org/works"
MAX_CONCURRENT_LOOKUPS = 8
LOOKUP_TIMEOUT = 10
SEARCH_ROWS = 1
# Solapamiento mínimo de tokens del título de Crossref presentes en la referencia
MIN_TITLE_OVERLAP = 0.7
# Un título con menos tokens significativos que esto no es evidencia suficiente
MIN_TITLE_TOKENS = 3
# Diferencia máxima de años entre la referencia y el registro de Crossref
MAX_YEAR_DIFF = 2

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_STOPWORDS = {
    "the", "a", "an", "of", "and", "in", "on", "for", "to", "with", "from", "into",
    "el", "la", "los", "las", "de", "del", "y", "en", "un", "una", "unas", "unos",
    "para", "con", "por", "que", "como", "sobre", "entre", "sus", "mas", "más",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-záéíóúüñ0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _title_overlap(reference: str, title: str) -> float:
    title_tokens = _tokens(title)
    if not title_tokens:
        return 0.0
    ref_tokens = _tokens(reference)
    return len(title_tokens & ref_tokens) / len(title_tokens)


def _parse_item(reference: str, item: dict) -> dict:
    title = (item.get("title") or [""])[0]
    doi = item.get("DOI", "")
    issued = item.get("issued", {}).get("date-parts", [[None]])
    year = issued[0][0] if issued and issued[0] else None
    container = (item.get("container-title") or [""])[0]

    doi_in_ref = bool(doi) and doi.lower() in reference.lower()
    overlap = _title_overlap(reference, title)

    # Evidencia de coincidencia: DOI explícito, o título suficientemente
    # informativo cuyos tokens aparecen casi todos en la referencia.
    title_informative = len(_tokens(title)) >= MIN_TITLE_TOKENS
    verified = doi_in_ref or (title_informative and overlap >= MIN_TITLE_OVERLAP)

    # Si la referencia declara un año muy distinto al del registro, no es la misma obra
    ref_years = [int(y.group(0)) for y in _YEAR_RE.finditer(reference)]
    if verified and not doi_in_ref and year and ref_years:
        if min(abs(year - ry) for ry in ref_years) > MAX_YEAR_DIFF:
            verified = False

    return {
        "verificada": verified,
        "doi": doi or None,
        "titulo_crossref": title or None,
        "anio": year,
        "revista": container or None,
        "coincidencia": round(overlap, 2),
    }


async def _verify_one(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, reference: str
) -> dict:
    async with semaphore:
        try:
            # Si la referencia trae DOI, consultarlo directamente es más fiable
            doi_match = _DOI_RE.search(reference)
            if doi_match:
                doi = doi_match.group(0).rstrip(".,;)")
                resp = await client.get(f"{CROSSREF_URL}/{doi}")
                if resp.status_code == 200:
                    return _parse_item(reference, resp.json()["message"])

            resp = await client.get(
                CROSSREF_URL,
                params={
                    "query.bibliographic": reference[:400],
                    "rows": SEARCH_ROWS,
                    "select": "DOI,title,issued,container-title",
                },
            )
            resp.raise_for_status()
            items = resp.json().get("message", {}).get("items", [])
            if not items:
                return {"verificada": False, "doi": None, "coincidencia": 0.0}
            # Evalúa los mejores candidatos y quédate con el de mayor coincidencia
            parsed = [_parse_item(reference, item) for item in items]
            parsed.sort(
                key=lambda p: (p["verificada"] is True, p.get("coincidencia") or 0),
                reverse=True,
            )
            return parsed[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref falló para %r: %s", reference[:80], exc)
            return {"verificada": None, "error": str(exc)}


async def verify_references(references: list[str]) -> list[dict]:
    """Verifica una lista de referencias contra Crossref (en paralelo acotado).

    Devuelve un dict por referencia:
    {verificada: bool|None, doi, titulo_crossref, anio, revista, coincidencia}
    (`verificada: None` significa que Crossref no estuvo disponible).
    """
    if not references:
        return []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)
    headers = {"User-Agent": f"GhostAnalyst/1.0 (mailto:{CROSSREF_MAILTO})"}
    async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT, headers=headers) as client:
        return list(
            await asyncio.gather(
                *(_verify_one(client, semaphore, ref) for ref in references)
            )
        )
