"""Composition root: crea la app FastAPI y conecta las capas."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import documents, events, settings
from .application.use_cases.analysis import recover_interrupted_documents
from .config import FRONTEND_ORIGINS, IS_VERCEL
from .infrastructure.db import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # En Vercel cada instancia nueva no debe marcar como error los análisis
    # que siguen corriendo en otra invocación (Fluid Compute).
    if not IS_VERCEL:
        recover_interrupted_documents()
    yield


app = FastAPI(title="Analizador personal de papers", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "Content-Disposition"],
)

app.include_router(documents.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/api/health")
def health():
    return {"ok": True}
