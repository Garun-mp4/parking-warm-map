"""A normalized occupancy field, clipped to observed regions; never a density sum."""

from functools import lru_cache
import json
import cv2
import numpy as np
from .config import ROOT

SPEC = json.loads((ROOT / "shared/heatmap.json").read_text(encoding="utf-8"))


def color(value, palette="thermal"):
    if value is None:
        return (230, 230, 230)
    stops = np.asarray(SPEC["palettes"][palette]["stops"], dtype=np.float32)
    position = np.clip(float(value), 0, 100) / 25
    index = min(int(position), 3)
    rgb = np.floor(
        stops[index] * (1 - (position - index))
        + stops[index + 1] * (position - index)
        + 0.5
    )
    return tuple(int(c) for c in rgb)


def signature(slots):
    return tuple((tuple(tuple(p) for p in s["points"]), s["occupancy"]) for s in slots)


@lru_cache(maxsize=8)
def field(items, width, height, palette="thermal"):
    """Return immutable RGBA. Alpha encodes support, never the occupancy percentage."""
    width, height = int(width), int(height)
    if not 1 <= width <= 1600 or not 1 <= height <= 1600:
        raise ValueError("Недопустимый размер теплового слоя")
    if palette not in SPEC["palettes"]:
        raise ValueError("Неизвестная палитра")
    numerator = np.zeros((height, width), np.float32)
    denominator = np.zeros_like(numerator)
    unknown_weight = np.zeros_like(numerator)
    feather_weight = np.zeros_like(numerator)
    observed = np.zeros((height, width), np.uint8)
    unknown = np.zeros_like(observed)
    for coordinates, occupancy in items:
        points = np.asarray(coordinates, np.float32) * [width, height]
        polygon = np.round(points).astype(np.int32)
        cv2.fillPoly(observed, [polygon], 1)
        if occupancy is None:
            cv2.fillPoly(unknown, [polygon], 1)
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(points.astype(np.float32))
        # Elliptical support follows each ROI's size and orientation. Constant
        # values stay constant through blending; 0% has visible blue support.
        a, b = max(rw * 0.50, 1), max(rh * 0.50, 1)
        radius = max(a, b) * 1.6
        x0, x1 = max(0, int(cx - radius)), min(width, int(cx + radius) + 1)
        y0, y1 = max(0, int(cy - radius)), min(height, int(cy + radius) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        theta = np.deg2rad(angle)
        dx, dy = xx - cx, yy - cy
        u = (dx * np.cos(theta) + dy * np.sin(theta)) / a
        v = (-dx * np.sin(theta) + dy * np.cos(theta)) / b
        distance = u * u + v * v
        weight = np.exp(-3.0 * distance).astype(np.float32)
        weight[distance > 2.56] = 0
        feather_weight[y0:y1, x0:x1] += weight * max(2, min(rw, rh) * 0.16)
        if occupancy is None:
            unknown_weight[y0:y1, x0:x1] += weight
        else:
            numerator[y0:y1, x0:x1] += weight * np.clip(occupancy, 0, 100)
            denominator[y0:y1, x0:x1] += weight
    values = np.divide(
        numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0
    )
    stops = np.asarray(SPEC["palettes"][palette]["stops"], dtype=np.float32)
    position = np.clip(values / 25, 0, 4)
    indices = np.minimum(position.astype(np.int32), 3)
    fraction = (position - indices)[..., None]
    rgb = np.floor(
        stops[indices] * (1 - fraction) + stops[indices + 1] * fraction + 0.5
    ).astype(np.uint8)
    # A hard outside mask prevents Gaussian tails from suggesting observations
    # in driveways. Feathering happens only INSIDE the annotated support.
    distance_inside = cv2.distanceTransform(observed, cv2.DIST_L2, 3)
    support = denominator + unknown_weight
    local_radius = np.divide(
        feather_weight, support, out=np.full_like(support, 2), where=support > 0
    )
    feather = np.clip(distance_inside / np.maximum(local_radius, 2), 0, 1)
    feather = feather * feather * (3 - 2 * feather)
    alpha = (1 - np.exp(-4 * denominator)) * feather
    alpha[(denominator <= 0) | (unknown > 0)] = 0
    yy, xx = np.indices((height, width))
    stripe = ((xx + yy) // max(3, width // 160)) % 2 == 0
    missing = (unknown > 0) & (observed > 0)
    rgb[missing] = np.where(stripe[missing, None], 150, 225)
    alpha[missing] = (
        (1 - np.exp(-4 * unknown_weight[missing])) * feather[missing] * 0.85
    )
    rgba = np.dstack((rgb, np.floor(np.clip(alpha, 0, 1) * 255 + 0.5).astype(np.uint8)))
    rgba.setflags(write=False)
    return rgba


def layer(slots, width, height, palette="thermal"):
    scale = min(1.0, 1200 / max(width, height))
    return field(
        signature(slots),
        max(1, round(width * scale)),
        max(1, round(height * scale)),
        palette,
    )


def png_layer(slots, width, height, palette="thermal"):
    rgba = layer(slots, width, height, palette)
    return cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1].tobytes()


def composite(frame, rgba, opacity=0.6):
    """Match the browser's saturate(.45) video and independent layer opacity."""
    if not 0 <= opacity <= 1:
        raise ValueError("Прозрачность должна быть от 0 до 1")
    if rgba.shape[:2] != frame.shape[:2]:
        rgba = cv2.resize(
            rgba, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR
        )
    source = frame.astype(np.float32)
    luminance = (
        source[..., 2] * 0.2126 + source[..., 1] * 0.7152 + source[..., 0] * 0.0722
    )
    background = source * 0.45 + luminance[..., None] * 0.55
    alpha = rgba[..., 3:4].astype(np.float32) / 255 * opacity
    return np.clip(
        background * (1 - alpha) + rgba[..., :3][..., ::-1] * alpha, 0, 255
    ).astype(np.uint8)
