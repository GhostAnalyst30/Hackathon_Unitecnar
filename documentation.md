# Clumi — documentación de backend y API

Contexto para agentes (Claude Code / Cursor) y para quien toque el código.
La app es **personal, local, sin autenticación**. El humano siempre decide:
nada se valida ni se aplica al documento sin un clic explícito.

- Backend: `http://127.0.0.1:8000` (`uvicorn app.main:app --port 8000` desde `backend/` con `.venv`)
- Frontend: `http://localhost:3000` (Next.js App Router)
- Datos: SQLite `backend/data/app.db` + uploads en `backend/data/uploads/`
- OpenAPI interactivo: `http://127.0.0.1:8000/docs`

---

## 1. Qué hace el sistema

1. El usuario sube PDF / DOCX / imagen.
2. Se extrae HTML editable (estructura nativa; RapidOCR solo en páginas escaneadas e imágenes).
3. Tres agentes LLM corren **en paralelo**: lector, contradicciones, referencias (+ Crossref).
4. Un clasificador **determinista** (sin LLM, salvo instrucciones custom) calcula puntaje 0–100 y etiqueta.
5. El documento queda en `awaiting_review`. El editor resalta hallazgos; el chat propone edits; Validar / Descartar es humano.

No hay modo demo. Sin API key configurada, subir o re-analizar se bloquea.

---

## 2. Arquitectura

Clean architecture **simplificada** (no hexagonal estricta). Dependencias hacia adentro:

```
api/  →  application/  →  domain/
              ↓
        infrastructure/
```

| Capa | Ruta | Responsabilidad | No debe |
|---|---|---|---|
| **Domain** | `backend/app/domain/` | Entidades SQLAlchemy + reglas puras (`anchor_findings`, `compute_score`, vocabularios) | Importar FastAPI, LLM, HTTP |
| **Application** | `backend/app/application/` | DTOs Pydantic, agentes, casos de uso (orquestación) | Hablar HTTP; exponer entidades crudas en la API |
| **Infrastructure** | `backend/app/infrastructure/` | SQLite, OpenAI-compatible LLM, ingest, Crossref, SSE | Contener reglas de negocio |
| **API** | `backend/app/api/routes/` | Routers delgados: DTO ↔ caso de uso, códigos HTTP | Lógica de pipeline o SQL complejo |
| **Composition root** | `backend/app/main.py` | FastAPI, CORS, lifespan (`init_db`, recuperar docs a medias) | |

`config.py` guarda constantes (límites, modelos default, paths). Settings **de usuario** viven en la tabla `app_settings` (una fila `id=1`), no en `.env`.

### Invariantes al cambiar código

- El humano tiene la última palabra (sugerencias de chat solo se aplican en el cliente al hacer clic).
- Errores de LLM/API **no** se muestran crudos al usuario. Usar `public_error_message()` → *«El servidor no pudo leer los datos…»*. El traceback sí va a logs.
- Preferir modelos OpenRouter baratos de pago (Gemini Flash-Lite, GPT-4o mini). Fallbacks configurables: cada agente reintenta y recorre la cadena del usuario antes de marcar error.
- Entidades de dominio no se serializan directo: pasar por DTOs (`application/dtos.py`).
- Los routers no abren sesiones extra ni llaman a LangGraph; delegan en `use_cases`.

---

## 3. Modelo de datos

SQLite vía SQLAlchemy 2. `init_db()` hace `create_all` y añade columnas nuevas con `ALTER TABLE` (`chat_fallback_models`, `ocr_fallback_models`). No hay Alembic.

### `documents`

| Campo | Notas |
|---|---|
| `id` | UUID hex 32 |
| `filename`, `file_path`, `file_format` | `pdf` \| `docx` \| `image` |
| `status` | ver máquina de estados |
| `content_html`, `content_text` | HTML para TipTap; texto plano para agentes y anclaje |
| `score` | 0–100 o null |
| `classification` | `aprobable` \| `revisar` \| `alto_riesgo` |
| `error` | mensaje **público** si `status=error` |
| `ocr_used` | bool |
| `decision_comment` | comentario humano al validar/descartar |

