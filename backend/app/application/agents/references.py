"""Agente de Referencias: extrae bibliografía, evalúa su relevancia y
VERIFICA cada fuente contra la Crossref REST API (existencia real, DOI, año).
"""

from ...domain.entities import AppSettings
from ...infrastructure.crossref import verify_references
from .base import bibliography_slice, call_agent_json, normalize_finding

SYSTEM = """Revisor de bibliografía. SOLO JSON compacto, sin markdown:
{"analisis":"1-2 frases","referencias":[{"referencia":"texto de la ref","relevancia":"alta|media|baja","comentario":"breve"}],"hallazgos":[{"cita":"copia literal ≤30 palabras","tipo":"referencia|alerta","severidad":"baja|media|alta","explicacion":"problema"}]}
Máximo 12 referencias y 4 hallazgos. Si no hay bibliografía, un hallazgo tipo alerta. Español."""


async def run_references(
    settings: AppSettings, text: str, reader_output: dict | None = None
) -> tuple[dict, list[dict]]:
    del reader_output
    result = await call_agent_json(
        settings,
        SYSTEM,
        f"Documento (inicio + bibliografía):\n\n{bibliography_slice(text)}",
        settings.references_instructions,
        max_tokens=1000,
    )

    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="references", default_kind="referencia")
        if f:
            findings.append(f)

    # Verificación de fuentes contra Crossref (tope para no alargar el pipeline)
    references = (result.get("referencias", []) or [])[:12]
    result["referencias"] = references
    ref_texts = [str(r.get("referencia", "")).strip() for r in references]
    verifications = await verify_references([t for t in ref_texts if t])

    verified_count = 0
    unverified_count = 0
    v_iter = iter(verifications)
    for ref in references:
        if not str(ref.get("referencia", "")).strip():
            continue
        verification = next(v_iter, {})
        ref.update(verification)
        if verification.get("verificada") is True:
            verified_count += 1
        elif verification.get("verificada") is False:
            unverified_count += 1
            findings.append(
                {
                    "agent": "references",
                    "kind": "referencia",
                    "severity": "media",
                    "quote": str(ref.get("referencia", ""))[:300],
                    "quote_secondary": None,
                    "explanation": (
                        "No se encontró esta fuente en Crossref: puede ser inexistente, "
                        "estar mal citada o no estar indexada. Verifícala manualmente."
                    ),
                }
            )

    result["verificacion_crossref"] = {
        "total": len([t for t in ref_texts if t]),
        "verificadas": verified_count,
        "no_encontradas": unverified_count,
    }
    return result, findings
