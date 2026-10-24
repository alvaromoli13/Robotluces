import os
import threading
import time

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .depth import find_holes, grid_in_tray
from .occupancy import mark_occupied
from .geometry import analyze_tray

# One model at a time on the GPU: two threads driving MPS at once abort the whole process
# ("failed assertion _status < MTLCommandBufferStatusCommitted").
GPU_LOCK = threading.Lock()
MIN_CONTOUR_CONFIDENCE = 0.35  # without a detector hit, require a clear cell pattern
MIN_CONTOUR_HOLES = 2  # ...and, when depth is available, at least this many pits inside it


def default_detector():
    if os.environ.get("SMARTSEED_DISABLE_MODEL") == "1":
        return None
    from .detector import Owlv2Detector

    return Owlv2Detector()


def default_depth():
    if os.environ.get("SMARTSEED_DISABLE_MODEL") == "1":
        return None
    from .depth import DepthEstimator

    return DepthEstimator()


def create_app(detector="default", depth="default", robot="default"):
    """`detector` needs `.detect(bgr) -> (bbox, score) | None`, `.loaded`, `.device`; None disables the model.

    `depth` needs `.estimate(bgr) -> relative depth map`, `.loaded`, `.device`. By default it is
    only loaded together with the default detector, so a test passing a detector gets no depth.

    `robot` is a `smartseed_robot.api.Runtime`; by default it is built from SMARTSEED_ROBOT (fake unless
    `real`). None leaves the robot endpoints off.
    """
    if depth == "default":
        depth = default_depth() if detector == "default" else None
    if detector == "default":
        detector = default_detector()
    app = FastAPI(title="SmartSeed vision")
    # allow_private_network answers Chrome's preflight for https pages calling localhost
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_private_network=True
    )

    if robot == "default":
        from smartseed_robot.api import build_runtime

        robot = build_runtime()
    if robot is not None:
        from smartseed_robot.api import create_router

        app.state.robot_runtime = robot
        app.include_router(create_router(robot))

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model_loaded": bool(detector and detector.loaded),
            "device": detector.device if detector else "none",
            "depth_loaded": bool(depth and depth.loaded),
            "depth_device": depth.device if depth else "none",
        }

    @app.post("/vision/tray")
    def tray(image: UploadFile = File(...)):
        start = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(image.file.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "image could not be decoded")
        h, w = img.shape[:2]
        with GPU_LOCK:
            detection = detector.detect(img) if detector else None
        bbox, score = detection if detection else (None, None)
        geometry = analyze_tray(img, bbox)
        if geometry is None and bbox is not None:  # bbox too tight or wrong: retry on the whole frame
            geometry, bbox, score = analyze_tray(img), None, None
        if geometry and bbox is None and geometry.confidence < MIN_CONTOUR_CONFIDENCE:
            geometry = None
        corners_px = geometry.corners_px if geometry else None
        with GPU_LOCK:
            depth_map = depth.estimate(img) if depth else None
        corners = [[min(max(x / w, 0), 1), min(max(y / h, 0), 1)] for x, y in corners_px] if geometry else None
        holes = find_holes(depth_map, tray=corners) if depth_map is not None else []
        if geometry and bbox is None and depth_map is not None and len(holes) < MIN_CONTOUR_HOLES:
            # contours alone also match printed text or tiles; a real tray has pits in the depth map
            geometry = corners = None
            holes = find_holes(depth_map)
        if holes and geometry:
            holes = grid_in_tray(holes, corners, geometry.rows, geometry.cols) or holes
        holes = mark_occupied(img, holes, corners)
        return {
            "found": geometry is not None,
            "corners": corners,
            "corners_px": corners_px,
            "rows": geometry.rows if geometry else None,
            "cols": geometry.cols if geometry else None,
            "confidence": geometry.confidence if geometry else 0.0,
            "detector_score": score,
            "source": "owlv2" if bbox is not None else "contour",
            "holes": [{k: bool(v) if k == "occupied" else float(v) if k in ("x", "y", "area", "depth", "fill_score")
                       else int(v) for k, v in h.items()} for h in holes],
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "image_size": [w, h],
        }

    return app


def __getattr__(name):
    # `uvicorn smartseed_vision.app:app` builds the default app lazily
    if name == "app":
        return create_app()
    raise AttributeError(name)