Relaciones (cascade delete): `findings`, `agent_outputs`, `chat_messages`, `process_logs`.

### Estados

```
queued → extracting → analyzing → awaiting_review → validated | discarded
                         ↘ error
```

Al arrancar el servidor, docs en `queued|extracting|analyzing` pasan a `error` (*análisis interrumpido*) para poder Re-analizar.

### `findings`

Hallazgo anclable al texto.

- `agent`: `reader` | `contradictions` | `references`
- `kind`: `importante` | `alerta` | `contradiccion` | `inconsistencia` | `referencia`
- `severity`: `baja` | `media` | `alta`
- `quote` / `quote_secondary`: citas literales (la secundaria se usa en contradicciones)
- `anchored`, `start_offset`, `end_offset`: resultado de `find_quote` sobre `content_text`

Puntaje (`domain/services.py`): parte de 100; restan solo kinds en `PENALIZING_KINDS` (`alerta`, `contradiccion`, `inconsistencia`, `referencia`). `importante` **no** resta. Penalización: baja 2, media 6, alta 12.

Clasificación local: `>=80` aprobable, `50–79` revisar, `<50` alto_riesgo.

### `app_settings`

Proveedor (`openrouter` | `gemini` | `qianfan` | `openai` | `custom`), keys, `chat_model`, `ocr_model`, **fallbacks** (lista separada por coma/salto de línea), instrucciones extra por agente. Gemini usa el endpoint OpenAI-compatible de Google AI Studio (`generativelanguage.googleapis.com/v1beta/openai/`).

---

## 4. Pipeline de análisis (LangGraph)

Archivo: `application/use_cases/analysis.py`.

```
START → ingest → (reader ∥ contradictions ∥ references) → classifier → END
```

- Semáforo `MAX_CONCURRENT_ANALYSES = 4`.
- `enqueue_analysis(id, skip_ingest=False)` crea `asyncio.Task`.
- Re-analizar usa `skip_ingest=True`: no reextrae el archivo; usa `content_text` ya editado.
- Cada nodo escribe `ProcessLog` y publica SSE (`agent_log`, `agent_done`, cambios de `status`).
- El grafo compilado se cachea en `get_graph()`. **Hay que reiniciar uvicorn** si cambias nodos/edges.

### Ingesta (`infrastructure/ingest.py`)

| Formato | Cómo |
|---|---|
| PDF nativo | PyMuPDF `get_text("dict")` → HTML (`h1–h3`, `p`, `li`, marcadores de página). Imágenes grandes: nota de figura + texto RapidOCR de ejes/leyenda si hay. `find_tables()` está **apagado** (`EXTRACT_PDF_TABLES = False`) por lentitud. |
| PDF escaneado | Si la página tiene &lt; 40 caracteres → pixmap + **RapidOCR local**. Si RapidOCR no saca texto y hay visión configurada, se usa como respaldo. |
| DOCX | mammoth → HTML |
| Imagen | RapidOCR local (visión solo si RapidOCR queda vacío) |

Los agentes no reciben el HTML: reciben `content_text` recortado (`truncate_doc`: cabeza 7k + centro 4k + cola 5k). Referencias usan `bibliography_slice` (intro + bloque de bibliografía).

### Agentes (`application/agents/`)

| Agente | LLM | Salida típica |
|---|---|---|
| `reader` | sí | resumen, estructura, 8–12 hallazgos `importante`/`alerta` |
| `contradictions` | sí | hasta 8 pares cita + `cita_secundaria` |
| `references` | sí + Crossref | hasta 12 refs, hasta 8 hallazgos; verifica DOI/título/año |
| `classifier` | no (sí si hay `classifier_instructions`) | `clasificacion`, `justificacion`, `recomendaciones`, `puntaje` |
| `chat` | sí | `respuesta` + `sugerencias[{original,sugerido,motivo}]` |

`call_agent_json` exige JSON. Si un modelo falla (vacío, timeout, 429, JSON roto), el agente reintenta ese modelo varias veces y luego recorre `chat_model_chain` (principal + respaldos configurados) **dos pasadas** antes de marcar error. El feed de proceso muestra cada cambio de modelo. La ingesta de escaneos usa RapidOCR; `ocr_model_chain` queda como respaldo de visión. Los tres agentes LLM no disparan más de 2 llamadas a la vez para no saturar el cupo `:free`.

