"""Agente Lector: estructura del paper, resumen e información importante."""

from ...domain.entities import AppSettings
from .base import call_agent_json, normalize_finding, truncate_doc

SYSTEM = """Eres un agente lector de papers. Responde SOLO un JSON compacto, sin markdown:
{"resumen":"3-5 frases","estructura":["secciones"],"tema_principal":"...","hallazgos":[{"cita":"copia literal 8-25 palabras","tipo":"importante|alerta","severidad":"baja|media|alta","explicacion":"por qué resaltar esto"}]}
Marca 8 a 12 fragmentos distintos: objetivo, tesis, método, resultados/números, limitaciones, conclusiones y afirmaciones fuertes. Citas EXACTAS del texto. Español."""


async def run_reader(settings: AppSettings, text: str) -> tuple[dict, list[dict]]:
    result = await call_agent_json(
        settings,
        SYSTEM,
        f"Documento a analizar:\n\n{truncate_doc(text)}",
        settings.reader_instructions,
        max_tokens=1400,
    )
    findings = []
    for raw in result.get("hallazgos", []) or []:
        f = normalize_finding(raw, agent="reader", default_kind="importante")
        if f:
            findings.append(f)
    return result, findings
