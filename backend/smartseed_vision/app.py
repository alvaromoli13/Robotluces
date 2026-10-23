import os
import time

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .geometry import analyze_tray


def default_detector():
    if os.environ.get("SMARTSEED_DISABLE_MODEL") == "1":
        return None
    from .detector import Owlv2Detector

    return Owlv2Detector()


def create_app(detector="default"):
    """`detector` needs `.detect(bgr) -> (bbox, score) | None`, `.loaded`, `.device`; None disables the model."""
    if detector == "default":
        detector = default_detector()
    app = FastAPI(title="SmartSeed vision")
    # allow_private_network answers Chrome's preflight for https pages calling localhost
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_private_network=True
    )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model_loaded": bool(detector and detector.loaded),
            "device": detector.device if detector else "none",
        }

    @app.post("/vision/tray")
    def tray(image: UploadFile = File(...)):
        start = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(image.file.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "image could not be decoded")
        h, w = img.shape[:2]
        detection = detector.detect(img) if detector else None
        bbox, score = detection if detection else (None, None)
        geometry = analyze_tray(img, bbox)
        if geometry is None and bbox is not None:  # bbox too tight or wrong: retry on the whole frame
            geometry, bbox, score = analyze_tray(img), None, None
        corners_px = geometry.corners_px if geometry else None
        return {
            "found": geometry is not None,
            "corners": [[x / w, y / h] for x, y in corners_px] if geometry else None,
            "corners_px": corners_px,
            "rows": geometry.rows if geometry else None,
            "cols": geometry.cols if geometry else None,
            "confidence": geometry.confidence if geometry else 0.0,
            "detector_score": score,
            "source": "owlv2" if bbox is not None else "contour",
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "image_size": [w, h],
        }

    return app


def __getattr__(name):
    # `uvicorn smartseed_vision.app:app` builds the default app lazily
    if name == "app":
        return create_app()
    raise AttributeError(name)
