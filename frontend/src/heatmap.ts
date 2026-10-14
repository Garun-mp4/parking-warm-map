import spec from "../../shared/heatmap.json";

export type HeatPalette = keyof typeof spec.palettes;
export const palettes = spec.palettes;
export const heatmapVersion = spec.version;
export const heatmapRender = spec.render;

type HSV = [number, number, number];
function toHSV(rgb: number[]): HSV {
  const [r, g, b] = rgb.map((v) => v / 255);
  const max = Math.max(r, g, b),
    delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta) {
    if (max === r) h = ((g - b) / delta + 6) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
  }
  return [h / 6, max ? delta / max : 0, max];
}
function fromHSV([h, s, v]: HSV): number[] {
  const sector = h * 6,
    index = Math.floor(sector),
    f = sector - index;
  const p = v * (1 - s),
    q = v * (1 - s * f),
    t = v * (1 - s * (1 - f));
  return [
    [v, t, p],
    [q, v, p],
    [p, v, t],
    [p, q, v],
    [t, p, v],
    [v, p, q],
  ][index % 6].map((c) => Math.floor(c * 255 + 0.5));
}
function buildRamp(palette: HeatPalette): number[][] {
  const stops = palettes[palette].stops.map(toHSV);
  return Array.from({ length: heatmapRender.rampSteps + 1 }, (_, step) => {
    const position = (step / heatmapRender.rampSteps) * (stops.length - 1);
    const index = Math.min(Math.floor(position), stops.length - 2),
      fraction = position - index;
    const [h0, s0, v0] = stops[index],
      [h1, s1, v1] = stops[index + 1];
    const delta = ((h1 - h0 + 1.5) % 1) - 0.5;
    return fromHSV([
      (h0 + delta * fraction + 1) % 1,
      s0 + (s1 - s0) * fraction,
      v0 + (v1 - v0) * fraction,
    ]);
  });
}
const ramps = { thermal: buildRamp("thermal"), warm: buildRamp("warm") };
function rampColor(value: number, palette: HeatPalette): string {
  const index = Math.floor(
    (Math.max(0, Math.min(100, value)) / 100) * heatmapRender.rampSteps + 0.5,
  );
  return `rgb(${ramps[palette][index].join(",")})`;
}
function buildGradient(palette: HeatPalette): string {
  return `linear-gradient(to right, ${Array.from({ length: 101 }, (_, value) => rampColor(value, palette)).join(",")})`;
}
const gradients = {
  thermal: buildGradient("thermal"),
  warm: buildGradient("warm"),
};
export function heatGradient(palette: HeatPalette): string {
  return gradients[palette];
}
export function heatColor(
  value: number | null,
  palette: HeatPalette = "thermal",
): string {
  if (value == null) return "#e6e6e6";
  return rampColor(value, palette);
}
