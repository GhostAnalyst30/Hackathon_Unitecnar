# GhostAnalyst — Analizador personal de papers

Herramienta personal para revisar papers con un pipeline de agentes de IA:
subes tu documento (**PDF, DOCX o imagen**), los agentes lo leen, buscan
contradicciones, revisan las referencias bibliográficas y lo clasifican con un
**puntaje de validación (0-100)**. El resultado se abre en un **editor** con los
hallazgos resaltados por color y un **chatbot** que propone correcciones que tú
aplicas con un clic. **El humano siempre tiene la última palabra**: nada se
aplica ni se valida sin tu decisión.

## Arquitectura

```
ingesta (texto nativo u OCR)
   └─> agente lector
          ├─> agente de contradicciones                ┐ (en paralelo)
          └─> agente de referencias + Crossref API     ┘
                 └─> agente clasificador (puntaje + clasificación)
                        └─> revisión humana (editor + chat + validar/descartar)
```

- **Backend**: FastAPI + LangGraph + SQLAlchemy (SQLite) + PyMuPDF + mammoth,
  organizado en **clean architecture simplificada con DTOs**:
  - `domain/` — entidades y reglas puras (anclaje de citas, fórmula del puntaje).
  - `application/` — DTOs, agentes de IA y casos de uso (pipeline, documentos, chat).
  - `infrastructure/` — SQLAlchemy, clientes LLM/OCR, **Crossref REST API**, SSE.
  - `api/` — routers FastAPI delgados que solo traducen DTOs y errores.

  Cola asyncio con hasta 3 documentos analizándose en paralelo y progreso en
  vivo por SSE.
- **Verificación de fuentes**: el agente de referencias consulta la
  [Crossref REST API](https://api.crossref.org) (pública, sin key) por cada
  referencia extraída: busca por DOI o por texto bibliográfico, compara el
  título y el año, y marca cada fuente como *verificada* (con enlace DOI) o
  *no encontrada* (lo que genera una alerta y penaliza el puntaje).
- **Frontend**: Next.js + Tailwind + TipTap (editor con resaltados por
  decoraciones, no destruye el contenido al editar).
- **Modelos**: **OpenRouter** con Gemini 2.5 Flash-Lite / GPT-4o mini (baratos, de pago) o **Google Gemini** nativo ([AI Studio](https://aistudio.google.com/apikey)). También Qianfan u OpenAI.

## Requisitos

- Python 3.11+ (probado con 3.13)
- Node.js 20+
- Una API key (gratis) de [Google AI Studio](https://aistudio.google.com/apikey)
  (Gemini) o de [OpenRouter](https://openrouter.ai/keys) — o de Qianfan / OpenAI

## Puesta en marcha

### 1. Backend (puerto 8000)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

### 2. Frontend (puerto 3000)

```powershell
cd frontend
npm install
npm run dev
```

Abre http://localhost:3000.

### 3. Configurar las API keys

Ve a **Configuración**:

1. Elige **Google Gemini (API gratis)** y pega una key `AIza…` de
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey). El preset
   por defecto es Gemini 2.5 Flash (visión) para agentes y OCR.
2. O usa **OpenRouter** con Gemini 2.5 Flash-Lite / GPT-4o mini (baratos, de
   pago) y una key `sk-or-…` de [openrouter.ai/keys](https://openrouter.ai/keys).
   Hace falta un poco de crédito; los `:free` se acaban a las 50 peticiones/día.
3. Usa **Probar conexión** para validar cada servicio antes de guardar.
4. (Opcional) Personaliza las instrucciones de cada agente y del chatbot.

Sin API key configurada, la app bloquea los análisis y te lo indica.

## Uso

1. **Biblioteca**: arrastra uno o varios archivos. Verás el estado en vivo
   (extrayendo texto → agentes analizando → esperando tu revisión).
2. **Espacio de trabajo**: al abrir un documento tienes tres zonas:
   - *Izquierda*: salida de cada agente, puntaje de validación, hallazgos
     (clic para saltar al fragmento) y los botones **Validar / Descartar**.
   - *Centro*: el editor con el texto y los resaltados
     (azul = importante, ámbar = alerta, rojo = contradicción,
     naranja = inconsistencia, violeta = referencia). Puedes editar
     directamente; se autoguarda y los resaltados se recalculan.
   - *Derecha*: el chatbot. Cuando propone una corrección aparece una tarjeta
     con el diff y el botón **Aplicar**; nada cambia sin tu clic.
3. **Re-analizar**: tras editar, vuelve a ejecutar el pipeline sobre el texto
   actualizado para recalcular puntaje y hallazgos.
4. **Exportar**: descarga el documento editado como Word, Markdown o HTML.

## Estructura del proyecto

```
backend/
  app/
    domain/
      entities.py      # entidades (Document, Finding, AppSettings…)
      services.py      # reglas puras: anclaje de citas, puntaje de validación
    application/
      dtos.py          # DTOs de entrada/salida de la API
      agents/          # lector, contradicciones, referencias, clasificador, chat
      use_cases/       # analysis (pipeline LangGraph), documents, chat, settings
    infrastructure/
      db.py            # SQLAlchemy + SQLite
      llm.py           # clientes OpenAI-compatibles (Gemini/OpenRouter/Qianfan/OpenAI)
      ingest.py        # PDF / DOCX / imagen -> HTML editable (OCR si hace falta)
      crossref.py      # verificación de referencias en la Crossref REST API
      events.py        # broker SSE
    api/routes/        # routers delgados (documentos, settings, eventos)
    main.py            # composition root
  data/                # SQLite + archivos subidos (se crea sola)
frontend/
  app/                 # biblioteca, espacio de trabajo, configuración
  components/          # editor TipTap, paneles de análisis y chat
```
