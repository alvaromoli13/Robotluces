"""Open-vocabulary tray detection with OWLv2 (runs fully offline once the weights are cached)."""
import threading

import cv2
import numpy as np

MODEL_ID = "google/owlv2-base-patch16-ensemble"
QUERIES = ["a black plastic seed tray", "a plant cell tray", "a seedling tray with cells"]
MIN_SCORE = 0.05


def best_box(boxes, scores, image_size):
    """Highest-scoring (box, score) with the box clipped to the (w, h) image, or None."""
    if len(scores) == 0:
        return None
    i = int(np.argmax(scores))
    w, h = image_size
    x0, y0, x1, y1 = np.clip(np.asarray(boxes[i], float), 0, [w, h, w, h])
    return (float(x0), float(y0), float(x1), float(y1)), float(scores[i])


class Owlv2Detector:
    """Lazy-loads the model on first use; `detect` takes a BGR frame."""

    def __init__(self, model_id=MODEL_ID, queries=QUERIES):
        self.model_id, self.queries = model_id, queries
        self.loaded = False
        self.device = "unloaded"
        self._lock = threading.Lock()

    def load(self):
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self._torch = torch
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._processor = Owlv2Processor.from_pretrained(self.model_id)
        self._model = Owlv2ForObjectDetection.from_pretrained(self.model_id).to(self.device).eval()
        self.loaded = True

    def detect(self, image_bgr):
        from PIL import Image

        with self._lock:
            if not self.loaded:
                self.load()
            h, w = image_bgr.shape[:2]
            image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
            inputs = self._processor(text=[self.queries], images=image, return_tensors="pt").to(self.device)
            with self._torch.no_grad():
                outputs = self._model(**inputs)
            # OWLv2 pads the frame to a square (bottom/right), so boxes are relative to that square
            side = max(w, h)
            result = self._processor.post_process_grounded_object_detection(
                outputs, threshold=MIN_SCORE, target_sizes=[(side, side)]
            )[0]
            return best_box(result["boxes"].cpu().numpy(), result["scores"].cpu().numpy(), (w, h))
