import { describe, expect, it } from "vitest";
import {
  clock,
  duration,
  heatColor,
  initialTimeScale,
  sampleIndex,
} from "./utils";
import type { Metadata } from "./types";

describe("known source scale of a prepared video", () => {
  const metadata: Metadata = {
    kind: "video",
    filename: "parking.mp4",
    source_name: "Camera",
    notice: "",
    width: 1280,
    height: 720,
    video_duration_seconds: 576,
    source_duration_seconds: 43200,
  };
  it("restores 12 source hours from the 9 minute 36 second timelapse", () => {
    expect(initialTimeScale(metadata)).toBe(75);
  });
  it("keeps ordinary uploaded video at its original speed", () => {
    expect(
      initialTimeScale({ ...metadata, source_duration_seconds: 576 }),
    ).toBe(1);
  });
  it("does not infer a linear scale from irregular timestamped photos", () => {
    expect(initialTimeScale({ ...metadata, kind: "sampled_timelapse" })).toBe(
      1,
    );
  });
});

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
  it("reads fractional UTC timestamps without losing source seconds", () => {
    expect(clock(4, "2026-10-13T12:59:56.283217+00:00")).toBe("13:00");
  });
  it("marks the next day for wall-clock time and keeps elapsed time unwrapped", () => {
    expect(clock(43200, "2026-10-13T12:59:56.283217+00:00")).toBe("00:59 (+1 д)");
    expect(clock(90000)).toBe("25:00:00");
  });
  it("distinguishes unknown from zero occupancy and keeps a fixed scale", () => {
    expect(heatColor(null)).toBe("#e6e6e6");
    expect(heatColor(0)).toBe("rgb(24,83,235)");
    expect(heatColor(100)).toBe("rgb(240,35,35)");
    expect(heatColor(100, "warm")).toBe("rgb(196,28,28)");
  });
  it("keeps saturated intermediate hues and clamps the shared fixed scale", () => {
    expect(heatColor(37.5)).toBe("rgb(0,255,15)");
    expect(heatColor(-1)).toBe(heatColor(0));
    expect(heatColor(101)).toBe(heatColor(100));
  });
});
