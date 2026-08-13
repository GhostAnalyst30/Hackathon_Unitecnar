"""Composition root: crea la app FastAPI y conecta las capas."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import documents, events, settings
from .application.use_cases.analysis import recover_interrupted_documents
from .infrastructure.db import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_interrupted_documents()
    yield


app = FastAPI(title="Analizador personal de papers", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(settings.router)
app.include_router(events.router)


@app.get("/api/health")
def health():
    return {"ok": True}
