"""Reglas de negocio puras del dominio: vocabulario de hallazgos,
anclaje de citas al texto y fórmula del puntaje de validación.
Sin dependencias de frameworks ni de I/O.
"""

import re

from .entities import Finding

VALID_KINDS = {"importante", "alerta", "contradiccion", "inconsistencia", "referencia"}
VALID_SEVERITIES = {"baja", "media", "alta"}
VALID_CLASSIFICATIONS = {"aprobable", "revisar", "alto_riesgo"}

# Penalización por severidad. Los hallazgos "importante" no restan: son información clave.
SEVERITY_PENALTY = {"baja": 2, "media": 6, "alta": 12}
PENALIZING_KINDS = {"alerta", "contradiccion", "inconsistencia", "referencia"}

_TOKEN_RE = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)


def compute_score(findings: list[dict]) -> int:
    """Puntaje de validación 0-100 ponderado por severidad de las alertas."""
    penalty = 0
    for f in findings:
        if f["kind"] in PENALIZING_KINDS:
            penalty += SEVERITY_PENALTY.get(f["severity"], 6)
    return max(0, 100 - penalty)


def find_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Busca la cita en el texto. Devuelve (inicio, fin) sobre el texto original."""
    if not quote or not quote.strip():
        return None

    stripped = quote.strip().strip("«»\"“”‘’'")
    for candidate in (quote, stripped):
        idx = text.find(candidate)
        if idx != -1:
            return idx, idx + len(candidate)
        idx = text.lower().find(candidate.lower())
        if idx != -1:
            return idx, idx + len(candidate)

    tokens = stripped.split()
    if not tokens:
        return None

    def _search(pattern: str) -> tuple[int, int] | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.start(), match.end()
        return None

    found = _search(r"\s+".join(re.escape(tok) for tok in tokens))
    if found:
        return found

    loose = _TOKEN_RE.findall(stripped)
    if len(loose) >= 3:
        found = _search(r"[\W_]*".join(re.escape(t) for t in loose))
        if found:
            return found

    for n in (10, 7, 5):
        if len(tokens) > n:
            found = _search(r"\s+".join(re.escape(tok) for tok in tokens[:n]))
            if found:
                return found
        if len(loose) > n:
            found = _search(r"[\W_]*".join(re.escape(t) for t in loose[:n]))
            if found:
                return found

    return None


def anchor_findings(text: str, findings: list[Finding]) -> None:
    """Actualiza in-place los offsets y el flag `anchored` de cada hallazgo."""
    for finding in findings:
        result = find_quote(text, finding.quote)
        if not result and finding.quote_secondary:
            result = find_quote(text, finding.quote_secondary)
        if result:
            finding.start_offset, finding.end_offset = result
            finding.anchored = True
        else:
            finding.start_offset = None
            finding.end_offset = None
            finding.anchored = False
