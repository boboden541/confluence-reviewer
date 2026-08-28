import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import CriterionRatings from "./CriterionRatings";
import Markdown from "./Markdown";
import StatusBadge from "./StatusBadge";
import ValidationDialog from "./ValidationDialog";
import {
  api,
  ApiError,
  type DocumentDetail,
  type DocumentRatings,
  type ValidationReport,
} from "./api";
import { on } from "./events";

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

// результат конкретной проверки (шаблон/ИИ), а не статус документа целиком
function CheckBadge({ passed }: { passed: boolean | null }) {
  if (passed == null) return <span className="lozenge default">не запускалась</span>;
  return passed ? (
    <span className="lozenge success">пройдено</span>
  ) : (
    <span className="lozenge error">не пройдено</span>
  );
}

/**
 * Просмотр документа: шапка с автором, зоны «Проверки» и «Заметки».
 * Используется в двух режимах: отдельная страница (/documents/:id)
 * и выдвижная панель справа (embedded — с липкой шапкой и onClose).
 */
export default function DocumentReport({
  documentId,
  embedded = false,
  onClose,
}: {
  documentId: number;
  embedded?: boolean;
  onClose?: () => void;
}) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [ratings, setRatings] = useState<DocumentRatings | null>(null);
  const [note, setNote] = useState("");
  const [noteOriginal, setNoteOriginal] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  // в панели шапка документа уезжает при прокрутке — «липкая» строка
  // с крошками и названием всегда сверху
  const [pinned, setPinned] = useState(false);
  const headerRef = useRef<HTMLDivElement | null>(null);

  // Проверка и отсюда идёт через диалог настроек (шаблон + промт ИИ) —
  // как и в списке документов. «Проверить заново» = force.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogForce, setDialogForce] = useState(false);

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
      // блок оценивания: критерии последнего прогона с оценками
      setRatings(
        await api<DocumentRatings>(`/api/documents/${documentId}/ratings`).catch(() => null),
      );
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить документ");
    }
  }, [documentId]);

  useEffect(() => {
    setDoc(null);
    setReport(null);
    setRatings(null);
    setPinned(false);
    load();
  }, [load]);

  // блок шапки ушёл выше границы прокрутки — показываем компактный ряд.
  // scroll-listener, а не IntersectionObserver: корневые отступы IO в Chrome
  // не принимают calc(), а фикс в пикселях ненадёжен при ресайзе панели.
  useEffect(() => {
    const el = headerRef.current;
    if (!embedded || !el) return;
    const scroller = el.closest(".drawer-body");
    if (!scroller || !scroller.clientHeight) return; // jsdom — без геометрии
    const update = () => {
      // шапка считается уехавшей, когда её низ скрылся за липкой строкой
      const headerBottom = el.getBoundingClientRect().bottom;
      const stickyLine = scroller.getBoundingClientRect().top + 48;
      setPinned(headerBottom < stickyLine);
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [embedded, doc]);

  // Итог проверки приходит событием (SSE): документ обновится сам, кем бы
  // проверка ни была запущена — отсюда, из списка или другой вкладки.
  useEffect(() => {
    return on("validation", (e) => {
      if (e.document_id !== documentId || e.status === "running") return;
      setBusy(false);
      setInfo("");
      void load();
    });
  }, [documentId, load]);

  // Диалог отработал: проверка ушла в фон, ждём событие завершения
  const handleLaunched = () => {
    setDialogOpen(false);
    setBusy(true);
    setInfo("Проверка запущена…");
    setError("");
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

  const crumbs = (
    <nav className="breadcrumbs">
      <Link to="/">Аналитики</Link>
      <span className="sep">/</span>
      <Link to={`/analysts/${doc.analyst_id}/documents`}>{analystName}</Link>
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
  );

  return (
    <div className={embedded ? "doc-report embedded" : "doc-report"}>
      {embedded ? (
        <div className={pinned ? "drawer-sticky pinned" : "drawer-sticky"}>
          <div className="drawer-sticky-row">
            <div className="drawer-crumbs">{crumbs}</div>
            {onClose && (
              <button
                type="button"
                className="btn small subtle drawer-close"
                aria-label="Закрыть панель"
                onClick={onClose}
              >
                ✕
              </button>
            )}
          </div>
          {pinned && (
            <div className="drawer-sticky-doc">
              <span className="sticky-title" title={doc.title}>
                {doc.title}
              </span>
              <StatusBadge status={doc.validation_status} />
            </div>
          )}
        </div>
      ) : (
        crumbs
      )}

      <div className="doc-header" ref={headerRef}>
        <div className="page-head">
          <div>
            <h1 className="page-title">{doc.title}</h1>
            <div className="doc-author">
              <span className="author-avatar" aria-hidden="true">
                {analystInitial}
              </span>
              <span className="author-info">
                <Link className="author-name" to={`/analysts/${doc.analyst_id}/documents`}>
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

        {/* одна главная кнопка; вторичные — тише (ghost) */}
        <div className="head-actions doc-actions">
          <button
            className="btn primary"
            onClick={() => {
              setDialogForce(false);
              setDialogOpen(true);
            }}
            disabled={busy || checking}
          >
            {checking ? "Проверяется…" : <><span aria-hidden="true">▶</span> Проверить</>}
          </button>
          <button
            className="btn ghost"
            onClick={() => {
              setDialogForce(true);
              setDialogOpen(true);
            }}
            disabled={busy || checking}
            title="Проверить заново, даже если документ не менялся"
          >
            <span aria-hidden="true">⟳</span> Проверить заново
          </button>
          <button
            className="btn ghost"
            onClick={sendComment}
            disabled={busy || !report || !!report.error_message || !!report.comment_sent_at}
            title={
              !report
                ? "Сначала выполните проверку"
                : report.comment_sent_at
                  ? "Комментарий уже опубликован"
                  : "Опубликовать замечания комментарием на странице Confluence"
            }
          >
            {report?.comment_sent_at
              ? `Отправлено ${formatDateTime(report.comment_sent_at)}`
              : <><span aria-hidden="true">↗</span> Отправить замечания</>}
          </button>
        </div>
      </div>

      <div className="zone-label">Проверки</div>

      {!report && (
        <div className="empty-hint">
          Документ ещё не проверялся. Нажмите «Проверить», чтобы запустить
          проверку шаблона и ИИ-анализ содержимого.
        </div>
      )}

      {report?.error_message && (
        <div className="report-card fail">
          <div className="report-card-head">
            <h2>Ошибка проверки</h2>
            <span className="lozenge moved">сбой</span>
          </div>
          <div className="markdown error">{report.error_message}</div>
        </div>
      )}

      {report && !report.error_message && (
        <>
          <div
            className={
              report.template_passed == null
                ? "report-card"
                : report.template_passed
                  ? "report-card pass"
                  : "report-card fail"
            }
          >
            <div className="report-card-head">
              <h2>Шаблон требований</h2>
              <CheckBadge passed={report.template_passed} />
            </div>
            <div className="markdown">
              <Markdown text={report.template_findings || "—"} />
            </div>
          </div>

          <div
            className={
              report.ai_passed == null
                ? "report-card"
                : report.ai_passed
                  ? "report-card pass"
                  : "report-card fail"
            }
          >
            <div className="report-card-head">
              <h2>Содержимое (ИИ)</h2>
              <CheckBadge passed={report.ai_passed} />
            </div>
            <div className="markdown">
              <Markdown text={report.ai_findings || "—"} />
            </div>
          </div>

          <div className="muted report-meta">
            Отчёт сформирован {formatDateTime(report.created_at)} · запуск:{" "}
            {report.triggered_by === "auto" ? "автоматический" : "ручной"}
            {report.ai_prompt && " · промт ИИ: изменён"}
            {report.ai_model_used && ` · модель: ${report.ai_model_used}`}
            {report.template_version_id != null && ` · шаблон v${report.template_version_id}`}
          </div>
        </>
      )}

      {/* оценивать можно только после ИИ-прогона: пустой criteria — зоны нет */}
      {ratings && ratings.criteria.length > 0 && (
        <>
          <div className="zone-label">Оценка руководителя</div>
          <CriterionRatings documentId={documentId} ratings={ratings} onChanged={setRatings} />
        </>
      )}

      <div className="zone-label">Заметки руководителя</div>

      <div className="notes-zone">
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
        <div className="head-actions notes-actions">
          <button
            className="btn small primary"
            onClick={saveNote}
            disabled={busy || note === noteOriginal}
          >
            Сохранить заметку
          </button>
          <button
            className="btn small ghost danger"
            onClick={deleteNote}
            disabled={busy || (!noteOriginal && !note)}
          >
            Удалить заметку
          </button>
          {note !== noteOriginal && <span className="muted">Есть несохранённые изменения</span>}
        </div>
      </div>

      {dialogOpen && (
        <ValidationDialog
          documentIds={[documentId]}
          force={dialogForce}
          onClose={() => setDialogOpen(false)}
          onLaunched={handleLaunched}
        />
      )}
    </div>
  );
}
