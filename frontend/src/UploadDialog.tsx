import { useEffect, useRef, useState } from "react";
import { Upload, X } from "lucide-react";
import { request } from "./utils";
import type { Project } from "./types";

export default function UploadDialog({
  onClose,
  onUploaded,
}: {
  onClose: () => void;
  onUploaded: (project: Project) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("Моя парковка");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Выберите видеофайл.");
      return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setError("Файл превышает 500 МБ. Подготовьте компактную версию.");
      return;
    }
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    try {
      onUploaded(
        await request<Project>("/api/projects/upload", {
          method: "POST",
          body: form,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось загрузить видео.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="upload-dialog"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      aria-labelledby="upload-title"
    >
      <button
        className="icon-button dialog-close"
        aria-label="Закрыть окно"
        disabled={busy}
        onClick={onClose}
      >
        <X size={20} />
      </button>
      <h2 id="upload-title">
        Ваша парковка.
        <br />
        Ваши данные.
      </h2>
      <p>
        Видео неподвижной камеры, снятое сверху или под углом. После загрузки
        выделите парковочные места.
      </p>
      <form onSubmit={submit}>
        <label>
          Название
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={100}
            disabled={busy}
          />
        </label>
        <label className="file-drop">
          <Upload size={30} />
          <strong>{file ? file.name : "Выберите видео"}</strong>
          <span>MP4, MOV, AVI, MKV · до 500 МБ</span>
          <input
            aria-label="Видеофайл"
            type="file"
            accept="video/*,.mkv"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            disabled={busy}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {busy && (
          <p role="status">
            Загружаем и подготавливаем видео. Для длинной записи это может
            занять несколько минут.
          </p>
        )}
        <button
          type="submit"
          className="button primary"
          disabled={busy || !file}
        >
          {busy ? "Подготовка видео…" : "Загрузить и разметить"}
        </button>
      </form>
    </dialog>
  );
}
