export type Point = [number, number];
export interface Slot {
  id: string;
  name: string;
  points: Point[];
}
export interface SourceSample {
  video_seconds: number;
  source_seconds: number;
  captured_at?: string;
}
export interface Metadata {
  kind: "video" | "sampled_timelapse";
  filename: string;
  source_name: string;
  source_url?: string;
  license?: string;
  notice: string;
  width: number;
  height: number;
  video_duration_seconds: number;
  source_duration_seconds: number;
  sample_count?: number;
  capture_start?: string;
  capture_end?: string;
  samples?: SourceSample[];
}
export interface Settings {
  model: "malexnet" | "yolo11n" | "yolo11s";
  confidence: number;
  sample_seconds: number;
  confirm_seconds: number;
  time_scale: number;
}
export interface Run {
  id: string;
  status: string;
  progress: number;
  stage: string;
  error: string | null;
  revision: number;
  settings: Settings;
}
export interface Project {
  id: string;
  title: string;
  metadata: Metadata;
  slots: Slot[];
  revision: number;
  latest_run: Run | null;
  completed_run_id: string | null;
}
export interface Sample extends SourceSample {
  states: number[];
  probabilities: number[];
  boxes: { xyxy: [number, number, number, number]; confidence: number }[];
}
export interface Analysis {
  run_id: string;
  project_id: string;
  revision: number;
  slots: Slot[];
  samples: Sample[];
  source_duration_seconds: number;
  video_duration_seconds: number;
  model: string;
  processing_seconds: number;
  sampled: boolean;
  notice: string;
  settings: Settings;
}
export interface SlotSummary extends Slot {
  occupancy: number | null;
  coverage: number;
  occupied_seconds: number;
  free_seconds: number;
  unknown_seconds: number;
  changes: number;
}
export interface Summary {
  start: number;
  end: number;
  duration: number;
  slots: SlotSummary[];
  occupancy: number | null;
  coverage: number;
  peak_occupied: number;
  changes: number;
  timeline: {
    time: number;
    occupied: number;
    free: number;
    unknown: number;
    video_seconds: number;
  }[];
}
