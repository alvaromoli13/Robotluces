import threading
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from smartseed_vision.app import create_app
from synth import make_box_depth, make_tray_image


class StubDetector:
    device = "stub"

    def __init__(self, result):
        self.result = result
        self.loaded = True
        self.calls = 0

    def detect(self, image_bgr):
        self.calls += 1
        return self.result


class StubDepth:
    device = "stub"
    loaded = True

    def __init__(self, depth):
        self.depth = depth

    def estimate(self, image_bgr):
        return self.depth


def png(img):
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def post(client, img):
    return client.post("/vision/tray", files={"image": ("frame.png", png(img), "image/png")})


@pytest.fixture
def tray():
    return make_tray_image(5, 8, 10.0)


def test_health_reports_model_state():
    body = TestClient(create_app(StubDetector(None))).get("/health").json()
    assert body == {"status": "ok", "model_loaded": True, "device": "stub",
                    "depth_loaded": False, "depth_device": "none"}


def test_health_without_model():
    body = TestClient(create_app(None)).get("/health").json()
    assert body["status"] == "ok" and body["model_loaded"] is False


def test_tray_uses_detector_bbox(tray):
    img, true = tray
    stub = StubDetector(((60, 20, 580, 460), 0.42))
    body = post(TestClient(create_app(stub)), img).json()
    assert stub.calls == 1
    assert body["found"] is True and body["source"] == "owlv2"
    assert (body["rows"], body["cols"]) == (5, 8)
    assert body["detector_score"] == pytest.approx(0.42)
    assert body["image_size"] == [640, 480]
    assert np.abs(np.array(body["corners_px"]) - true).max() < 5
    assert np.allclose(np.array(body["corners"]) * [640, 480], body["corners_px"], atol=0.01)
    assert 0 <= body["confidence"] <= 1 and body["elapsed_ms"] >= 0


def test_tray_falls_back_to_contour_when_detector_finds_nothing(tray):
    img, _ = tray
    body = post(TestClient(create_app(StubDetector(None))), img).json()
    assert body["found"] is True and body["source"] == "contour"
    assert body["detector_score"] is None and (body["rows"], body["cols"]) == (5, 8)


def test_tray_contour_only_when_model_disabled(tray):
    img, _ = tray
    body = post(TestClient(create_app(None)), img).json()
    assert body["source"] == "contour" and body["found"] is True


def test_tray_not_found_on_blank_frame():
    body = post(TestClient(create_app(None)), np.full((480, 640, 3), 200, np.uint8)).json()
    assert body["found"] is False and body["image_size"] == [640, 480]
    assert body["corners"] is None


def test_invalid_image_is_rejected():
    r = TestClient(create_app(None)).post("/vision/tray", files={"image": ("x.png", b"nope", "image/png")})
    assert r.status_code == 400


def test_cors_allows_any_origin():
    r = TestClient(create_app(None)).get("/health", headers={"Origin": "https://alvaromoli13.github.io"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_private_network_preflight_is_answered():
    r = TestClient(create_app(None)).options(
        "/vision/tray",
        headers={
            "Origin": "https://alvaromoli13.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-private-network"] == "true"


def test_contour_fallback_rejects_dark_blob_without_a_cell_pattern():
    img = np.full((480, 640, 3), 200, np.uint8)
    cv2.rectangle(img, (60, 40), (560, 440), (30, 30, 30), -1)
    assert post(TestClient(create_app(None)), img).json()["found"] is False


def test_normalized_corners_are_clamped_to_the_frame():
    img, _ = make_tray_image(4, 6, 10.0, center=(600, 240))  # tray overhangs the right edge
    corners = post(TestClient(create_app(None)), img).json()["corners"]
    assert all(0 <= v <= 1 for p in corners for v in p)


def test_holes_come_from_the_depth_map():
    depth, centers = make_box_depth(1, 2)
    img = np.full((480, 640, 3), 200, np.uint8)  # no tray in the colour image at all
    body = post(TestClient(create_app(None, depth=StubDepth(depth))), img).json()
    assert [(h["row"], h["col"]) for h in body["holes"]] == [(0, 0), (0, 1)]
    got = np.array([[h["x"], h["y"]] for h in body["holes"]])
    assert np.abs(got - np.array(centers)).max() < 0.06
    assert all(set(h) == {"x", "y", "area", "depth", "row", "col"} for h in body["holes"])


def test_no_holes_without_depth_model(tray):
    img, _ = tray
    assert post(TestClient(create_app(None)), img).json()["holes"] == []


def test_health_reports_depth_model():
    body = TestClient(create_app(None, depth=StubDepth(None))).get("/health").json()
    assert body["depth_loaded"] is True and body["depth_device"] == "stub"


class OverlapProbe:
    """Detector and depth stubs sharing one counter, to catch two models on the GPU at once."""

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def run(self, result):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.guard:
            self.active -= 1
        return result


def test_models_never_run_concurrently_across_requests(tray):
    img, _ = tray
    probe = OverlapProbe()
    detector = StubDetector(None)
    detector.detect = lambda image: probe.run(None)
    depth = StubDepth(None)
    depth.estimate = lambda image: probe.run(None)
    client = TestClient(create_app(detector, depth=depth))
    threads = [threading.Thread(target=post, args=(client, img)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert probe.max_active == 1