Crossref (`infrastructure/crossref.py`): API pública, `mailto` en User-Agent, hasta 8 lookups en paralelo, 1 row por búsqueda. Sin key.

---

## 5. Catálogo de rutas

Base: `/api`. CORS: `localhost:3000` y `127.0.0.1:3000`.

Errores JSON FastAPI: `{ "detail": "..." }`. El frontend lee `detail` (`frontend/lib/api.ts`).

Códigos habituales: `400` validación / LLM no configurado / formato; `404` documento; `409` ya se está analizando; `502` chat/modelo; `500` genérico ofuscado.

### Salud

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | `{ "ok": true }` |

### Documentos — `api/routes/documents.py`

| Método | Ruta | Body | Respuesta | Caso de uso |
|---|---|---|---|---|
| POST | `/api/documents` | `multipart/form-data` campo `files` (varios) | `DocumentSummaryDTO[]` | `create_documents` → guarda archivo, `queued`, `enqueue_analysis` |
| GET | `/api/documents` | — | `DocumentSummaryDTO[]` | lista por `created_at` desc |
| GET | `/api/documents/{id}` | — | `DocumentDetailDTO` | detalle + findings + outputs + chat + logs |
| DELETE | `/api/documents/{id}` | — | `{ ok: true }` | borra fila y archivo en disco |
| PUT | `/api/documents/{id}/content` | `{ content_html }` | `FindingDTO[]` | autoguardado del editor; re-ancla citas |
| POST | `/api/documents/{id}/reanalyze` | — | `DocumentSummaryDTO` | `skip_ingest=True`; 409 si ya corre |
| POST | `/api/documents/{id}/decision` | `{ decision, comment? }` | `DocumentSummaryDTO` | `validated` \| `discarded` solo desde `awaiting_review` (o ya decidido) |
| POST | `/api/documents/{id}/chat` | `{ message }` | `{ reply, suggestions, message_id }` | persiste user+assistant |
| GET | `/api/documents/{id}/export?format=` | `md` \| `html` \| `docx` | archivo | HTML editado, no el original |

`DocumentSummaryDTO`: `id`, `filename`, `file_format`, `status`, `score`, `classification`, `error`, `ocr_used`, `created_at`, `updated_at`.

`DocumentDetailDTO` añade `content_html`, `decision_comment`, `findings`, `agent_outputs`, `chat_messages`, `process_logs`.

`agent_outputs[].output_json` es un **string JSON** (no objeto). El frontend hace `JSON.parse`.

### Settings — `api/routes/settings.py`

| Método | Ruta | Body | Respuesta |
|---|---|---|---|
| GET | `/api/settings` | — | `SettingsDTO` (incluye API keys en claro: app local) |
| PUT | `/api/settings` | `SettingsUpdateDTO` parcial | settings guardados |
| POST | `/api/settings/test` | `{ target: "chat" \| "ocr" }` | `{ ok, detail, data? }` |

El test guarda implícitamente desde el frontend **antes** de llamar (el cliente hace PUT y luego test). El backend testea lo ya persistido.

### Eventos SSE — `api/routes/events.py`

| Método | Ruta | Media |
|---|---|---|
| GET | `/api/events` | `text/event-stream` |

Broker **en memoria** (`infrastructure/events.py`). Un proceso uvicorn; no escala a varios workers.

Payload:

```json
{
  "type": "document",
  "document_id": "...",
  "status": "extracting | analyzing | awaiting_review | error | agent_log | agent_done | …"
}
```

Extras según evento:

- `agent_log`: `agent`, `message`, `log_id`, `created_at`
- `agent_done`: `agent`
- `awaiting_review`: `score`, `classification`
- `error`: `error` (mensaje público)

Keepalive cada 20s (`: keepalive`). Cola por suscriptor `maxsize=256`; si se llena, se descartan eventos.

El frontend:

- Biblioteca: recarga lista en eventos **excepto** `agent_log` (evitar spam).
- Workspace: `agent_log` append al diario; el resto hace refetch del documento.

---

