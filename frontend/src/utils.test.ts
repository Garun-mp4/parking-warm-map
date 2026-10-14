import { describe, expect, it } from "vitest";
import { clock, duration, heatColor, sampleIndex } from "./utils";

describe("source timestamps, not sped-up playback time", () => {
  const samples = [
    { video_seconds: 0, source_seconds: 0 },
    { video_seconds: 2, source_seconds: 1740 },
    { video_seconds: 4, source_seconds: 3600 },
  ];
  it("uses actual irregular capture times and holds the current captured frame", () => {
    expect(sampleIndex(samples, 1.9)).toBe(0);
    expect(samples[sampleIndex(samples, 2)].source_seconds).toBe(1740);
    expect(sampleIndex(samples, 100)).toBe(2);
  });
  it("preserves source local clock regardless of the computer timezone", () => {
    expect(clock(1740, "2015-11-16T07:22:00")).toBe("07:51");
    expect(duration(36720)).toBe("10 ч 12 мин");
  });
  it("distinguishes unknown from zero occupancy and keeps a fixed scale", () => {
    expect(heatColor(null)).toBe("#e6e6e6");
    expect(heatColor(0)).toBe("rgb(255,255,255)");
    expect(heatColor(100)).toBe("rgb(31,29,61)");
  });
});
