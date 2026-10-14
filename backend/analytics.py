import numpy as np


def interval_weights(samples, duration):
    """Left-held sampled states, clipped to source duration; last point adds no invented time."""
    times = [float(s["source_seconds"]) for s in samples]
    return [
        max(0.0, min(times[i + 1] if i + 1 < len(times) else duration, duration) - t)
        for i, t in enumerate(times)
    ]


def summary(result, start=0.0, end=None):
    samples, slots = result["samples"], result["slots"]
    duration = result["source_duration_seconds"]
    end = duration if end is None else min(end, duration)
    start = max(0.0, start)
    if end <= start:
        raise ValueError("Конец интервала должен быть позже начала")
    records, timeline = [], []
    weights = []
    for i, sample in enumerate(samples):
        next_time = (
            samples[i + 1]["source_seconds"] if i + 1 < len(samples) else duration
        )
        weight = max(0.0, min(next_time, end) - max(sample["source_seconds"], start))
        weights.append(weight)
        if weight > 0 or start <= sample["source_seconds"] <= end:
            states = sample["states"]
            timeline.append(
                {
                    "time": max(sample["source_seconds"], start),
                    "video_seconds": sample["video_seconds"],
                    "occupied": states.count(1),
                    "free": states.count(0),
                    "unknown": states.count(-1),
                }
            )
    if timeline and timeline[-1]["time"] < end:
        timeline.append({**timeline[-1], "time": end})
    for col, slot in enumerate(slots):
        busy = sum(w for w, s in zip(weights, samples) if s["states"][col] == 1)
        free = sum(w for w, s in zip(weights, samples) if s["states"][col] == 0)
        valid = busy + free
        active = [s["states"][col] for s, w in zip(samples, weights) if w > 0]
        changes = sum(
            a != b and a != -1 and b != -1 for a, b in zip(active, active[1:])
        )
        records.append(
            {
                **slot,
                "occupied_seconds": round(busy, 2),
                "free_seconds": round(free, 2),
                "unknown_seconds": round(end - start - valid, 2),
                "occupancy": round(busy / valid * 100, 2) if valid else None,
                "coverage": round(valid / (end - start) * 100, 2),
                "changes": changes,
            }
        )
    known_space_seconds = sum(
        r["occupied_seconds"] + r["free_seconds"] for r in records
    )
    return {
        "start": start,
        "end": end,
        "duration": end - start,
        "slots": records,
        "timeline": timeline,
        "occupancy": round(
            sum(r["occupied_seconds"] for r in records) / known_space_seconds * 100, 2
        )
        if known_space_seconds
        else None,
        "coverage": round(known_space_seconds / ((end - start) * len(slots)) * 100, 2)
        if slots
        else 0,
        "peak_occupied": max((r["occupied"] for r in timeline), default=0),
        "changes": sum(r["changes"] for r in records),
    }


class Stabilizer:
    def __init__(self, count, confirm):
        self.states = [-1] * count
        self.pending = [-1] * count
        self.since = [0.0] * count
        self.confirm = confirm

    def step(self, raw, timestamp):
        output = self.states.copy()
        for i, value in enumerate(raw):
            if value == -1:
                output[i] = -1
                self.pending[i] = -1
                self.since[i] = timestamp
                continue
            if self.states[i] == -1:
                self.states[i] = value
            if self.pending[i] != value:
                self.pending[i] = value
                self.since[i] = timestamp
            if timestamp - self.since[i] >= self.confirm:
                self.states[i] = value
            output[i] = self.states[i]
        return output


def heat_color(percent):
    if percent is None:
        return (230, 230, 230)
    palette = [
        (255, 255, 255),
        (244, 176, 197),
        (61, 29, 31),
    ]  # BGR: canvas, lilac, navy
    amount = min(max(percent / 100, 0), 1) * 2
    index = min(int(amount), 1)
    fraction = amount - index
    return tuple(
        int(round(a + (b - a) * fraction))
        for a, b in zip(palette[index], palette[index + 1])
    )


def metrics(truth, predicted):
    a, b = np.asarray(truth), np.asarray(predicted)
    if a.size == 0 or a.shape != b.shape:
        raise ValueError(
            "Quality evaluation requires matching, nonempty labels and predictions"
        )
    known = b != -1
    tp = int(((a == 1) & (b == 1)).sum())
    fp = int(((a == 0) & (b == 1)).sum())
    fn = int(((a == 1) & (b != 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {
        "total": int(a.size),
        "coverage": float(known.mean()),
        "accuracy_on_known": float((a[known] == b[known]).mean())
        if known.any()
        else None,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative_including_abstentions": fn,
        "unknown": int((~known).sum()),
    }