## 6. LLM (`infrastructure/llm.py`)

Cliente `AsyncOpenAI` reutilizado por `(base_url, api_key)`. Timeout 90s, `max_retries=1`.

OpenRouter: `extra_body.provider.sort = throughput`. Gemini: `thinking_budget: 0`. Headers `HTTP-Referer` / `X-Title`.

Cadena de modelos: `[chat_model] + parse(chat_fallback_models)` sin duplicados. Igual OCR.

`chat_completion(..., model=None)` recorre la cadena. `call_agent_json` recorre la cadena **también** si el JSON no parsea.

Excepciones:

- `LLMNotConfigured` → 400, mensaje de configuración.
- `LLMEmptyResponse` / resto → mensaje público de lectura.

---

## 7. Frontend adyacente

| Ruta UI | API que usa |
|---|---|
| `/` biblioteca | GET/POST/DELETE documents, SSE |
| `/documents/[id]` | GET detail, PUT content (debounce), reanalyze, decision, chat, export, SSE |
| `/settings` | GET/PUT settings, POST test |

Editor TipTap (`components/Editor.tsx`): resaltados = **decoraciones ProseMirror**, no marcas en el HTML. Hover → `HighlightPopover`. Búsqueda de citas tolerante a espacios/puntuación (espejo de `find_quote` en dominio).

Cliente: `frontend/lib/api.ts`. `NEXT_PUBLIC_API_URL` opcional; default `http://localhost:3000` → backend 8000.

---

## 8. Cómo extender (guía para agentes)

**Nuevo endpoint:** DTO en `dtos.py` → función en `use_cases/` → ruta delgada en `api/routes/` que traduzca excepciones. Si el front lo consume, añadir wrapper en `lib/api.ts` y tipo en `lib/types.ts`.

**Nuevo agente en el grafo:** función `run_*` en `application/agents/`, nodo en `analysis.py`, edge (hoy fan-out desde `ingest` y join en `classifier`), persistir con `_save_agent_output`. Reiniciar uvicorn.

**Nueva columna SQLite:** campo en `entities.py` **y** entrada en `_NEW_COLUMNS` de `infrastructure/db.py` (si no, `create_all` no altera tablas existentes).

**No hacer:** meter SQL en routers; devolver stack traces al cliente; llamar LangGraph desde el frontend; añadir auth salvo que el producto deje de ser local; `find_tables()` de PyMuPDF sin medir (es lento).

---

## 9. Mejoras recomendadas (API y adyacentes)

Orden aproximado de impacto. No están hechas; son backlog consciente.

### API

1. **Ofuscar API keys en GET `/api/settings`.** Devolver `api_key_set: bool` y últimos 4 caracteres. El PUT seguiría aceptando la key completa. Hoy viajan en claro (aceptable en local, mal si se expone el puerto).
2. **Códigos de error estables.** `{ "code": "LLM_NOT_CONFIGURED" | "PIPELINE_BUSY" | "READ_FAILED", "detail": "…" }` para que el UI no haga regex sobre el texto (`/configur/i` en `UploadZone`).
3. **Idempotencia y jobs.** POST upload/reanalyze deberían devolver `202` + `job_id` (o el `document_id` + `status`) en lugar de parecer sincrónicos mientras el trabajo es background. Un `GET /api/documents/{id}/jobs` evitaría adivinar por SSE.
4. **Paginación y proyección.** `GET /api/documents` trae todo. Con muchos papers: `?limit=&cursor=` y un summary sin `error` largo. `GET /{id}` es pesado (HTML + logs + chat); split `GET /{id}/content` vs `GET /{id}/analysis`.
5. **Validación Pydantic estricta.** `file_format`, `status`, `decision`, `kind` como `Literal`/enums. `export format` como enum, no string libre.
6. **Rate limit y tamaño de upload.** Límite de MB y de archivos por POST. OpenRouter free = 50 req/día: un paper dispara 3 llamadas LLM (+ OCR). Superficie para 429 amigable.
7. **SSE por documento o filtro.** Hoy todos los clientes reciben todos los eventos. `GET /api/events?document_id=` reduce ruido. Alternativa: WebSocket.
8. **Health más útil.** `/api/health` podría reportar DB writable, settings configurados (sin key), versión. Útil para el front al arrancar.
9. **No filtrar API keys en logs.** Revisar que `logger` no imprima bodies de OpenRouter.
10. **CORS configurable.** Lista en settings/env para no hardcodear 3000.

