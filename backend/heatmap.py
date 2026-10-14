"""Continuous parking-row fields, interpolating measurements without density sums."""

from colorsys import hsv_to_rgb, rgb_to_hsv
from functools import lru_cache
import json
import cv2
import numpy as np
from .config import ROOT

SPEC = json.loads((ROOT / "shared/heatmap.json").read_text(encoding="utf-8"))
RENDER = SPEC["render"]


@lru_cache(maxsize=2)
def color_ramp(palette):
    """Interpolate hue, saturation and value, avoiding dull RGB midpoints."""
    stops = [
        rgb_to_hsv(*(c / 255 for c in rgb))
        for rgb in SPEC["palettes"][palette]["stops"]
    ]
    ramp = []
    for step in range(RENDER["rampSteps"] + 1):
        position = step / RENDER["rampSteps"] * (len(stops) - 1)
        index = min(int(position), len(stops) - 2)
        fraction = position - index
        h0, s0, v0 = stops[index]
        h1, s1, v1 = stops[index + 1]
        hue = (h0 + ((h1 - h0 + 0.5) % 1 - 0.5) * fraction) % 1
        rgb = hsv_to_rgb(hue, s0 + (s1 - s0) * fraction, v0 + (v1 - v0) * fraction)
        ramp.append([int(c * 255 + 0.5) for c in rgb])
    result = np.asarray(ramp, np.uint8)
    result.setflags(write=False)
    return result


def color(value, palette="thermal"):
    if value is None:
        return (230, 230, 230)
    index = int(np.clip(float(value), 0, 100) / 100 * RENDER["rampSteps"] + 0.5)
    return tuple(int(c) for c in color_ramp(palette)[index])


def signature(slots):
    return tuple((tuple(tuple(p) for p in s["points"]), s["occupancy"]) for s in slots)


