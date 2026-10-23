import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from smartseed_vision.app import create_app
from synth import make_tray_image


class StubDetector:
    device = "stub"

    def __init__(self, result):
        self.result = result
        self.loaded = True
        self.calls = 0

    def detect(self, image_bgr):
        self.calls += 1
        return self.result


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
    assert body == {"status": "ok", "model_loaded": True, "device": "stub"}


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