### Persistencia y runtime

11. **Alembic** (o al menos un registro de migraciones) en lugar de `ALTER` ad-hoc.
12. **SSE + análisis no sobreviven a varios workers.** Un process único está bien en local. Si se despliega: Redis pub/sub o Postgres LISTEN, y cola (ARQ/Celery) en vez de `asyncio.Task` en el proceso web.
13. **Sesiones SQLAlchemy en el pipeline.** Cada nodo abre `SessionLocal()` corto. Correcto para no dejar conexiones, pero hay race al escribir el mismo doc. Un lock por `document_id` (asyncio) evitaría commits cruzados.
14. **Borrar `agent_outputs` viejos** en re-análisis (hoy se **añaden** filas; el front toma la última por `agent` al parsear en orden). Deduplicar o reemplazar.
15. **Archivos huérfanos** si falla el commit tras escribir el upload.

### Pipeline / LLM

16. **Timeout por nodo** y circuit breaker (si OpenRouter cae, no esperar 90s × 3 agentes × N fallbacks).
17. **Structured outputs** (`response_format: json_object`) donde el proveedor lo soporte, para menos `extract_json` frágil.
18. **Reanudar grafo** (checkpoint LangGraph) si se reinicia el server a mitad de análisis, en vez de marcar `error`.
19. **Clasificador:** documentar en UI que es local; si hay instrucciones custom, avisar que añade latencia.
20. **Crossref:** cache por DOI/texto; backoff 429; no penalizar `verificada: None` (API caída) igual que `False`.

### Frontend acoplado a la API

21. **Autoguardado:** PUT content en cada debounce; no hay ETag/versión → last-write-wins si dos pestañas. Añadir `updated_at` if-match.
22. **Chat:** el historial se reenvía al modelo truncado; no hay endpoint de listado paginado (viaja en el detail).
23. **Export:** GET con query; mejor POST o `Content-Disposition` ya está. Añadir PDF export si se necesita.
24. **Tipos generados** desde OpenAPI (`openapi-typescript`) para no desincronizar `lib/types.ts` y `dtos.py`.

### Seguridad (aunque sea app personal)

25. Path traversal en `file_path` al borrar: hoy se guarda path absoluto generado; no aceptar paths del cliente.
26. HTML del editor es HTML libre en TipTap → XSS almacenado si algún día se sirve a otro origen. Sanitizar al guardar (`bleach` / DOMPurify en el cliente).
27. Bind de uvicorn a `127.0.0.1` (ya es el default) para no exponer keys en la LAN.

---

## 10. Mapa rápido de archivos

```
backend/app/
  main.py                          # app FastAPI
  config.py                        # constantes
  domain/entities.py               # tablas
  domain/services.py               # anclaje + puntaje
  application/dtos.py              # contrato HTTP
  application/agents/*.py          # prompts + parseo JSON
  application/use_cases/analysis.py
  application/use_cases/documents.py
  application/use_cases/chat.py
  application/use_cases/settings.py
  infrastructure/db.py             # engine + columnas nuevas
  infrastructure/llm.py            # OpenAI-compatible + fallbacks
  infrastructure/ingest.py         # PDF/DOCX/imagen → HTML
  infrastructure/rapid_ocr.py      # RapidOCR local (escaneos + figuras)
  infrastructure/crossref.py
  infrastructure/events.py         # SSE in-memory
  api/routes/documents.py
  api/routes/settings.py
  api/routes/events.py
frontend/lib/api.ts                # único cliente HTTP
frontend/lib/useDocumentEvents.ts  # EventSource
frontend/components/Editor.tsx     # TipTap + highlights
```

Stack backend (`requirements.txt`): FastAPI, Uvicorn, SQLAlchemy, Pydantic v2, LangGraph, OpenAI SDK, httpx, PyMuPDF, mammoth, BeautifulSoup, python-docx, markdownify, RapidOCR.
