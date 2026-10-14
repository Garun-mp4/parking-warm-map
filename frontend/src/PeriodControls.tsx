import { RotateCcw } from "lucide-react";
import { clock } from "./utils";

export default function PeriodControls({
  range,
  duration,
  captureStart,
  sparse,
  onChange,
}: {
  range: [number, number];
  duration: number;
  captureStart?: string;
  sparse: boolean;
  onChange: (range: [number, number]) => void;
}) {
  const gap = Math.min(1, duration);
  return (
    <section
      className="range-section map-range"
      aria-label="Период карты и статистики"
    >
      <div>
        <h3>Период карты и статистики</h3>
        <button className="text-button" onClick={() => onChange([0, duration])}>
          Весь день <RotateCcw size={14} />
        </button>
      </div>
      <div className="range-controls">
        <label>
          С {clock(range[0], captureStart)}
          <input
            aria-label="Начало интервала"
            type="range"
            min={0}
            max={duration}
            step={sparse ? 60 : Math.min(1, duration)}
            value={range[0]}
            onChange={(event) =>
              onChange([
                Math.min(Number(event.target.value), range[1] - gap),
                range[1],
              ])
            }
          />
        </label>
        <label>
          До {clock(range[1], captureStart)}
          <input
            aria-label="Конец интервала"
            type="range"
            min={0}
            max={duration}
            step={sparse ? 60 : Math.min(1, duration)}
            value={range[1]}
            onChange={(event) =>
              onChange([
                range[0],
                Math.max(Number(event.target.value), range[0] + gap),
              ])
            }
          />
        </label>
      </div>
      <p>
        Цвет — занятость за выбранный период. Время кадра меняется отдельно при
        просмотре видео.
      </p>
    </section>
  );
}
