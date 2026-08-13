"""Reglas de negocio puras del dominio: vocabulario de hallazgos,
anclaje de citas al texto y fórmula del puntaje de validación.
Sin dependencias de frameworks ni de I/O.
"""

import re

from .entities import Finding

VALID_KINDS = {"importante", "alerta", "contradiccion", "inconsistencia", "referencia"}
VALID_SEVERITIES = {"baja", "media", "alta"}
VALID_CLASSIFICATIONS = {"aprobable", "revisar", "alto_riesgo"}

# Ejes: el contenido manda. Crossref es residual y nunca tumba un paper bueno.
SCORE_WEIGHTS = {
    "contenido": 0.65,
    "coherencia": 0.30,
    "referencias": 0.05,
}

# Restas dentro de cada eje (no son puntos globales).
_ALERTA_PENALTY = {"baja": 1, "media": 3, "alta": 7}
_MAX_ALERTA_PENALTY = 18
_CONTRADICCION_PENALTY = {"baja": 8, "media": 16, "alta": 28}
_INCONSISTENCIA_PENALTY = {"baja": 4, "media": 10, "alta": 18}
_REF_ISSUE_PENALTY = {"baja": 1, "media": 2, "alta": 3}

_TOKEN_RE = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)


def _counts_score(finding: dict) -> bool:
    return finding.get("score_impact") is not False


def _content_axis(findings: list[dict]) -> int:
    """Sustancia del paper: parte alta. Las alertas restan poco y con tope."""
    importantes = sum(1 for f in findings if f.get("kind") == "importante")
    score = 85 + min(12, importantes * 2)
    alerta_hit = 0
    for f in findings:
        if f.get("kind") != "alerta" or not _counts_score(f):
            continue
        alerta_hit += _ALERTA_PENALTY.get(str(f.get("severity")), 3)
    score -= min(_MAX_ALERTA_PENALTY, alerta_hit)
    return max(0, min(100, score))


def _coherence_axis(findings: list[dict]) -> int:
    """Sin contradicciones = 100. Una contradicción grave baja fuerte este eje."""
    score = 100
    for f in findings:
        if not _counts_score(f):
            continue
        kind = f.get("kind")
        severity = str(f.get("severity"))
        if kind == "contradiccion":
            score -= _CONTRADICCION_PENALTY.get(severity, 20)
        elif kind == "inconsistencia":
            score -= _INCONSISTENCIA_PENALTY.get(severity, 14)
    return max(0, min(100, score))


def _references_axis(findings: list[dict], references_output: dict | None) -> int:
    """Eje residual. Crossref no decide el puntaje: base alta, bonus mínimo."""
    xr = (references_output or {}).get("verificacion_crossref") or {}
    verified = int(xr.get("verificadas") or 0)
    score = 88 + min(12, verified * 2)
    for f in findings:
        if f.get("kind") != "referencia" or not _counts_score(f):
            continue
        score -= _REF_ISSUE_PENALTY.get(str(f.get("severity")), 2)
    return max(0, min(100, score))


def score_axes(
    findings: list[dict],
    references_output: dict | None = None,
) -> dict:
    contenido = _content_axis(findings)
    coherencia = _coherence_axis(findings)
    referencias = _references_axis(findings, references_output)
    total = int(
        round(
            contenido * SCORE_WEIGHTS["contenido"]
            + coherencia * SCORE_WEIGHTS["coherencia"]
            + referencias * SCORE_WEIGHTS["referencias"]
        )
    )
    return {
        "contenido": contenido,
        "coherencia": coherencia,
        "referencias": referencias,
        "pesos": dict(SCORE_WEIGHTS),
        "total": max(0, min(100, total)),
    }


def classify_from_axes(axes: dict, findings: list[dict]) -> str:
    """Etiqueta final: el contenido manda. Crossref no puede tumbar un paper bueno."""
    contenido = int(axes.get("contenido") or 0)
    coherencia = int(axes.get("coherencia") or 0)
    total = int(axes.get("total") or 0)
    alta_contra = any(
        f.get("kind") == "contradiccion"
        and f.get("severity") == "alta"
        and f.get("score_impact") is not False
        for f in findings
    )
    # Paper sólido y sin contradicción grave → aprobable, da igual Crossref
    if contenido >= 75 and coherencia >= 70 and not alta_contra:
        return "aprobable"
    if total >= 78 and not alta_contra:
        return "aprobable"
    if contenido >= 60 and coherencia >= 50:
        return "revisar"
    if total >= 50:
        return "revisar"
    return "alto_riesgo"


def compute_score(
    findings: list[dict],
    references_output: dict | None = None,
) -> int:
    """Puntaje 0-100: 65% contenido, 30% coherencia, 5% referencias."""
    return score_axes(findings, references_output)["total"]


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
