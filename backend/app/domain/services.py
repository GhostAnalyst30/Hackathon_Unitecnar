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

    # 1. Búsqueda exacta
    idx = text.find(quote)
    if idx != -1:
        return idx, idx + len(quote)

    # 2. Búsqueda insensible a espacios en blanco y mayúsculas
    tokens = quote.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(tok) for tok in tokens)
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.start(), match.end()

    # 3. Si la cita es larga, intenta con un prefijo (primeras ~12 palabras)
    if len(tokens) > 12:
        prefix_pattern = r"\s+".join(re.escape(tok) for tok in tokens[:12])
        match = re.search(prefix_pattern, text, re.IGNORECASE)
        if match:
            return match.start(), match.end()

    return None


def anchor_findings(text: str, findings: list[Finding]) -> None:
    """Actualiza in-place los offsets y el flag `anchored` de cada hallazgo."""
    for finding in findings:
        result = find_quote(text, finding.quote)
        if result:
            finding.start_offset, finding.end_offset = result
            finding.anchored = True
        else:
            finding.start_offset = None
            finding.end_offset = None
            finding.anchored = False
