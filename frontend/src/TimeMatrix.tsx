import { memo, useLayoutEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Analysis } from "./types";
import { clock } from "./utils";

const PAGE_SIZE = 24;
const label = (state: number | undefined) =>
  state === 1 ? "Занято" : state === 0 ? "Свободно" : "Не определено";
const stateClass = (state: number | undefined) =>
  state === 1 ? "occupied" : state === 0 ? "free" : "unknown";

function TimeMatrix({
  result,
  index,
  selected,
  captureStart,
  onSelect,
  onSeek,
}: {
  result: Analysis;
  index: number;
  selected: string | null;
  captureStart?: string;
  onSelect: (id: string) => void;
  onSeek: (seconds: number) => void;
}) {
  const [window, setWindow] = useState({
    index,
    page: Math.floor(index / PAGE_SIZE),
  });
  // Follow a new video frame, while letting the reader browse history with playback paused.
  if (window.index !== index)
    setWindow({ index, page: Math.floor(index / PAGE_SIZE) });
  const pageCount = Math.max(1, Math.ceil(result.samples.length / PAGE_SIZE));
  const page = Math.min(window.page, pageCount - 1);
  const start = page * PAGE_SIZE;
  const samples = result.samples.slice(start, start + PAGE_SIZE);
  const grid = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (pendingFocus.current) {
      grid.current
        ?.querySelector<HTMLButtonElement>(
          `[data-cell="${pendingFocus.current}"]`,
        )
        ?.focus();
      pendingFocus.current = null;
    }
  });
  const move = (row: number, observation: number, focus = false) => {
    setWindow({
      index: observation,
      page: Math.floor(observation / PAGE_SIZE),
    });
    if (focus) pendingFocus.current = `${row}-${observation}`;
    onSelect(result.slots[row].id);
    onSeek(result.samples[observation].video_seconds);
  };
  return (
    <section className="matrix-section" aria-label="История мест">
      <div className="section-title">
        <div>
          <h3>У каждого места — своя история</h3>
          <p>
            Строка — место. Столбец — реальный момент наблюдения. Нажмите на
            ячейку, чтобы открыть кадр. Стрелки клавиатуры перемещают по
            истории.
          </p>
        </div>
        <div className="matrix-key">
          <span>Свободно</span>
          <i className="dot free" />
          <i className="dot occupied" />
          <span>Занято</span>
          <i className="dot unknown" />
          <span>Неясно</span>
        </div>
      </div>
      {pageCount > 1 && (
        <div className="matrix-pagination">
          <span aria-live="polite">
            Наблюдения {start + 1}–{start + samples.length} из{" "}
            {result.samples.length}
          </span>
          <div>
            <button
              className="icon-button"
              aria-label="Предыдущие наблюдения"
              disabled={page === 0}
              onClick={() => setWindow({ index, page: page - 1 })}
            >
              <ChevronLeft size={18} />
            </button>
            <button
              className="text-button"
              onClick={() =>
                setWindow({ index, page: Math.floor(index / PAGE_SIZE) })
              }
            >
              К текущему кадру
            </button>
            <button
              className="icon-button"
              aria-label="Следующие наблюдения"
              disabled={page === pageCount - 1}
              onClick={() => setWindow({ index, page: page + 1 })}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      )}
      <div className="matrix-scroll">
        <div
          ref={grid}
          className="matrix"
          style={{
            gridTemplateColumns: `80px repeat(${samples.length}, minmax(20px, 1fr))`,
          }}
        >
          <span className="matrix-corner">Место</span>
          {samples.map((sample, i) => (
            <span className="matrix-time" key={start + i}>
              {i % 3 === 0 ? clock(sample.source_seconds, captureStart) : ""}
            </span>
          ))}
          {result.slots.map((slot, row) => (
            <div
              className={`matrix-row ${selected === slot.id ? "selected" : ""}`}
              key={slot.id}
            >
              <button
                className="matrix-label"
                onClick={() => onSelect(slot.id)}
                aria-label={`Выбрать ${slot.name}`}
              >
                {slot.id}
              </button>
              {samples.map((sample, i) => {
                const observation = start + i;
                const tabbable =
                  observation ===
                  (index >= start && index < start + samples.length
                    ? index
                    : start);
                return (
                  <button
                    key={observation}
                    className={`matrix-cell ${stateClass(sample.states[row])} ${observation === index ? "current" : ""}`}
                    data-cell={`${row}-${observation}`}
                    tabIndex={
                      (selected === slot.id || (!selected && row === 0)) &&
                      tabbable
                        ? 0
                        : -1
                    }
                    aria-label={`Место ${slot.id}, ${clock(sample.source_seconds, captureStart)}, ${label(sample.states[row])}`}
                    title={`${clock(sample.source_seconds, captureStart)} · ${label(sample.states[row])}`}
                    onClick={() => move(row, observation)}
                    onKeyDown={(event) => {
                      const delta: Record<string, [number, number]> = {
                        ArrowLeft: [0, -1],
                        ArrowRight: [0, 1],
                        ArrowUp: [-1, 0],
                        ArrowDown: [1, 0],
                      };
                      if (!delta[event.key]) return;
                      event.preventDefault();
                      const [dr, di] = delta[event.key];
                      move(
                        Math.max(
                          0,
                          Math.min(result.slots.length - 1, row + dr),
                        ),
                        Math.max(
                          0,
                          Math.min(result.samples.length - 1, observation + di),
                        ),
                        true,
                      );
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default memo(TimeMatrix);
