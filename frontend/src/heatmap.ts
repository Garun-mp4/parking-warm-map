import spec from "../../shared/heatmap.json";

export type HeatPalette = keyof typeof spec.palettes;
export const palettes = spec.palettes;
export const heatmapVersion = spec.version;
export function heatGradient(palette: HeatPalette): string {
  return `linear-gradient(to right, ${palettes[palette].stops.map((rgb) => `rgb(${rgb.join(",")})`).join(",")})`;
}
export function heatColor(
  value: number | null,
  palette: HeatPalette = "thermal",
): string {
  if (value == null) return "#e6e6e6";
  const stops = palettes[palette].stops;
  const position = Math.max(0, Math.min(100, value)) / 25;
  const index = Math.min(Math.floor(position), 3),
    fraction = position - index;
  return `rgb(${stops[index].map((c, j) => Math.round(c * (1 - fraction) + stops[index + 1][j] * fraction)).join(",")})`;
}
