import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Markdown from "./Markdown";
import StatusBadge from "./StatusBadge";
import {
  api,
  ApiError,
  type DocumentDetail,
  type ValidationReport,
} from "./api";

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

/**
 * Просмотр документа: шапка с автором, отчёты проверок, заметки.
 * Используется в двух режимах: отдельная страница (/documents/:id)
 * и выдвижная панель справа (embedded — без «Назад», компактнее).
 */
export default function DocumentReport({
  documentId,
  embedded = false,
}: {
  documentId: number;
  embedded?: boolean;
}) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [note, setNote] = useState("");
  const [noteOriginal, setNoteOriginal] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const documentResp = await api<DocumentDetail>(`/api/documents/${documentId}`);
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
    setDoc(null);
    setReport(null);
    load();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  const runValidation = async (force: boolean) => {
    setBusy(true);
    setInfo("Проверка запущена…");
    setError("");
    try {
      await api(`/api/documents/${documentId}/validate${force ? "?force=true" : ""}`, {
        method: "POST",
      });
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const current = await api<DocumentDetail>(`/api/documents/${documentId}`);
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
    return error ? (
      <div className="alert error">{error}</div>
    ) : (
      <p className="muted">Загрузка…</p>
    );
  }

  const checking = doc.validation_status === "in_progress";
  const analystName = doc.analyst_name || "Аналитик";
  const analystInitial = analystName.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className={embedded ? "doc-report embedded" : "doc-report"}>
      <nav className="breadcrumbs">
        <Link to="/">Аналитики</Link>
        <span className="sep">/</span>
        <Link to={`/analysts/${doc.analyst_id}`}>{analystName}</Link>
        <span className="sep">/</span>
        <span className="crumb-current" title={doc.title}>
          {embedded ? (
            <Link
              className="crumb-link"
              to={`/documents/${documentId}`}
              title="Открыть на отдельной странице"
            >
              {doc.title}
            </Link>
          ) : (
            doc.title
          )}
        </span>
      </nav>

      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">📄</span>
            {doc.title}
          </h1>
          <div className="doc-author">
            <span className="author-avatar" aria-hidden="true">
              {analystInitial}
            </span>
            <span className="author-info">
              <Link className="author-name" to={`/analysts/${doc.analyst_id}`}>
                {analystName}
              </Link>
              {doc.analyst_email && (
                <span className="muted author-email">{doc.analyst_email}</span>
              )}
            </span>
          </div>
          <div className="page-meta">
            <a href={doc.url} target="_blank" rel="noreferrer">
              Открыть в Confluence ↗
            </a>
            {" · создан "}
            {formatDateTime(doc.created_in_confluence_at)}
            {" · изменён "}
            {formatDateTime(doc.last_modified_in_confluence_at)}
          </div>
        </div>
        <div className="head-actions">
          <StatusBadge status={doc.validation_status} />
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="head-actions" style={{ marginBottom: "16px" }}>
        <button className="btn primary" onClick={() => runValidation(false)} disabled={busy || checking}>
          {checking ? "Проверяется…" : "▶ Проверить"}
        </button>
        <button className="btn subtle" onClick={() => runValidation(true)} disabled={busy || checking}>
          ⟳ Проверить заново
        </button>
        <button
          className="btn subtle"
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
        <div className="panel">
          <p className="table-empty">
            Документ ещё не проверялся. Нажмите «Проверить», чтобы запустить
            проверку шаблона и ИИ-анализ содержимого.
          </p>
        </div>
      )}

      {report?.error_message && (
        <div className="panel">
          <h2>❌ Ошибка проверки</h2>
          <div className="markdown error">{report.error_message}</div>
        </div>
      )}

      {report && !report.error_message && (
        <>
          <div className="panel">
            <h2>
              {report.template_passed ? "✅" : "❌"} Соответствие шаблону требований
            </h2>
            <div className="markdown">
              <Markdown text={report.template_findings || "—"} />
            </div>
          </div>

          <div className="panel">
            <h2>
              {report.ai_passed == null ? "—️" : report.ai_passed ? "✅" : "❌"} Качество
              содержимого (ИИ)
            </h2>
            <div className="markdown">
              <Markdown text={report.ai_findings || "—"} />
            </div>
            <div className="muted" style={{ marginTop: "10px" }}>
              Отчёт сформирован {formatDateTime(report.created_at)} (запуск:{" "}
              {report.triggered_by === "auto" ? "автоматический" : "ручной"})
            </div>
          </div>
        </>
      )}

      <div className="panel">
        <h2>📝 Заметки руководителя (Markdown)</h2>
        <textarea
          className="text-input"
          rows={5}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Замечания, договорённости, задачи по документу…"
        />
        {note.trim() && (
          <div className="note-preview">
            <div className="muted" style={{ marginBottom: "4px" }}>
              Предпросмотр:
            </div>
            <div className="markdown">
              <Markdown text={note} />
            </div>
          </div>
        )}
        <div className="head-actions" style={{ marginTop: "12px" }}>
          <button
            className="btn primary"
            onClick={saveNote}
            disabled={busy || note === noteOriginal}
          >
            Сохранить заметку
          </button>
          <button
            className="btn subtle danger"
            onClick={deleteNote}
            disabled={busy || (!noteOriginal && !note)}
          >
            Удалить заметку
          </button>
          {note !== noteOriginal && <span className="muted">Есть несохранённые изменения</span>}
        </div>
      </div>
    </div>
  );
}
