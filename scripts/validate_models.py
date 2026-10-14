"""Evaluate predictions against author labels; labels are never read by the app worker."""

from pathlib import Path
from datetime import datetime
import json
import time
import cv2

from backend.detectors import detector
from backend.analytics import metrics

ROOT = Path(__file__).resolve().parents[1]


def run():
    manifest = json.loads(
        (ROOT / "data/demo/manifest.json").read_text(encoding="utf-8")
    )
    slots = manifest["slots"]
    reference = json.loads(
        (ROOT / "examples/reference-labels.json").read_text(encoding="utf-8")
    )
    test_date = "2016-02-12"
    test_folder = ROOT / "examples/validation"

    def evaluate(model, paths, confidence):
        truth, predicted, probabilities = [], [], []
        started = time.monotonic()
        for path in paths:
            capture = datetime.strptime(path.stem, "%Y-%m-%d_%H%M").strftime(
                "%Y-%m-%d_%H.%M"
            )
            labels = reference.get(capture, {})
            subset = [s for s in slots if s["id"] in labels]
            if not subset:
                continue
            states, probs, _ = model.predict(cv2.imread(str(path)), subset, confidence)
            truth.extend(labels[s["id"]] for s in subset)
            predicted.extend(states)
            probabilities.extend(probs)
        return (
            {
                "report": metrics(truth, predicted),
                "seconds": round(time.monotonic() - started, 3),
            },
            truth,
            probabilities,
        )

    validation_paths = sorted((ROOT / "data/demo/frames").glob("*.jpg"))
    test_paths = sorted(test_folder.glob("*.jpg"))
    classifier = detector("malexnet")
    base, actual, probabilities = evaluate(classifier, validation_paths, 0.5)
    thresholds = []
    for threshold in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]:
        states = [
            1 if p >= threshold else 0 if p <= 1 - threshold else -1
            for p in probabilities
        ]
        thresholds.append({"threshold": threshold, **metrics(actual, states)})
    eligible = [r for r in thresholds if r["coverage"] >= 0.95 and r["f1"] >= 0.98]
    chosen = max((r["threshold"] for r in eligible), default=0.65)
    validation_result, _, _ = evaluate(classifier, validation_paths, chosen)
    test_result, _, _ = evaluate(classifier, test_paths, chosen)
    output = {
        "selected_model": "malexnet",
        "confidence": chosen,
        "validation_date": "2015-11-16",
        "test_date": test_date,
        "training_source": "Public mAlexNet weights trained on CNRPark A/B (July 2015), checkpoint selected by authors on CNR-EXT validation. No local training.",
        "evaluation_note": "Test day reserved before threshold selection in this script. Same CNR-EXT camera; not a cross-camera generalization claim. Unknown positive labels count as false negatives in recall. Metrics concern sampled states, not precise arrivals.",
        "source_url": "http://cnrpark.it/",
        "model_sha256": classifier.sha256,
        "threshold_selection": thresholds,
        "validation": validation_result["report"],
        "validation_seconds": validation_result["seconds"],
        "test": test_result["report"],
        "test_seconds": test_result["seconds"],
        "comparisons": {},
    }
    print(
        "CLASSIFIER",
        json.dumps({k: output[k] for k in ["confidence", "validation", "test"]}),
        flush=True,
    )
    for name in ["yolo11n", "yolo11s"]:
        model = detector(name)
        report, _, _ = evaluate(model, validation_paths, 0.25)
        output["comparisons"][name] = {
            "confidence": 0.25,
            "imgsz": 960,
            "model_sha256": model.sha256,
            **report,
        }
        print(name, json.dumps(report), flush=True)
    (ROOT / "docs/validation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    run()
