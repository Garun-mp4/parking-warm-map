import hashlib
import cv2
import numpy as np
import requests
from .config import MODELS


def crop(frame, points):
    h, w = frame.shape[:2]
    a = np.asarray(points)
    x1, y1 = np.floor(a.min(axis=0) * [w, h]).astype(int)
    x2, y2 = np.ceil(a.max(axis=0) * [w, h]).astype(int)
    return frame[max(0, y1) : min(h, y2), max(0, x1) : min(w, x2)]


class ParkingClassifier:
    name = "mAlexNet · CNRParkAB → CNR-EXT"

    def __init__(self):
        definition = MODELS / "deploy.prototxt"
        weights = MODELS / "snapshot_iter_870.caffemodel"
        if not definition.exists() or not weights.exists():
            raise FileNotFoundError(
                "Не найдены веса mAlexNet. Выполните scripts/prepare_demo.py."
            )
        self.net = cv2.dnn.readNetFromCaffe(str(definition), str(weights))
        self.sha256 = hashlib.sha256(weights.read_bytes()).hexdigest()

    def predict(self, frame, slots, confidence):
        # Author's Caffe ImageData: BGR, resize 256, center crop 224, scale 1/256, no mean subtraction.
        inputs = []
        for slot in slots:
            region = crop(frame, slot["points"])
            if region.size == 0:
                raise ValueError("Место оказалось вне изображения")
            region = cv2.resize(region, (150, 150))
            region = cv2.resize(region, (256, 256))[16:240, 16:240]
            inputs.append(region)
        self.net.setInput(
            cv2.dnn.blobFromImages(
                inputs, 1 / 256, (224, 224), swapRB=False, crop=False
            )
        )
        scores = self.net.forward().reshape(len(slots), 2)
        probabilities = scores[:, 1].tolist()
        states = [
            1 if p >= confidence else 0 if p <= 1 - confidence else -1
            for p in probabilities
        ]
        return states, probabilities, []


class YoloDetector:
    def __init__(self, name):
        from ultralytics import YOLO

        path = MODELS / (name + ".pt")
        if not path.exists():
            response = requests.get(
                f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{name}.pt",
                timeout=120,
            )
            response.raise_for_status()
            temporary = path.with_suffix(".part")
            temporary.write_bytes(response.content)
            temporary.replace(path)
        self.model = YOLO(str(MODELS / (name + ".pt")))
        self.name = name
        self.sha256 = hashlib.sha256((MODELS / (name + ".pt")).read_bytes()).hexdigest()

    def predict(self, frame, slots, confidence):
        h, w = frame.shape[:2]
        output = self.model.predict(
            frame,
            classes=[2, 3, 5, 7],
            conf=confidence,
            imgsz=960,
            device="cpu",
            verbose=False,
        )[0]
        boxes = [
            {
                "xyxy": (box.xyxy[0].cpu().numpy() / [w, h, w, h]).tolist(),
                "confidence": float(box.conf[0]),
                "class": int(box.cls[0]),
            }
            for box in output.boxes
        ]
        probabilities = [0.0] * len(slots)
        ambiguous = set()
        for box in boxes:
            x1, y1, x2, y2 = box["xyxy"]
            rectangle = np.array(
                [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32
            )
            candidates = []
            for i, slot in enumerate(slots):
                polygon = np.array(slot["points"], dtype=np.float32)
                intersection, _ = cv2.intersectConvexConvex(polygon, rectangle)
                area = cv2.contourArea(polygon)
                score = float(intersection / area) if area else 0
                if score >= 0.35:
                    candidates.append((score, i))
            candidates.sort(reverse=True)
            if candidates:
                score, best = candidates[0]
                if len(candidates) > 1 and candidates[1][0] > score * 0.85:
                    ambiguous.update([best, candidates[1][1]])
                else:
                    probabilities[best] = max(probabilities[best], box["confidence"])
        # A validated clear ROI without matching detections is a baseline free estimate, not a proof of absence.
        states = [
            -1 if i in ambiguous else 1 if p >= confidence else 0
            for i, p in enumerate(probabilities)
        ]
        return states, probabilities, boxes


def detector(name):
    return ParkingClassifier() if name == "malexnet" else YoloDetector(name)
