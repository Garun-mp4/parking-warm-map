import type { SourceSample } from "./types";

export const duration = (seconds: number) => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours} ч ${minutes ? `${minutes} мин` : ""}`.trim();
  if (minutes) return `${minutes} мин`;
  return `${Math.round(seconds)} с`;
};

export const clock = (seconds: number, start?: string) => {
  if (start) {
    // Captures are local source timestamps: do not reinterpret them in the viewer's timezone.
    const base = start.split("T")[1].split(":").map(Number);
    seconds += base[0] * 3600 + base[1] * 60 + (base[2] || 0);
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}${start ? "" : `:${String(s).padStart(2, "0")}`}`;
};

export function sampleIndex(
  samples: SourceSample[],
  videoSeconds: number,
): number {
  let low = 0,
    high = samples.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (samples[mid].video_seconds <= videoSeconds) low = mid + 1;
    else high = mid;
  }
  return Math.max(0, low - 1);
}

export { heatColor } from "./heatmap";

export const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value)}%`;

export async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: `Ошибка сервера ${response.status}` }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Проверьте введённые данные и геометрию мест.",
    );
  }
  return response.json();
}
