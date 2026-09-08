import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Analyst, type AnalystNote } from "../api";
import { DomainsInput } from "../DomainsInput";
import Markdown from "../Markdown";
import { pushRecent } from "../recent";

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

/**
 * Профиль аналитика: карточка с числом документов и заметки руководителя
 * по работе с ним (Markdown, по образцу заметки документа). Список
 * документов — соседний маршрут /analysts/:id/documents.
 */
export default function AnalystProfilePage() {
  const { analystId } = useParams();
  const id = Number(analystId);
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [note, setNote] = useState("");
  const [noteOriginal, setNoteOriginal] = useState("");
  const [domains, setDomains] = useState<string[]>([]);
  const [domainsOriginal, setDomainsOriginal] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const item = await api<Analyst>(`/api/analysts/${id}`);
      setAnalyst(item);
      setDomains(item.domains);
      setDomainsOriginal(item.domains);
      const noteResp = await api<AnalystNote>(`/api/analysts/${id}/note`);
      setNote(noteResp.content);
      setNoteOriginal(noteResp.content);
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить профиль");
    }
  }, [id]);

  useEffect(() => {
    setAnalyst(null);
    setNote("");
    setNoteOriginal("");
    setDomains([]);
    setDomainsOriginal([]);
    setError("");
    setInfo("");
    void load();
  }, [load]);

  // визит профиля попадает в «Недавние» на главной
  useEffect(() => {
    if (analyst) pushRecent("analyst", analyst.id, analyst.full_name);
  }, [analyst?.id, analyst?.full_name]);

  // домены сохраняются автоматически: добавили по Enter или убрали чип —
  // короткая пауза и PUT; кнопки «Сохранить» больше не требуется
  const domainsDirty =
    domains.length !== domainsOriginal.length ||
    domains.some((d, i) => d !== domainsOriginal[i]);

  const saveDomains = useCallback(
    async (next: string[]) => {
      try {
        const applied = await api<string[]>(`/api/analysts/${id}/domains`, {
          method: "PUT",
          body: JSON.stringify({ domains: next }),
        });
        setDomains(applied);
        setDomainsOriginal(applied);
        setInfo("Домены сохранены");
        setError("");
      } catch (exc) {
        setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить домены");
      }
    },
    [id],
  );

  useEffect(() => {
    if (!domainsDirty) return;
    const timer = window.setTimeout(() => void saveDomains(domains), 700);
    return () => window.clearTimeout(timer);
  }, [domains, domainsDirty, saveDomains]);

  const saveNote = async () => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/analysts/${id}/note`, {
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
      await api(`/api/analysts/${id}/note`, { method: "DELETE" });
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

  if (!analyst) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  const initial = analyst.full_name.trim().charAt(0).toUpperCase() || "?";

  return (
    <section className="page">
      <nav className="breadcrumbs">
        {/* причастность к структуре: кликабельный путь кластер → команда */}
        {analyst.cluster_id != null && analyst.team_id != null ? (
          <>
            <Link to="/">Кластеры</Link>
            <span className="sep">/</span>
            <Link to={`/clusters/${analyst.cluster_id}`}>{analyst.cluster_name}</Link>
            <span className="sep">/</span>
            <Link to={`/teams/${analyst.team_id}`}>{analyst.team_name}</Link>
            <span className="sep">/</span>
          </>
        ) : (
          <>
            <Link to="/analysts">Аналитики</Link>
            <span className="sep">/</span>
          </>
        )}
        <span className="crumb-current">{analyst.full_name}</span>
      </nav>

      <div className="page-head profile-head">
        <span className="profile-avatar" aria-hidden="true">
          {initial}
        </span>
        <div>
          <h1 className="page-title">{analyst.full_name}</h1>
          <div className="page-meta">
            {analyst.email}
            {analyst.confluence_username && <> · Confluence: {analyst.confluence_username}</>}
            {" · документов: "}
            {analyst.documents_count}
            {" · синхронизирован "}
            {formatDateTime(analyst.last_synced_at)}
          </div>
          <div className="head-actions profile-actions">
            <Link className="btn primary" to={`/analysts/${id}/documents`}>
              <span aria-hidden="true">📄</span> Документы ({analyst.documents_count})
            </Link>
            <Link className="btn ghost" to={`/analysts/${id}/stats`}>
              <span aria-hidden="true">📊</span> Статистика оценок
            </Link>
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="zone-label">Домены (бизнес-функционал)</div>

      <div className="notes-zone">
        <DomainsInput domains={domains} onChange={setDomains} />
        <div className="head-actions notes-actions">
          {domainsDirty ? (
            <span className="muted">Сохраняем…</span>
          ) : (
            info === "Домены сохранены" && <span className="muted">Домены сохранены ✓</span>
          )}
        </div>
      </div>

      <div className="zone-label">Заметки руководителя</div>

      <div className="notes-zone">
        <textarea
          className="text-input"
          rows={5}
          aria-label="Заметка руководителя"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Сильные стороны, зоны роста, договорённости по документам аналитика…"
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
    </section>
  );
}
