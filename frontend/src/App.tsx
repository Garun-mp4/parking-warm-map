import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronDown,
  CircleHelp,
  Expand,
  Layers,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  Analysis,
  Point,
  Project,
  Settings,
  Slot,
  Summary,
} from "./types";
import {
  clock,
  duration,
  heatColor,
  percent,
  request,
  sampleIndex,
} from "./utils";
import UploadDialog from "./UploadDialog";
import HeatmapLayer from "./HeatmapLayer";
import {
  heatGradient,
  heatmapVersion,
  heatmapRender,
  palettes,
} from "./heatmap";
import type { HeatPalette } from "./heatmap";

const initialSettings: Settings = {
  model: "malexnet",
  confidence: 0.7,
  sample_seconds: 1,
  confirm_seconds: 2,
  time_scale: 1,
};
const stateLabel = (state: number | undefined) =>
  state === 1 ? "Занято" : state === 0 ? "Свободно" : "Не определено";
const stateClass = (state: number | undefined) =>
  state === 1 ? "occupied" : state === 0 ? "free" : "unknown";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [result, setResult] = useState<Analysis | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [view, setView] = useState<"analysis" | "editor" | "method">(
    "analysis",
  );
  const [mode, setMode] = useState<"video" | "states" | "heatmap">("heatmap");
  const [palette, setPalette] = useState<HeatPalette>("thermal");
  const [heatOpacity, setHeatOpacity] = useState(heatmapRender.defaultOpacity);
  const [upload, setUpload] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [settings, setSettings] = useState(initialSettings);
  const [seconds, setSeconds] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [range, setRange] = useState<[number, number]>([0, 1]);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [draft, setDraft] = useState<Point[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [history, setHistory] = useState<Slot[][]>([]);
  const [dirty, setDirty] = useState(false);
  const [filter, setFilter] = useState("");
  const [validation, setValidation] = useState<{
    selected_model: string;
    test?: { f1: number; coverage: number; total: number };
  } | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef<{ slot: string; point: number } | null>(null);
  const loadedRun = useRef<string | null>(null);

  const showError = (reason: unknown) =>
    setError(
      reason instanceof Error
        ? reason.message
        : "Не удалось выполнить действие.",
    );
  const loadProject = useCallback(async (id: string, reset = false) => {
    const next = await request<Project>(`/api/projects/${id}`);
    setProject(next);
    if (reset) {
      loadedRun.current = null;
      setResult(null);
      setSummary(null);
      setSeconds(0);
      setSelected(null);
      setSlots(next.slots);
      setDirty(false);
      setHistory([]);
      setDraft([]);
      setDrawing(false);
      setRange([0, next.metadata.source_duration_seconds]);
      setSettings(initialSettings);
      localStorage.setItem("parking.project", id);
    }
    if (next.completed_run_id && loadedRun.current !== next.completed_run_id) {
      const data = await request<Analysis>(
        `/api/runs/${next.completed_run_id}/result`,
      );
      setRange([0, data.source_duration_seconds]);
      setResult(data);
      loadedRun.current = data.run_id;
    }
  }, []);

  const reload = useCallback(async () => {
    const list = await request<Project[]>("/api/projects");
    setProjects(list);
    if (list.length) {
      const saved = localStorage.getItem("parking.project");
      await loadProject(
        list.find((p) => p.id === saved)?.id || list[0].id,
        true,
      );
    }
  }, [loadProject]);

  useEffect(() => {
    let disposed = false;
    void request<Project[]>("/api/projects")
      .then(async (list) => {
        if (disposed) return;
        setProjects(list);
        const saved = localStorage.getItem("parking.project");
        if (list.length)
          await loadProject(
            list.find((p) => p.id === saved)?.id || list[0].id,
            true,
          );
      })
      .catch((reason) => {
        if (!disposed) showError(reason);
      });
    return () => {
      disposed = true;
    };
  }, [loadProject]);
  useEffect(() => {
    const active = project?.latest_run;
    if (!project || !active || !["running", "queued"].includes(active.status))
      return;
    const id = window.setInterval(() => {
      void loadProject(project.id).catch(showError);
    }, 1000);
    return () => window.clearInterval(id);
  }, [project, loadProject]);
  useEffect(() => {
    if (!result) return;
    const controller = new AbortController();
    void request<Summary>(
      `/api/runs/${result.run_id}/summary?start=${range[0]}&end=${range[1]}`,
      { signal: controller.signal },
    )
      .then(setSummary)
      .catch((reason) => {
        if (reason.name !== "AbortError") showError(reason);
      });
    return () => controller.abort();
  }, [result, range]);
  useEffect(() => {
    void fetch("/api/validation")
      .then((response) => (response.ok ? response.json() : null))
      .then(setValidation)
      .catch(() => {
        /* Optional recorded experiment; analysis does not depend on it. */
      });
  }, []);

  const meta = project?.metadata;
  const sourceSamples = result?.samples || meta?.samples || [];
  const index = sourceSamples.length ? sampleIndex(sourceSamples, seconds) : 0;
  const sample = result?.samples[index];
  const sourceSeconds =
    sourceSamples[index]?.source_seconds ?? seconds * settings.time_scale;
  const displayedSlots =
    view === "editor" ? slots : result?.slots || project?.slots || [];
  const selectedIndex = displayedSlots.findIndex(
    (slot) => slot.id === selected,
  );
  const selectedSummary = summary?.slots.find((slot) => slot.id === selected);
  const heatSummary =
    summary &&
    summary.run_id === result?.run_id &&
    summary.start === range[0] &&
    summary.end === range[1]
      ? summary
      : null;
  const heatUrl =
    heatSummary && result
      ? `/api/runs/${result.run_id}/heatmap.png?start=${heatSummary.start}&end=${heatSummary.end}&palette=${palette}&v=${heatmapVersion}`
      : null;
  const run = project?.latest_run;
  const active = !!run && ["running", "queued"].includes(run.status);
  const sparse = meta?.kind === "sampled_timelapse";
  const visibleRows = useMemo(
    () =>
      (summary?.slots || []).filter((slot) =>
        `${slot.name} ${slot.id}`.toLowerCase().includes(filter.toLowerCase()),
      ),
    [summary, filter],
  );

  function seek(time: number) {
    if (video.current) video.current.currentTime = time;
    setSeconds(time);
  }
  async function togglePlay() {
    if (!video.current) return;
    if (video.current.paused) {
      try {
        await video.current.play();
      } catch (reason) {
        showError(reason);
      }
    } else video.current.pause();
  }
  async function analyze() {
    if (!project) return;
    setError("");
    setBusy("analysis");
    try {
      await request(`/api/projects/${project.id}/analyses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      await loadProject(project.id);
      setView("analysis");
    } catch (reason) {
      showError(reason);
    } finally {
      setBusy("");
    }
  }
  async function saveLayout() {
    if (!project) return;
    setBusy("layout");
    setError("");
    try {
      const next = await request<Project>(
        `/api/projects/${project.id}/layout`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slots }),
        },
      );
      setProject(next);
      setDirty(false);
      setHistory([]);
      setNotice("Разметка сохранена. Запустите анализ для этой версии мест.");
    } catch (reason) {
      showError(reason);
    } finally {
      setBusy("");
    }
  }
  function changeView(next: typeof view) {
    if (
      dirty &&
      next !== "editor" &&
      !window.confirm("Несохранённая разметка останется в редакторе. Перейти?")
    )
      return;
    video.current?.pause();
    setView(next);
  }
  async function chooseProject(id: string) {
    if (
      dirty &&
      !window.confirm(
        "Переключиться и отменить несохранённые изменения разметки?",
      )
    )
      return;
    setError("");
    setView("analysis");
    try {
      await loadProject(id, true);
    } catch (reason) {
      showError(reason);
    }
  }
  async function importDemo() {
    setBusy("demo");
    setError("");
    try {
      const p = await request<Project>("/api/examples/day", { method: "POST" });
      await reload();
      await loadProject(p.id, true);
    } catch (reason) {
      showError(reason);
    } finally {
      setBusy("");
    }
  }
  async function exportFile(format: string) {
    if (!result) return;
    setBusy(format);
    setError("");
    try {
      const response = await fetch(
        `/api/runs/${result.run_id}/export/${format}?start=${range[0]}&end=${range[1]}&palette=${palette}&opacity=${heatOpacity}&video_seconds=${seconds}&mode=${mode === "states" ? "states" : "heatmap"}`,
      );
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(detail.detail || "Ошибка экспорта");
      }
      const blob = await response.blob(),
        url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `parking-${format === "png" ? "heatmap" : format === "mp4" ? (mode === "states" ? "annotated" : "heatmap") : "statistics"}.${format}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Файл подготовлен и передан браузеру для сохранения.");
    } catch (reason) {
      showError(reason);
    } finally {
      setBusy("");
    }
  }
  function remember() {
    setHistory((previous) => [...previous.slice(-19), structuredClone(slots)]);
  }
  function svgPoint(event: React.PointerEvent | React.MouseEvent): Point {
    const box = svg.current!.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)),
      Math.max(0, Math.min(1, (event.clientY - box.top) / box.height)),
    ];
  }
  function finishPolygon() {
    if (draft.length < 3) return;
    remember();
    let n = slots.length + 1;
    while (slots.some((slot) => slot.id === `N${n}`)) n++;
    const id = `N${n}`;
    setSlots([...slots, { id, name: `Место ${n}`, points: draft }]);
    setSelected(id);
    setDraft([]);
    setDrawing(false);
    setDirty(true);
  }
  function removeSlot() {
    remember();
    setSlots(slots.filter((slot) => slot.id !== selected));
    setSelected(null);
    setDirty(true);
  }

  return (
    <>
      <header className="top-nav">
        <a className="wordmark" href="/" aria-label="Парковка — главная">
          <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="black" />
            <path
              d="M10 24V8h7a5 5 0 0 1 0 10h-7m0-5h7"
              fill="none"
              stroke="white"
              strokeWidth="2.5"
            />
          </svg>
          парковка<span className="wordmark-dot">.</span>
        </a>
        <nav aria-label="Разделы приложения">
          {(["analysis", "editor", "method"] as const).map((tab, i) => (
            <button
              key={tab}
              className={view === tab ? "nav-tab selected" : "nav-tab"}
              onClick={() => changeView(tab)}
              disabled={(!project && tab === "editor") || busy === "layout"}
            >
              {["Обзор", "Разметка", "Методика"][i]}
            </button>
          ))}
        </nav>
        <button
          className="button primary nav-upload"
          onClick={() => setUpload(true)}
        >
          <Plus size={18} />
          Новое видео
        </button>
      </header>
      <main>
        {error && (
          <div className="alert error" role="alert">
            <span>{error}</span>
            <button
              className="icon-button"
              onClick={() => setError("")}
              aria-label="Закрыть сообщение"
            >
              <X size={18} />
            </button>
          </div>
        )}
        {notice && (
          <div className="alert success" role="status">
            <Check size={18} />
            <span>{notice}</span>
            <button
              className="icon-button"
              onClick={() => setNotice("")}
              aria-label="Закрыть уведомление"
            >
              <X size={18} />
            </button>
          </div>
        )}
        {view === "method" ? (
          <section className="method-page">
            <h1>
              Что стоит
              <br />
              за цветом.
            </h1>
            <p className="lead">
              Карта показывает измеренную занятость мест, а не просто движение
              автомобилей.
            </p>
            <div className="method-grid">
              <article>
                <h2>Один день — целиком</h2>
                <p>
                  Пример CNRPark-EXT охватывает 16 ноября 2015 года, с 07:22 до
                  17:34. Это 10 часов 12 минут наблюдений с высокой неподвижной
                  камеры в Пизе.
                </p>
                <p>
                  Исходник — 21 реальный снимок с интервалами около 30 минут. Из
                  них собран компактный MP4: по две секунды на снимок. Переходы
                  между снимками не выдают себя за непрерывную съёмку.
                </p>
                <a href="http://cnrpark.it/" target="_blank" rel="noreferrer">
                  Источник и лицензия ODbL 1.0 <ArrowRight size={16} />
                </a>
              </article>
              <article>
                <h2>Две задачи, две модели</h2>
                <p>
                  mAlexNet определяет, занята ли выделенная область. Готовые
                  веса обучены на CNRPark A/B. YOLO11n и YOLO11s сначала находят
                  автомобили, затем сопоставляют рамки с выделенными местами.
                </p>
                <p>
                  Модель не получает эталонные ответы при анализе. Разметка
                  используется отдельно для проверки. Вы можете повторить анализ
                  любой из моделей.
                </p>
              </article>
            </div>
            <section className="method-formula">
              <h2>От синего к красному — от редкой занятости к высокой</h2>
              <p className="formula">
                Время занятости / время достоверного наблюдения × 100%
              </p>
              <p>
                Неопределённые состояния исключаются из знаменателя; покрытие
                наблюдения показывается рядом. Для редких снимков состояние
                между наблюдениями оценивается по последнему кадру. Моменты
                приезда и отъезда внутри такого интервала неизвестны.
              </p>
              <p>
                Мягкие пятна — визуальное обобщение значений соседних мест.
                Проезды за пределами размеченных областей не окрашиваются; места
                без определённых данных показаны серой штриховкой. Точный
                процент и покрытие доступны по нажатию на место. Палитра и
                непрозрачность меняют вид карты, а не результат модели.
              </p>
            </section>
            <div className="method-grid">
              <article>
                <h2>Уверенность — часть результата</h2>
                <p>
                  Вместо уверенного предположения модель может выдать «Не
                  определено». Эти места не считаются свободными. Для
                  непрерывного видео дополнительно применяется подтверждение
                  смены состояния во времени.
                </p>
                {validation?.test && (
                  <p className="validation-note">
                    Сохранённая проверка на другой дате: F1{" "}
                    {validation.test.f1.toFixed(3)}, покрытие{" "}
                    {percent(validation.test.coverage * 100)},{" "}
                    {validation.test.total} сравнений с эталоном. Подробности —
                    в отчёте проекта.
                  </p>
                )}
              </article>
              <article>
                <h2>Ваше видео</h2>
                <p>
                  Нужна неподвижная камера, видимые места и известная шкала
                  времени. Для заранее ускоренного ролика укажите исходный
                  коэффициент ускорения. Нельзя восстановить часы съёмки из
                  ролика с неизвестным ускорением.
                </p>
                <p>
                  Результаты зависят от ракурса, освещения, перекрытий и
                  выбранной модели. Точность демонстрационного примера не
                  гарантирует ту же точность на новой парковке.
                </p>
              </article>
            </div>
          </section>
        ) : !project ? (
          <section className="empty-page">
            <h1>
              Весь день.
              <br />
              На одной карте.
            </h1>
            <p className="lead">
              Загрузите запись парковки или начните с реального рабочего дня в
              Пизе.
            </p>
            <div className="empty-actions">
              <button
                className="button primary"
                onClick={() => setUpload(true)}
              >
                <Upload size={18} />
                Загрузить видео
              </button>
              <button
                className="button secondary"
                onClick={importDemo}
                disabled={!!busy}
              >
                {busy === "demo" ? "Открываем…" : "Открыть пример · 10 часов"}
              </button>
              <button
                className="text-button"
                onClick={() => void reload().catch(showError)}
              >
                Обновить список
              </button>
            </div>
          </section>
        ) : (
          <>
            <section
              className={`page-heading ${view === "analysis" ? "analysis-heading" : ""}`}
            >
              <div>
                <h1>
                  {view === "editor" ? (
                    <>
                      Каждому месту —<br />
                      свои границы.
                    </>
                  ) : (
                    <>Тепловая карта занятости</>
                  )}
                </h1>
                <p>
                  {view === "editor"
                    ? "Выделите области мест. Разметка сохраняется для этого ракурса."
                    : "Доля занятого времени среди известных интервалов."}
                </p>
              </div>
              <div className="project-picker">
                <label htmlFor="project">Исследование</label>
                <div className="select-wrap">
                  <select
                    id="project"
                    value={project.id}
                    onChange={(event) => void chooseProject(event.target.value)}
                  >
                    {projects.map((p) => (
                      <option value={p.id} key={p.id}>
                        {p.title}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={16} />
                </div>
                <span>{meta?.source_name}</span>
              </div>
            </section>
            <section
              className={`workspace ${view === "analysis" && result ? "analysis-workspace" : ""}`}
            >
              <div className="video-column">
                <div className="video-toolbar">
                  {view === "editor" ? (
                    <>
                      <span className="toolbar-title">{slots.length} мест</span>
                      <div className="toolbar-actions">
                        <button
                          className="button small secondary"
                          onClick={() => {
                            setDrawing(true);
                            setDraft([]);
                            setSelected(null);
                          }}
                        >
                          <Plus size={15} />
                          Добавить
                        </button>
                        <button
                          className="icon-button"
                          disabled={!history.length}
                          aria-label="Отменить изменение"
                          onClick={() => {
                            setSlots(history[history.length - 1]);
                            setHistory(history.slice(0, -1));
                            setDirty(true);
                          }}
                        >
                          <RotateCcw size={17} />
                        </button>
                        <button
                          className="icon-button"
                          disabled={!selected}
                          aria-label="Удалить выбранное место"
                          onClick={removeSlot}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="segmented" aria-label="Слой на видео">
                        {(["video", "states", "heatmap"] as const).map(
                          (tab, i) => (
                            <button
                              key={tab}
                              className={mode === tab ? "selected" : ""}
                              onClick={() => setMode(tab)}
                            >
                              {["Видео", "Занятость", "Тепловая карта"][i]}
                            </button>
                          ),
                        )}
                      </div>
                      {mode === "heatmap" && (
                        <div className="heat-controls">
                          <select
                            aria-label="Палитра карты"
                            value={palette}
                            onChange={(event) =>
                              setPalette(
                                event.target.value === "warm"
                                  ? "warm"
                                  : "thermal",
                              )
                            }
                          >
                            {Object.entries(palettes).map(([key, value]) => (
                              <option key={key} value={key}>
                                {value.label}
                              </option>
                            ))}
                          </select>
                          <label className="heat-opacity">
                            Непрозрачность
                            <input
                              aria-label="Непрозрачность карты"
                              type="range"
                              min="0"
                              max="1"
                              step="0.05"
                              value={heatOpacity}
                              onChange={(event) =>
                                setHeatOpacity(Number(event.target.value))
                              }
                            />
                            <output>{Math.round(heatOpacity * 100)}%</output>
                          </label>
                        </div>
                      )}
                      <button
                        className="icon-button fullscreen"
                        aria-label="Развернуть видео"
                        onClick={() => {
                          void stage.current
                            ?.requestFullscreen()
                            .catch(showError);
                        }}
                      >
                        <Expand size={18} />
                      </button>
                    </>
                  )}
                </div>
                <div
                  ref={stage}
                  className={`video-stage ${drawing ? "drawing" : ""}`}
                  tabIndex={view === "editor" ? 0 : -1}
                  aria-label={
                    view === "editor"
                      ? "Редактор парковочных мест: кликайте вершины, Enter завершает, Escape отменяет"
                      : undefined
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && drawing) {
                      event.preventDefault();
                      finishPolygon();
                    }
                    if (event.key === "Escape") {
                      setDraft([]);
                      setDrawing(false);
                    }
                  }}
                >
                  <button
                    className="icon-button fullscreen-exit"
                    aria-label="Свернуть видео"
                    onClick={() => {
                      void document.exitFullscreen().catch(showError);
                    }}
                  >
                    <X size={20} />
                  </button>
                  <div
                    className={`video-plane ${view === "analysis" && mode === "heatmap" ? "with-heatmap" : ""}`}
                    style={
                      {
                        "--media-ratio": meta!.width / meta!.height,
                        "--heatmap-video-saturation":
                          heatmapRender.videoSaturation,
                        aspectRatio: `${meta!.width}/${meta!.height}`,
                      } as CSSProperties & {
                        "--media-ratio": number;
                        "--heatmap-video-saturation": number;
                      }
                    }
                  >
                    {view === "editor" ? (
                      <img
                        src={`/api/projects/${project.id}/poster`}
                        alt="Кадр парковки для разметки"
                      />
                    ) : (
                      <video
                        ref={video}
                        key={project.id}
                        src={`/api/projects/${project.id}/video`}
                        poster={`/api/projects/${project.id}/poster?first=true`}
                        playsInline
                        preload="metadata"
                        onTimeUpdate={(event) =>
                          setSeconds(event.currentTarget.currentTime)
                        }
                        onPlay={() => setPlaying(true)}
                        onPause={() => setPlaying(false)}
                        onEnded={() => setPlaying(false)}
                        aria-label="Видео парковки"
                      />
                    )}
                    {view === "analysis" && mode === "heatmap" && (
                      <>
                        <span className="frame-time-chip">
                          Кадр · {clock(sourceSeconds, meta!.capture_start)}
                        </span>
                        {result ? (
                          <HeatmapLayer
                            url={heatUrl}
                            slots={heatSummary?.slots || []}
                            width={meta!.width}
                            height={meta!.height}
                            opacity={heatOpacity}
                            selected={selected}
                            onSelect={setSelected}
                          />
                        ) : (
                          <div className="heat-layer-status">
                            Разметьте места и запустите анализ, чтобы построить
                            карту.
                          </div>
                        )}
                      </>
                    )}
                    {(view === "editor" || mode === "states") && (
                      <svg
                        ref={svg}
                        className="parking-overlay"
                        viewBox={`0 0 ${meta!.width} ${meta!.height}`}
                        onClick={(event) => {
                          if (drawing && draft.length < 16)
                            setDraft([...draft, svgPoint(event)]);
                        }}
                        onPointerMove={(event) => {
                          const drag = dragging.current;
                          if (!drag) return;
                          const point = svgPoint(event);
                          setSlots((current) =>
                            current.map((slot) =>
                              slot.id === drag.slot
                                ? {
                                    ...slot,
                                    points: slot.points.map((p, i) =>
                                      i === drag.point ? point : p,
                                    ),
                                  }
                                : slot,
                            ),
                          );
                          setDirty(true);
                        }}
                        onPointerUp={() => {
                          dragging.current = null;
                        }}
                        onPointerCancel={() => {
                          dragging.current = null;
                        }}
                      >
                        {displayedSlots.map((slot, col) => {
                          const state = sample?.states[col],
                            slotPoints = slot.points;
                          const fill =
                            view === "editor"
                              ? selected === slot.id
                                ? "#c5b0f4"
                                : "#ffffff"
                              : state === 1
                                ? "#f3c9b6"
                                : state === 0
                                  ? "#c8e6cd"
                                  : "#e6e6e6";
                          const x =
                              (slot.points.reduce((a, p) => a + p[0], 0) /
                                slot.points.length) *
                              meta!.width,
                            y =
                              (slot.points.reduce((a, p) => a + p[1], 0) /
                                slot.points.length) *
                              meta!.height;
                          return (
                            <g
                              key={slot.id}
                              className={
                                selected === slot.id
                                  ? "slot-group active"
                                  : "slot-group"
                              }
                              onClick={(event) => {
                                if (!drawing) {
                                  event.stopPropagation();
                                  setSelected(slot.id);
                                }
                              }}
                            >
                              <title>
                                {slot.name}:{" "}
                                {view === "editor"
                                  ? "область наблюдения"
                                  : stateLabel(state)}
                              </title>
                              <polygon
                                points={slotPoints
                                  .map(
                                    (p) =>
                                      `${p[0] * meta!.width},${p[1] * meta!.height}`,
                                  )
                                  .join(" ")}
                                fill={fill}
                                fillOpacity={view === "editor" ? 0.25 : 0.62}
                                stroke={selected === slot.id ? "#000" : "#fff"}
                                strokeWidth={selected === slot.id ? 3 : 1.3}
                              />
                              <rect
                                x={x - 14}
                                y={y - 8}
                                width={28}
                                height={16}
                                rx={3}
                                fill="#ffffff"
                              />
                              <text
                                x={x}
                                y={y + 3}
                                textAnchor="middle"
                                fill="#000000"
                              >
                                {slot.id}
                              </text>
                              {view === "editor" &&
                                selected === slot.id &&
                                slot.points.map((p, vertex) => (
                                  <circle
                                    key={vertex}
                                    cx={p[0] * meta!.width}
                                    cy={p[1] * meta!.height}
                                    r={5}
                                    fill="black"
                                    stroke="white"
                                    strokeWidth={2}
                                    onPointerDown={(event) => {
                                      event.preventDefault();
                                      event.stopPropagation();
                                      remember();
                                      dragging.current = {
                                        slot: slot.id,
                                        point: vertex,
                                      };
                                      event.currentTarget.setPointerCapture(
                                        event.pointerId,
                                      );
                                    }}
                                  />
                                ))}
                            </g>
                          );
                        })}
                        {draft.length > 0 && (
                          <>
                            <polyline
                              points={draft
                                .map(
                                  (p) =>
                                    `${p[0] * meta!.width},${p[1] * meta!.height}`,
                                )
                                .join(" ")}
                              stroke="black"
                              strokeWidth={3}
                              fill="#c5b0f4"
                              fillOpacity={0.4}
                            />
                            {draft.map((p, i) => (
                              <circle
                                key={i}
                                cx={p[0] * meta!.width}
                                cy={p[1] * meta!.height}
                                r={5}
                                fill="black"
                              />
                            ))}
                          </>
                        )}
                      </svg>
                    )}
                  </div>
                </div>
                {view === "editor" ? (
                  <div className="editor-footer">
                    {drawing ? (
                      <>
                        <span>
                          {draft.length} вершин · Enter завершает полигон
                        </span>
                        <button
                          className="button small primary"
                          onClick={finishPolygon}
                          disabled={draft.length < 3}
                        >
                          Замкнуть место
                        </button>
                        <button
                          className="text-button"
                          onClick={() => {
                            setDrawing(false);
                            setDraft([]);
                          }}
                        >
                          Отмена
                        </button>
                      </>
                    ) : (
                      <>
                        <span>
                          Нажмите на место, чтобы переместить его вершины.
                        </span>
                        <a
                          className="text-button"
                          href={`/api/projects/${project.id}/layout/export`}
                        >
                          Скачать разметку
                        </a>
                      </>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="playback">
                      <button
                        className="icon-button"
                        aria-label={playing ? "Пауза" : "Воспроизвести"}
                        onClick={() => void togglePlay()}
                      >
                        {playing ? <Pause size={19} /> : <Play size={19} />}
                      </button>
                      <input
                        aria-label="Позиция видео"
                        type="range"
                        min={0}
                        max={meta!.video_duration_seconds}
                        step={0.01}
                        value={seconds}
                        onChange={(event) => seek(Number(event.target.value))}
                      />
                      <span className="playback-time">
                        {clock(sourceSeconds, meta!.capture_start)}
                      </span>
                      <select
                        aria-label="Скорость воспроизведения"
                        defaultValue="1"
                        onChange={(event) => {
                          if (video.current)
                            video.current.playbackRate = Number(
                              event.target.value,
                            );
                        }}
                      >
                        <option value="0.5">0,5×</option>
                        <option value="1">1×</option>
                        <option value="2">2×</option>
                      </select>
                    </div>
                    <div
                      className={`legend ${mode === "heatmap" ? "thermal-legend-wrap" : ""}`}
                    >
                      {mode === "heatmap" ? (
                        <div className="thermal-legend">
                          <span>Редко занято</span>
                          <div className="thermal-scale">
                            <div
                              className="heat-scale"
                              style={{ background: heatGradient(palette) }}
                            />
                            <div className="thermal-ticks">
                              {[0, 25, 50, 75, 100].map((n) => (
                                <span key={n}>{n}%</span>
                              ))}
                            </div>
                          </div>
                          <span>Почти всегда занято</span>
                          <span className="unknown-legend">
                            <i />
                            Нет определённых данных
                          </span>
                        </div>
                      ) : (
                        <>
                          <span>
                            <i className="dot free" />
                            Свободно
                          </span>
                          <span>
                            <i className="dot occupied" />
                            Занято
                          </span>
                          <span>
                            <i className="dot unknown" />
                            Не определено
                          </span>
                        </>
                      )}
                      <span className="legend-tail">
                        {sparse
                          ? "Реальные снимки · шаг ≈ 30 мин"
                          : "Неподвижная камера"}
                      </span>
                    </div>
                    {mode === "heatmap" && (
                      <p className="heat-period">
                        Период карты: {clock(range[0], meta!.capture_start)} —{" "}
                        {clock(range[1], meta!.capture_start)} · Нажмите на
                        место для точных значений.
                      </p>
                    )}
                  </>
                )}
              </div>
              <aside className="inspector">
                <div className="observation-panel">
                  <div className="panel-top">
                    <span>Период наблюдения</span>
                    <Layers size={20} />
                  </div>
                  <strong className="observation-duration">
                    {duration(
                      result?.source_duration_seconds ||
                        meta!.source_duration_seconds,
                    )}
                  </strong>
                  <p>
                    {meta!.capture_start
                      ? `${clock(0, meta!.capture_start)} — ${clock(meta!.source_duration_seconds, meta!.capture_start)}`
                      : "От начала исходной записи"}
                    <br />
                    {sparse
                      ? `${meta!.sample_count} исходных кадров · ${duration(meta!.video_duration_seconds)} видео`
                      : `${duration(meta!.video_duration_seconds)} видео · масштаб ${result?.settings.time_scale || settings.time_scale}×`}
                  </p>
                  <div className="panel-bottom">
                    <span>{displayedSlots.length} парковочных мест</span>
                    <span className="local-tag">Локально</span>
                  </div>
                </div>
                {view === "editor" ? (
                  <div className="configuration">
                    <h2>Разметка мест</h2>
                    <p>
                      Для классификатора выделяйте область, в которой находится
                      автомобиль. Сохраните изменения перед анализом.
                    </p>
                    {selectedIndex >= 0 && (
                      <label>
                        Название места
                        <input
                          value={slots[selectedIndex]?.name || ""}
                          onFocus={remember}
                          onChange={(event) => {
                            const name = event.target.value;
                            setSlots(
                              slots.map((slot) =>
                                slot.id === selected ? { ...slot, name } : slot,
                              ),
                            );
                            setDirty(true);
                          }}
                          maxLength={50}
                        />
                      </label>
                    )}
                    <button
                      className="button primary full"
                      onClick={() => void saveLayout()}
                      disabled={!dirty || !!busy}
                    >
                      {busy === "layout"
                        ? "Сохраняем…"
                        : dirty
                          ? "Сохранить разметку"
                          : "Изменения сохранены"}
                      <Check size={18} />
                    </button>
                    <div className="slot-list">
                      {slots.map((slot) => (
                        <button
                          className={selected === slot.id ? "selected" : ""}
                          key={slot.id}
                          onClick={() => setSelected(slot.id)}
                        >
                          <span>{slot.name}</span>
                          <span>{slot.id}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <>
                    {sample && (
                      <div className="frame-summary">
                        <p>
                          На кадре {clock(sourceSeconds, meta!.capture_start)}
                        </p>
                        <div className="live-counts">
                          <div>
                            <strong>
                              {sample.states.filter((s) => s === 1).length}
                            </strong>
                            <span>
                              <i className="dot occupied" />
                              Занято
                            </span>
                          </div>
                          <div>
                            <strong>
                              {sample.states.filter((s) => s === 0).length}
                            </strong>
                            <span>
                              <i className="dot free" />
                              Свободно
                            </span>
                          </div>
                          <div>
                            <strong>
                              {sample.states.filter((s) => s === -1).length}
                            </strong>
                            <span>
                              <i className="dot unknown" />
                              Неясно
                            </span>
                          </div>
                        </div>
                      </div>
                    )}
                    {mode !== "heatmap" &&
                      selected &&
                      selectedIndex >= 0 &&
                      sample && (
                        <div className="selected-slot">
                          <button
                            className="icon-button"
                            aria-label="Снять выделение"
                            onClick={() => setSelected(null)}
                          >
                            <X size={15} />
                          </button>
                          <strong>{displayedSlots[selectedIndex]?.name}</strong>
                          <p>
                            {stateLabel(sample.states[selectedIndex])} · среди
                            известных интервалов{" "}
                            {percent(selectedSummary?.occupancy)}
                          </p>
                        </div>
                      )}
                    <div className="configuration">
                      <h2>
                        {result ? "Повторить исследование" : "Начнём с анализа"}
                      </h2>
                      <label>
                        Модель
                        <div className="select-wrap">
                          <select
                            aria-label="Модель"
                            value={settings.model}
                            disabled={active}
                            onChange={(event) => {
                              const model = event.target
                                .value as Settings["model"];
                              setSettings({
                                ...settings,
                                model,
                                confidence: model === "malexnet" ? 0.7 : 0.25,
                              });
                            }}
                          >
                            <option value="malexnet">
                              mAlexNet · занятость мест
                            </option>
                            <option value="yolo11n">
                              YOLO11n · автомобили
                            </option>
                            <option value="yolo11s">
                              YOLO11s · автомобили
                            </option>
                          </select>
                          <ChevronDown size={16} />
                        </div>
                      </label>
                      <label className="confidence-label">
                        Порог уверенности{" "}
                        <strong>{percent(settings.confidence * 100)}</strong>
                        <input
                          type="range"
                          min={settings.model === "malexnet" ? 0.5 : 0.2}
                          max={0.95}
                          step={0.05}
                          value={settings.confidence}
                          onChange={(event) =>
                            setSettings({
                              ...settings,
                              confidence: Number(event.target.value),
                            })
                          }
                          disabled={active}
                        />
                      </label>
                      {!sparse && (
                        <div className="settings-row">
                          <label>
                            Кадр каждые, с
                            <input
                              type="number"
                              min={0.25}
                              max={120}
                              step={0.25}
                              value={settings.sample_seconds}
                              disabled={active}
                              onChange={(event) =>
                                setSettings({
                                  ...settings,
                                  sample_seconds: Number(event.target.value),
                                })
                              }
                            />
                          </label>
                          <label>
                            Ускорение исходника
                            <input
                              type="number"
                              min={1}
                              max={10000}
                              value={settings.time_scale}
                              disabled={active}
                              onChange={(event) =>
                                setSettings({
                                  ...settings,
                                  time_scale: Number(event.target.value),
                                })
                              }
                            />
                          </label>
                        </div>
                      )}
                      {active ? (
                        <div className="processing" role="status">
                          <div>
                            <LoaderCircle className="spin" size={17} />
                            <span>{run!.stage}</span>
                          </div>
                          <progress value={run!.progress} max={100} />
                          <div>
                            <strong>{Math.round(run!.progress)}%</strong>
                            <button
                              className="text-button"
                              disabled={!!run!.stage.includes("Останавливаем")}
                              onClick={() => {
                                void request(`/api/runs/${run!.id}/cancel`, {
                                  method: "POST",
                                })
                                  .then(() => loadProject(project.id))
                                  .catch(showError);
                              }}
                            >
                              Отменить
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          className="button primary full"
                          onClick={() => void analyze()}
                          disabled={!!busy || project.slots.length === 0}
                        >
                          {busy === "analysis"
                            ? "Запускаем…"
                            : "Рассчитать карту"}
                          <ArrowRight size={19} />
                        </button>
                      )}
                      {!project.slots.length && (
                        <button
                          className="text-button"
                          onClick={() => changeView("editor")}
                        >
                          Сначала разметить места <ArrowRight size={16} />
                        </button>
                      )}
                      {run?.error && (
                        <p className="form-error" role="alert">
                          {run.error}
                        </p>
                      )}
                      {result && result.revision !== project.revision && (
                        <p className="form-error">
                          Разметка изменена. Показаны результаты версии{" "}
                          {result.revision}; запустите новый анализ.
                        </p>
                      )}
                      <p className="model-note">
                        {settings.model === "malexnet"
                          ? "Классификатор оценивает каждую выделенную область. Сомнительные ответы отмечаются отдельно."
                          : "YOLO находит автомобили. На мелких и перекрытых местах возможны пропуски."}
                      </p>
                    </div>
                  </>
                )}
              </aside>
            </section>
            {view === "analysis" &&
              (result && summary ? (
                <>
                  <section className="results-heading">
                    <div>
                      <h2>День в цифрах</h2>
                      <p>
                        {clock(range[0], meta!.capture_start)} —{" "}
                        {clock(range[1], meta!.capture_start)} · {result.model}
                      </p>
                    </div>
                    <div className="export-actions">
                      <button
                        className="button secondary small"
                        disabled={!!busy}
                        onClick={() => void exportFile("png")}
                      >
                        <ArrowDownToLine size={16} />
                        {busy === "png" ? "Готовим…" : "Карта PNG"}
                      </button>
                      <button
                        className="button secondary small"
                        disabled={!!busy}
                        onClick={() => void exportFile("csv")}
                      >
                        <ArrowDownToLine size={16} />
                        CSV
                      </button>
                      <button
                        className="button secondary small"
                        disabled={!!busy}
                        onClick={() => void exportFile("mp4")}
                      >
                        <ArrowDownToLine size={16} />
                        {busy === "mp4" ? "Готовим видео…" : "Видео MP4"}
                      </button>
                    </div>
                  </section>
                  <div className="summary-strip">
                    <div>
                      <span>Средняя занятость</span>
                      <strong>{percent(summary.occupancy)}</strong>
                      <small>среди определённых состояний</small>
                    </div>
                    <div>
                      <span>Пик загрузки</span>
                      <strong>
                        {summary.peak_occupied}
                        <small> / {result.slots.length}</small>
                      </strong>
                      <small>одновременно занятых мест</small>
                    </div>
                    <div>
                      <span>Покрытие наблюдения</span>
                      <strong>{percent(summary.coverage)}</strong>
                      <small>остальное — неопределённость</small>
                    </div>
                    <div>
                      <span>Смены состояния</span>
                      <strong>{summary.changes}</strong>
                      <small>между исходными кадрами</small>
                    </div>
                  </div>
                  <section className="range-section">
                    <div>
                      <h3>Интервал исследования</h3>
                      <button
                        className="text-button"
                        onClick={() =>
                          setRange([0, result.source_duration_seconds])
                        }
                      >
                        Весь день <RotateCcw size={14} />
                      </button>
                    </div>
                    <div className="range-controls">
                      <label>
                        С {clock(range[0], meta!.capture_start)}
                        <input
                          aria-label="Начало интервала"
                          type="range"
                          min={0}
                          max={result.source_duration_seconds}
                          step={sparse ? 60 : 1}
                          value={range[0]}
                          onChange={(event) =>
                            setRange([
                              Math.min(
                                Number(event.target.value),
                                range[1] - 1,
                              ),
                              range[1],
                            ])
                          }
                        />
                      </label>
                      <label>
                        До {clock(range[1], meta!.capture_start)}
                        <input
                          aria-label="Конец интервала"
                          type="range"
                          min={0}
                          max={result.source_duration_seconds}
                          step={sparse ? 60 : 1}
                          value={range[1]}
                          onChange={(event) =>
                            setRange([
                              range[0],
                              Math.max(
                                Number(event.target.value),
                                range[0] + 1,
                              ),
                            ])
                          }
                        />
                      </label>
                    </div>
                  </section>
                  <section className="chart-section">
                    <div className="section-title">
                      <h3>Как менялась загрузка</h3>
                      <span>
                        <i className="dot ink" />
                        Занятые места
                      </span>
                    </div>
                    <div className="chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={summary.timeline}
                          margin={{ top: 16, right: 14, bottom: 0, left: -18 }}
                        >
                          <CartesianGrid vertical={false} stroke="#e6e6e6" />
                          <XAxis
                            dataKey="time"
                            tickFormatter={(time) =>
                              clock(Number(time), meta!.capture_start)
                            }
                            tickLine={false}
                            axisLine={false}
                            minTickGap={32}
                            tick={{ fill: "#000", fontSize: 12 }}
                          />
                          <YAxis
                            allowDecimals={false}
                            domain={[0, result.slots.length]}
                            tickLine={false}
                            axisLine={false}
                            tick={{ fill: "#000", fontSize: 12 }}
                          />
                          <Tooltip
                            labelFormatter={(time) =>
                              clock(Number(time), meta!.capture_start)
                            }
                            formatter={(value) => [value, "Занято мест"]}
                            contentStyle={{
                              border: "1px solid #e6e6e6",
                              borderRadius: 8,
                              color: "#000",
                            }}
                          />
                          <Area
                            type="stepAfter"
                            dataKey="occupied"
                            stroke="#000000"
                            strokeWidth={2}
                            fill="#f28b3c"
                            fillOpacity={0.48}
                            isAnimationActive={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </section>
                  <section className="matrix-section">
                    <div className="section-title">
                      <div>
                        <h3>У каждого места — своя история</h3>
                        <p>
                          Строка — место. Столбец — реальный момент наблюдения.
                          Нажмите на ячейку, чтобы открыть кадр.
                        </p>
                      </div>
                      <div className="matrix-key">
                        <span>Свободно</span>
                        <i className="dot free" />
                        <i className="dot occupied" />
                        <span>Занято</span>
                      </div>
                    </div>
                    <div className="matrix-scroll">
                      <div
                        className="matrix"
                        style={{
                          gridTemplateColumns: `80px repeat(${result.samples.length}, minmax(20px, 1fr))`,
                        }}
                      >
                        <span className="matrix-corner">Место</span>
                        {result.samples.map((s, i) => (
                          <span className="matrix-time" key={i}>
                            {i % 3 === 0
                              ? clock(s.source_seconds, meta!.capture_start)
                              : ""}
                          </span>
                        ))}
                        {result.slots.map((slot, col) => (
                          <div
                            className={`matrix-row ${selected === slot.id ? "selected" : ""}`}
                            key={slot.id}
                          >
                            <button
                              className="matrix-label"
                              onClick={() => setSelected(slot.id)}
                            >
                              {slot.id}
                            </button>
                            {result.samples.map((s, i) => (
                              <button
                                key={i}
                                className={`matrix-cell ${stateClass(s.states[col])} ${i === index ? "current" : ""}`}
                                data-cell={`${col}-${i}`}
                                tabIndex={
                                  (selected === slot.id ||
                                    (!selected && col === 0)) &&
                                  i === index
                                    ? 0
                                    : -1
                                }
                                onKeyDown={(event) => {
                                  const delta: Record<
                                    string,
                                    [number, number]
                                  > = {
                                    ArrowLeft: [0, -1],
                                    ArrowRight: [0, 1],
                                    ArrowUp: [-1, 0],
                                    ArrowDown: [1, 0],
                                  };
                                  if (!delta[event.key]) return;
                                  event.preventDefault();
                                  const [dc, di] = delta[event.key];
                                  const nextRow = Math.max(
                                    0,
                                    Math.min(result.slots.length - 1, col + dc),
                                  );
                                  const nextSample = Math.max(
                                    0,
                                    Math.min(result.samples.length - 1, i + di),
                                  );
                                  setSelected(result.slots[nextRow].id);
                                  seek(
                                    result.samples[nextSample].video_seconds,
                                  );
                                  event.currentTarget
                                    .closest(".matrix")
                                    ?.querySelector<HTMLButtonElement>(
                                      `[data-cell="${nextRow}-${nextSample}"]`,
                                    )
                                    ?.focus();
                                }}
                                aria-label={`Место ${slot.id}, ${clock(s.source_seconds, meta!.capture_start)}, ${stateLabel(s.states[col])}`}
                                title={`${clock(s.source_seconds, meta!.capture_start)} · ${stateLabel(s.states[col])}`}
                                onClick={() => {
                                  setSelected(slot.id);
                                  seek(s.video_seconds);
                                }}
                              />
                            ))}
                          </div>
                        ))}
                      </div>
                    </div>
                  </section>
                  <section className="table-section">
                    <div className="section-title">
                      <h3>По каждому месту</h3>
                      <input
                        className="search-input"
                        aria-label="Поиск места"
                        placeholder="Найти место…"
                        value={filter}
                        onChange={(event) => setFilter(event.target.value)}
                      />
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Место</th>
                            <th>Занятость</th>
                            <th>Наблюдение</th>
                            <th>Время занятости*</th>
                            <th>Смены</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleRows.map((slot) => (
                            <tr
                              key={slot.id}
                              className={selected === slot.id ? "selected" : ""}
                            >
                              <td>
                                <button
                                  className="text-button"
                                  onClick={() => setSelected(slot.id)}
                                >
                                  {slot.name}
                                </button>
                              </td>
                              <td>
                                <span className="occupancy-cell">
                                  <i
                                    style={{
                                      background: heatColor(
                                        slot.occupancy,
                                        palette,
                                      ),
                                    }}
                                  />
                                  {percent(slot.occupancy)}
                                </span>
                              </td>
                              <td>{percent(slot.coverage)}</td>
                              <td>{duration(slot.occupied_seconds)}</td>
                              <td>{slot.changes}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {visibleRows.length === 0 && (
                        <p className="table-empty">
                          Такого места нет. Измените поиск.
                        </p>
                      )}
                    </div>
                    <p className="table-footnote">
                      *{" "}
                      {sparse
                        ? "Оценка между редкими снимками, а не точная длительность парковки."
                        : "Наблюдаемая занятость в пределах записи, а не полная длительность визита."}{" "}
                      Неопределённые интервалы исключены.
                    </p>
                  </section>
                  <div className="source-note">
                    <CircleHelp size={23} />
                    <div>
                      <h3>У данных есть границы</h3>
                      <p>{result.notice}</p>
                      <button
                        className="text-button"
                        onClick={() => changeView("method")}
                      >
                        Как устроен расчёт <ArrowRight size={16} />
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <section className="before-analysis">
                  <div>
                    <h2>От записи — к пониманию.</h2>
                    <p>
                      После анализа здесь появятся график загрузки, тепловая
                      матрица и статистика каждого места.
                    </p>
                  </div>
                  <ArrowRight size={35} strokeWidth={1.3} />
                </section>
              ))}
          </>
        )}
      </main>
      <footer>
        <span>парковка.</span>
        <p>Компьютерное зрение. Реальные наблюдения.</p>
        <span>Учебное исследование · 2026</span>
      </footer>
      {upload && (
        <UploadDialog
          onClose={() => setUpload(false)}
          onUploaded={(next) => {
            setUpload(false);
            setProjects((current) => [next, ...current]);
            void loadProject(next.id, true)
              .then(() => setView("editor"))
              .catch(showError);
          }}
        />
      )}
    </>
  );
}
