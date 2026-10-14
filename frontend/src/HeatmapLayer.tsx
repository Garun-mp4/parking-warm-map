import { memo, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { SlotSummary } from "./types";
import { percent } from "./utils";

interface Props {
  url: string | null;
  slots: SlotSummary[];
  width: number;
  height: number;
  opacity: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
}

function HeatmapLayer({
  url,
  slots,
  width,
  height,
  opacity,
  selected,
  onSelect,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const targets = useRef(new Map<string, SVGGElement>());
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failure, setFailure] = useState<{
    url: string;
    message: string;
  } | null>(null);
  const [retry, setRetry] = useState(0);
  const [hovered, setHovered] = useState<string | null>(null);
  const current = slots.find((s) => s.id === (selected || hovered));
  const ready = !!url && loaded === url && failure?.url !== url;
  const failed = failure?.url === url ? failure : null;

  useEffect(() => {
    if (!url) return;
    const controller = new AbortController();
    let disposed = false;
    void (async () => {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error("Не удалось построить тепловой слой.");
      const bitmap = await createImageBitmap(await response.blob());
      try {
        if (disposed || !canvas.current) return;
        const context = canvas.current.getContext("2d");
        if (!context) throw new Error("Браузер не поддерживает Canvas 2D.");
        canvas.current.width = bitmap.width;
        canvas.current.height = bitmap.height;
        context.clearRect(0, 0, bitmap.width, bitmap.height);
        context.drawImage(bitmap, 0, 0);
        setLoaded(url);
        setFailure(null);
      } finally {
        bitmap.close();
      }
    })().catch((reason: unknown) => {
      if (!disposed)
        setFailure({
          url,
          message:
            reason instanceof Error
              ? reason.message
              : "Не удалось загрузить карту.",
        });
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [url, retry]);

  const center = current
    ? current.points.reduce(
        (a, p) => [
          a[0] + p[0] / current.points.length,
          a[1] + p[1] / current.points.length,
        ],
        [0, 0],
      )
    : null;
  function move(id: string, direction: number) {
    const index = slots.findIndex((s) => s.id === id);
    const next = slots[(index + direction + slots.length) % slots.length];
    if (next) {
      onSelect(next.id);
      setHovered(null);
      targets.current.get(next.id)?.focus();
    }
  }

  return (
    <div
      className="heatmap-layer"
      data-ready={ready}
      aria-busy={!ready && !failed}
    >
      <canvas
        ref={canvas}
        className="thermal-canvas"
        style={{ opacity: ready ? opacity : 0 }}
        aria-hidden="true"
      />
      {ready && (
        <svg
          className="heatmap-hit-layer"
          viewBox={`0 0 ${width} ${height}`}
          aria-label="Места на тепловой карте"
        >
          {slots.map((slot, i) => (
            <g
              key={slot.id}
              ref={(node) => {
                if (node) targets.current.set(slot.id, node);
                else targets.current.delete(slot.id);
              }}
              role="button"
              tabIndex={selected === slot.id || (!selected && i === 0) ? 0 : -1}
              data-heat-slot={slot.id}
              aria-label={`${slot.name}: занятость ${percent(slot.occupancy)}, покрытие ${percent(slot.coverage)}. Стрелки переключают места.`}
              onPointerEnter={(event) => {
                if (event.pointerType === "mouse") setHovered(slot.id);
              }}
              onPointerLeave={() => setHovered(null)}
              onFocus={() => setHovered(slot.id)}
              onBlur={() => setHovered(null)}
              onClick={() => {
                onSelect(slot.id);
                setHovered(null);
              }}
              onKeyDown={(event) => {
                if (
                  ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(
                    event.key,
                  )
                ) {
                  event.preventDefault();
                  move(
                    slot.id,
                    event.key === "ArrowRight" || event.key === "ArrowDown"
                      ? 1
                      : -1,
                  );
                } else if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(slot.id);
                } else if (event.key === "Escape") {
                  onSelect(null);
                  setHovered(null);
                }
              }}
            >
              <circle
                className="map-focus-ring"
                cx={
                  (slot.points.reduce((sum, p) => sum + p[0], 0) /
                    slot.points.length) *
                  width
                }
                cy={
                  (slot.points.reduce((sum, p) => sum + p[1], 0) /
                    slot.points.length) *
                  height
                }
                r={width * 0.012}
                fill="none"
                stroke="black"
                strokeWidth="5"
                vectorEffect="non-scaling-stroke"
              />
              <circle
                className="map-focus-ring"
                cx={
                  (slot.points.reduce((sum, p) => sum + p[0], 0) /
                    slot.points.length) *
                  width
                }
                cy={
                  (slot.points.reduce((sum, p) => sum + p[1], 0) /
                    slot.points.length) *
                  height
                }
                r={width * 0.012}
                fill="none"
                stroke="white"
                strokeWidth="3"
                vectorEffect="non-scaling-stroke"
              />
              <polygon
                points={slot.points
                  .map((p) => `${p[0] * width},${p[1] * height}`)
                  .join(" ")}
                fill="transparent"
                stroke="none"
              />
            </g>
          ))}
          {center && (
            <g className="heatmap-marker" aria-hidden="true">
              <line
                x1={center[0] * width}
                y1={center[1] * height}
                x2={width * 0.82}
                y2={height * 0.6}
                stroke="white"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
              <circle
                cx={center[0] * width}
                cy={center[1] * height}
                r={width * 0.009}
                fill="none"
                stroke="black"
                strokeWidth="5"
                vectorEffect="non-scaling-stroke"
              />
              <circle
                cx={center[0] * width}
                cy={center[1] * height}
                r={width * 0.009}
                fill="none"
                stroke="white"
                strokeWidth="3"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          )}
        </svg>
      )}
      {ready && current && (
        <div
          className={`heat-tooltip ${hovered && !selected ? "hover-only" : ""}`}
          role="status"
        >
          <strong>{current.name}</strong>
          {selected && (
            <button
              className="icon-button"
              aria-label="Закрыть карточку места"
              onClick={() => {
                onSelect(null);
                setHovered(null);
              }}
            >
              <X size={16} />
            </button>
          )}
          <span className="heat-tooltip-value">
            {percent(current.occupancy)}
          </span>
          <p>
            {current.occupancy == null
              ? "Нет определённых наблюдений"
              : "занято среди известных интервалов"}
          </p>
          <div>
            Покрытие <b>{percent(current.coverage)}</b>
          </div>
          {current.coverage < 50 && (
            <small>Мало данных: результат требует осторожной оценки.</small>
          )}
        </div>
      )}
      {!ready && (
        <div className="heat-layer-status" role={failed ? "alert" : "status"}>
          {failed ? (
            <>
              {failed.message}
              <button
                className="text-button"
                onClick={() => setRetry((n) => n + 1)}
              >
                Повторить
              </button>
            </>
          ) : url ? (
            "Строим тепловой слой…"
          ) : (
            "Обновляем выбранный интервал…"
          )}
        </div>
      )}
    </div>
  );
}
export default memo(HeatmapLayer);
