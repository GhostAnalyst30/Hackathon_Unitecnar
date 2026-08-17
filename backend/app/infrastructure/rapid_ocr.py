"""OCR local con RapidOCR (ONNX, CPU). Compartido por ingesta y cajas del visor."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_OCR_LOCK = threading.Lock()
_OCR_ENGINE = None


def ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def pixmap_to_numpy(pix: Any):
    import numpy as np

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        return img[:, :, :3].copy()
    if pix.n == 1:
        return np.repeat(img, 3, axis=2)
    return img


def run_ocr(img) -> list[dict]:
    """Devuelve [{text, x0, y0, x1, y1}] en píxeles de la imagen."""
    with _OCR_LOCK:
        try:
            result, _elapsed = ocr_engine()(img)
        except Exception:  # noqa: BLE001
            logger.exception("RapidOCR falló")
            return []
    out: list[dict] = []
    for item in result or []:
        if not item or len(item) < 2:
            continue
        quad, text = item[0], item[1]
        if not text or not str(text).strip():
            continue
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        out.append(
            {
                "text": str(text).strip(),
                "x0": min(xs),
                "y0": min(ys),
                "x1": max(xs),
                "y1": max(ys),
            }
        )
    return out
