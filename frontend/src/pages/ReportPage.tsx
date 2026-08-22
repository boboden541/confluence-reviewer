import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Markdown from "../Markdown";
import {
  api,
  ApiError,
  type DocumentListItem,
  type ValidationReport,
} from "../api";

const STATUS_LABELS: Record<string, string> = {
  not_checked: "не проверено",
  in_progress: "проверяется",
  passed: "пройдено",
  failed: "не пройдено",
  error: "ошибка",
};

interface Note {
  document_id: number;
  content: string;
  created_at: string | null;
  updated_at: string | null;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

export default function ReportPage() {
  const { documentId } = useParams();
  const [doc, setDoc] = useState<DocumentListItem | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [note, setNote] = useState("");
  const [noteOriginal, setNoteOriginal] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!documentId) return;
    try {
      const documentResp = await api<
        DocumentListItem & { content_html: string; sync_error: string | null }
      >(`/api/documents/${documentId}`);
      setDoc(documentResp);
      setReport(
        await api<ValidationReport>(`/api/documents/${documentId}/report`).catch(
          () => null,
        ),
      );
      const noteResp = await api<Note>(`/api/documents/${documentId}/note`);
      setNote(noteResp.content);
      setNoteOriginal(noteResp.content);
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить документ");
    }
  }, [documentId]);

  useEffect(() => {
    load();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  const runValidation = async (force: boolean) => {
    if (!documentId) return;
    setBusy(true);
    setInfo("Проверка запущена…");
    setError("");
    try {
      await api(`/api/documents/${documentId}/validate${force ? "?force=true" : ""}`, {
        method: "POST",
      });
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const current = await api<
          DocumentListItem & { content_html: string; sync_error: string | null }
        >(`/api/documents/${documentId}`);
        setDoc(current);
        if (current.validation_status !== "in_progress") {
          if (timer.current) clearInterval(timer.current);
          timer.current = null;
          setBusy(false);
          setInfo("");
          await load();
        }
      }, 1500);
    } catch (exc) {
      setBusy(false);
      setInfo("");
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить проверку");
    }
  };

  const sendComment = async () => {
    if (!documentId) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<ValidationReport>(
        `/api/documents/${documentId}/comment`,
        { method: "POST" },
      );
      setReport(updated);
      setInfo("Замечания опубликованы комментарием на странице Confluence");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось отправить комментарий");
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!documentId) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/documents/${documentId}/note`, {
        method: "PUT",
        body: JSON.stringify({ content: note }),
      });
      setNoteOriginal(note);
      setInfo("Заметка сохранена");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить заметку");
    } finally {
      setBusy(false);
    }
  };

  const deleteNote = async () => {
    if (!documentId) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/documents/${documentId}/note`, { method: "DELETE" });
      setNote("");
      setNoteOriginal("");
      setInfo("Заметка удалена");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить заметку");
    } finally {
      setBusy(false);
    }
  };

  // Несохранённая заметка не должна молча пропасть при закрытии вкладки
  useEffect(() => {
    if (note === noteOriginal) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [note, noteOriginal]);

  if (!doc) {
    return (
      <section>
        {error ? <div className="alert error">{error}</div> : <p className="empty">Загрузка…</p>}
      </section>
    );
  }

  const checking = doc.validation_status === "in_progress";

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{doc.title}</h1>
          <div className="muted">
            <a href={doc.url} target="_blank" rel="noreferrer">
              Открыть в Confluence ↗
            </a>
            {" · создан "}
            {formatDateTime(doc.created_in_confluence_at)}
            {" · изменён "}
            {formatDateTime(doc.last_modified_in_confluence_at)}
          </div>
        </div>
        <span className={`badge ${doc.validation_status}`}>
          {STATUS_LABELS[doc.validation_status] ?? doc.validation_status}
        </span>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="actions" style={{ marginBottom: "1.2rem" }}>
        <button onClick={() => runValidation(false)} disabled={busy || checking}>
          {checking ? "Проверяется…" : "Проверить"}
        </button>
        <button className="secondary" onClick={() => runValidation(true)} disabled={busy || checking}>
          Проверить заново
        </button>
        <button
          onClick={sendComment}
          disabled={busy || !report || !!report.error_message || !!report.comment_sent_at}
          title={
            !report
              ? "Сначала выполните проверку"
              : report.comment_sent_at
                ? "Комментарий уже опубликован"
                : ""
          }
        >
          {report?.comment_sent_at
            ? `Отправлено ${formatDateTime(report.comment_sent_at)}`
            : "Отправить замечания в Confluence"}
        </button>
      </div>

      {!report && (
        <div className="card">
          <p className="empty">
            Документ ещё не проверялся. Нажмите «Проверить», чтобы запустить
            проверку шаблона и ИИ-анализ содержимого.
          </p>
        </div>
      )}

      {report?.error_message && (
        <div className="card">
          <h2>❌ Ошибка проверки</h2>
          <div className="markdown error">{report.error_message}</div>
        </div>
      )}

      {report && !report.error_message && (
        <>
          <div className="card">
            <h2>
              {report.template_passed ? "✅" : "❌"} Соответствие шаблону требований
            </h2>
            <div className="markdown">
              <Markdown text={report.template_findings || "—"} />
            </div>
          </div>

          <div className="card">
            <h2>
              {report.ai_passed == null ? "—️" : report.ai_passed ? "✅" : "❌"} Качество
              содержимого (ИИ)
            </h2>
            <div className="markdown">
              <Markdown text={report.ai_findings || "—"} />
            </div>
            <div className="muted" style={{ marginTop: "0.6rem" }}>
              Отчёт сформирован {formatDateTime(report.created_at)} (запуск:{" "}
              {report.triggered_by === "auto" ? "автоматический" : "ручной"})
            </div>
          </div>
        </>
      )}

      <div className="card">
        <h2>📝 Заметки руководителя (Markdown)</h2>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Замечания, договорённости, задачи по документу…"
        />
        {note.trim() && (
          <div className="note-preview">
            <div className="muted" style={{ marginBottom: "0.3rem" }}>
              Предпросмотр:
            </div>
            <div className="markdown">
              <Markdown text={note} />
            </div>
          </div>
        )}
        <div className="actions" style={{ marginTop: "0.7rem" }}>
          <button onClick={saveNote} disabled={busy || note === noteOriginal}>
            Сохранить заметку
          </button>
          <button
            className="secondary"
            onClick={deleteNote}
            disabled={busy || (!noteOriginal && !note)}
          >
            Удалить заметку
          </button>
          {note !== noteOriginal && <span className="muted">Есть несохранённые изменения</span>}
        </div>
      </div>
    </section>
  );
}