def parking_rows(items, width, height):
    """Infer neighboring rows in camera coordinates; return projected place knots."""
    places = []
    for coordinates, occupancy in dict.fromkeys(items):
        points = np.asarray(coordinates, np.float32) * [width, height]
        center, size, angle = cv2.minAreaRect(points.astype(np.float32))
        places.append((points, np.asarray(center), occupancy, size, angle))
    if not places:
        return np.array([1.0, 0.0]), []
    centers = np.asarray([p[1] for p in places])
    # Dense nearest-neighbor directions reveal row orientation, including tilted
    # cameras. For sparse layouts use the short side of the parking rectangles.
    if len(places) >= 3:
        delta = centers[:, None, :] - centers[None, :, :]
        distance = np.linalg.norm(delta, axis=2)
        distance[distance < 1] = np.inf
        angles, weights = [], []
        for i in range(len(places)):
            for j in np.argsort(distance[i])[:2]:
                if not np.isfinite(distance[i, j]):
                    continue
                angles.append(np.arctan2(delta[i, j, 1], delta[i, j, 0]) % np.pi)
                weights.append(1 / distance[i, j])
        angles, weights = np.asarray(angles), np.asarray(weights)
        scores = np.asarray(
            [
                np.sum(
                    weights[
                        np.abs((angles - a + np.pi / 2) % np.pi - np.pi / 2)
                        < np.pi / 12
                    ]
                )
                for a in angles
            ]
        )
        angle = angles[np.argmax(scores)] if len(angles) else 0
        near = np.abs((angles - angle + np.pi / 2) % np.pi - np.pi / 2) < np.pi / 12
        angle = (
            np.arctan2(
                np.sum(weights[near] * np.sin(2 * angles[near])),
                np.sum(weights[near] * np.cos(2 * angles[near])),
            )
            / 2
            if np.any(near)
            else angle
        )
    else:
        _, _, _, (rw, rh), degrees = places[0]
        angle = np.deg2rad(degrees + (90 if rw > rh else 0))
    axis = np.array([np.cos(angle), np.sin(angle)])
    if axis[0] < -1e-6 or (abs(axis[0]) <= 1e-6 and axis[1] < 0):
        axis = -axis
    normal = np.array([-axis[1], axis[0]])
    nodes = []
    for points, center, occupancy, _, _ in places:
        u, v = points @ axis, points @ normal
        nodes.append(
            {
                "u": float(center @ axis),
                "v": float(center @ normal),
                "width": max(float(np.ptp(u)), 1),
                "depth": max(float(np.ptp(v)), 1),
                "occupancy": occupancy,
            }
        )
    parents = list(range(len(nodes)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes[:i]):
            perpendicular = abs(a["v"] - b["v"])
            gap = abs(a["u"] - b["u"]) - (a["width"] + b["width"]) / 2
            if perpendicular <= 0.38 * (a["depth"] + b["depth"]) and gap <= RENDER[
                "rowGapLimit"
            ] * min(a["width"], b["width"]):
                parents[find(i)] = find(j)
    groups = {}
    for i, node in enumerate(nodes):
        groups.setdefault(find(i), []).append(node)
    rows = list(groups.values())
    for row in rows:
        for node in row:
            radius = node["depth"] * RENDER["rowDepthScale"] / 2
            for other in nodes:
                if other in row or abs(node["u"] - other["u"]) > (
                    node["width"] + other["width"]
                ):
                    continue
                radius = min(
                    radius, abs(node["v"] - other["v"]) * RENDER["roadClearance"]
                )
            node["radius"] = max(radius, 1)
        row.sort(key=lambda n: n["u"])
        # Coincident/overlapping annotations do not create density or alpha gain.
        merged = []
        for node in row:
            if merged and node["u"] - merged[-1]["u"] < 1:
                previous = merged[-1]
                values = [previous["occupancy"], node["occupancy"]]
                previous["occupancy"] = None if None in values else sum(values) / 2
                previous["width"] = max(previous["width"], node["width"])
                previous["radius"] = max(previous["radius"], node["radius"])
                previous["v"] = (previous["v"] + node["v"]) / 2
            else:
                merged.append(node.copy())
        row[:] = merged
    return axis, rows


@lru_cache(maxsize=8)
def field(items, width, height, palette="thermal"):
    """Interpolate exact place values along softly bounded, connected row ribbons."""
    width, height = int(width), int(height)
    if not 1 <= width <= 1600 or not 1 <= height <= 1600:
        raise ValueError("Недопустимый размер теплового слоя")
    if palette not in SPEC["palettes"]:
        raise ValueError("Неизвестная палитра")
    axis, rows = parking_rows(items, width, height)
    normal = np.array([-axis[1], axis[0]])
    rgba = np.zeros((height, width, 4), np.uint8)
    for row in rows:
        knots = np.array([n["u"] for n in row])
        centers = np.array([n["v"] for n in row])
        radii = np.array([n["radius"] for n in row])
        caps = np.array([n["width"] * RENDER["endCapScale"] for n in row])
        bounds = np.array(
            [
                axis * n["u"]
                + normal * n["v"]
                + axis * caps[i] * a
                + normal * radii[i] * b
                for i, n in enumerate(row)
                for a in (-1, 1)
                for b in (-1, 1)
            ]
        )
        x0, y0 = np.maximum(np.floor(bounds.min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(
            np.ceil(bounds.max(axis=0)).astype(int) + 1, [width, height]
        )
        if x1 <= x0 or y1 <= y0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        u, v = xx * axis[0] + yy * axis[1], xx * normal[0] + yy * normal[1]
        spine, radius = np.interp(u, knots, centers), np.interp(u, knots, radii)
        # A connected row still follows the scale of its actual places. Large
        # inter-place gaps form a soft neck rather than an opaque rectangular strip.
        influence = np.zeros_like(u)
        for node in row:
            along = (u - node["u"]) / (node["width"] * RENDER["influenceScale"])
            influence = np.maximum(influence, np.exp(-0.5 * along**4))
        radius = radius * (0.75 + 0.25 * influence)
        beyond = np.maximum(
            (knots[0] - u) / caps[0], np.maximum((u - knots[-1]) / caps[-1], 0)
        )
        distance = np.sqrt(((v - spine) / radius) ** 2 + beyond**2)
        edge = np.clip(
            (distance - RENDER["coreRadius"]) / (1 - RENDER["coreRadius"]), 0, 1
        )
        alpha = (1 - edge * edge * (3 - 2 * edge)) * influence
        values = np.array(
            [n["occupancy"] if n["occupancy"] is not None else 0 for n in row]
        )
        unknown = np.array([n["occupancy"] is None for n in row])
        if len(row) == 1:
            value = np.full_like(u, values[0])
            missing = np.full(u.shape, unknown[0])
        else:
            left = np.clip(np.searchsorted(knots, u, side="right") - 1, 0, len(row) - 2)
            t = np.clip((u - knots[left]) / (knots[left + 1] - knots[left]), 0, 1)
            blend = t * t * (3 - 2 * t)
            value = values[left] * (1 - blend) + values[left + 1] * blend
            missing = np.where(t <= 0.5, unknown[left], unknown[left + 1])
            # An unknown place never pulls a known value towards false zero.
            value = np.where(
                unknown[left],
                values[left + 1],
                np.where(unknown[left + 1], values[left], value),
            )
        indices = np.floor(
            np.clip(value, 0, 100) / 100 * RENDER["rampSteps"] + 0.5
        ).astype(np.int32)
        rgb = color_ramp(palette)[indices]
        stripe = ((xx + yy) // max(3, width // 160)) % 2 == 0
        rgb[missing] = np.where(stripe[missing, None], 150, 225)
        alpha[missing] *= 0.85
        incoming = np.floor(alpha * 255 + 0.5).astype(np.uint8)
        target = rgba[y0:y1, x0:x1]
        take = incoming > target[..., 3]
        target[take, :3] = rgb[take]
        target[take, 3] = incoming[take]
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


def composite(frame, rgba, opacity=RENDER["defaultOpacity"]):
    """Match CSS saturation and the browser's premultiplied-alpha compositing."""
    if not 0 <= opacity <= 1:
        raise ValueError("Прозрачность должна быть от 0 до 1")
    alpha = rgba[..., 3:4].astype(np.float32) / 255
    premultiplied = np.concatenate((rgba[..., :3] * alpha, alpha), axis=2)
    if rgba.shape[:2] != frame.shape[:2]:
        premultiplied = cv2.resize(
            premultiplied,
            (frame.shape[1], frame.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
    source = frame.astype(np.float32)
    luminance = (
        source[..., 2] * 0.2126 + source[..., 1] * 0.7152 + source[..., 0] * 0.0722
    )
    saturation = RENDER["videoSaturation"]
    background = source * saturation + luminance[..., None] * (1 - saturation)
    alpha = premultiplied[..., 3:4] * opacity
    return np.clip(
        background * (1 - alpha) + premultiplied[..., :3][..., ::-1] * opacity, 0, 255
    ).astype(np.uint8)
