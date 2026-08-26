import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Analyst } from "../api";
import { on } from "../events";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU");
}

export default function AnalystsPage() {
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busyAnalyst, setBusyAnalyst] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);
  // редактирование карточки: null — форма скрыта
  const [editing, setEditing] = useState<Analyst | null>(null);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editUsername, setEditUsername] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  const load = useCallback(async () => {
    try {
      setAnalysts(await api<Analyst[]>("/api/analysts"));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить список");
    }
  }, []);

  // Итог синхронизации приходит событием (SSE): запущенная откуда угодно —
  // кнопкой здесь, из другой вкладки или плановая по расписанию — она сама
  // обновит страницу. «Завершение» из снимка при подключении игнорируем:
  // это состояние прошлого прогона, а не новость.
  useEffect(() => {
    let sawRun = false;
    return on("sync", (e) => {
      if (e.running) {
        sawRun = true;
        setSyncing(true);
        return;
      }
      setSyncing(false);
      if (!sawRun) return;
      sawRun = false;
      setBusyAnalyst(null);
      const failures = (e.last_results ?? []).filter((r) => r.error);
      const created = (e.last_results ?? []).reduce((acc, r) => acc + r.created, 0);
      const updated = (e.last_results ?? []).reduce((acc, r) => acc + r.updated, 0);
      setInfo(
        failures.length
          ? `Синхронизация завершена с ошибками: ${failures.map((f) => `${f.analyst_name}: ${f.error}`).join("; ")}`
          : `Синхронизация завершена: новых ${created}, обновлено ${updated}`,
      );
      void load();
    });
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  const syncAnalyst = async (id: number) => {
    setBusyAnalyst(id);
    setInfo("");
    setError("");
    try {
      await api(`/api/analysts/${id}/sync`, { method: "POST" });
      setSyncing(true);
    } catch (exc) {
      setBusyAnalyst(null);
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить синхронизацию");
    }
  };

  const syncAll = async () => {
    setInfo("");
    setError("");
    try {
      await api("/api/sync/all", { method: "POST" });
      setSyncing(true);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить синхронизацию");
    }
  };

  // ФТ-CR-1 в UI: создание карточки аналитика вручную.
  const addAnalyst = async () => {
    if (!newName.trim() || !newEmail.trim()) return;
    setCreating(true);
    setInfo("");
    setError("");
    try {
      await api("/api/analysts", {
        method: "POST",
        body: JSON.stringify({ full_name: newName, email: newEmail }),
      });
      setNewName("");
      setNewEmail("");
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось добавить аналитика");
    } finally {
      setCreating(false);
    }
  };

  const startEdit = (analyst: Analyst) => {
    setEditing(analyst);
    setEditName(analyst.full_name);
    setEditEmail(analyst.email);
    setEditUsername(analyst.confluence_username ?? "");
    setError("");
    setInfo("");
  };

  const cancelEdit = () => setEditing(null);

  const saveEdit = async () => {
    if (!editing || !editName.trim() || !editEmail.trim()) return;
    setSavingEdit(true);
    setInfo("");
    setError("");
    try {
      await api(`/api/analysts/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify({
          full_name: editName.trim(),
          email: editEmail.trim(),
          confluence_username: editUsername.trim() || null,
        }),
      });
      setInfo("Карточка аналитика сохранена");
      setEditing(null);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить аналитика");
    } finally {
      setSavingEdit(false);
    }
  };

  const deleteAnalyst = async (analyst: Analyst) => {
    const docsNote = analyst.documents_count
      ? ` и все его документы (${analyst.documents_count})`
      : "";
    if (!window.confirm(`Удалить аналитика «${analyst.full_name}»${docsNote}?`)) return;
    setInfo("");
    setError("");
    try {
      await api(`/api/analysts/${analyst.id}`, { method: "DELETE" });
      setInfo(`Аналитик «${analyst.full_name}» удалён`);
      if (editing?.id === analyst.id) setEditing(null);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить аналитика");
    }
  };

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <span>Ревью требований</span>
        <span className="sep">/</span>
        <span>Аналитики</span>
      </nav>
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">👥</span>Аналитики
          </h1>
          <div className="page-meta">
            {analysts.length} аналитиков · документов:{" "}
            {analysts.reduce((acc, a) => acc + a.documents_count, 0)}
          </div>
        </div>
        <div className="head-actions">
          <button className="btn primary" onClick={syncAll} disabled={syncing}>
            {syncing ? "Синхронизация…" : "⟳ Синхронизировать всех"}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <form
        className="panel add-panel"
        onSubmit={(e) => {
          e.preventDefault();
          addAnalyst();
        }}
      >
        <div className="form-row">
          <span className="field">
            <label htmlFor="new-analyst-name">ФИО</label>
            <input
              id="new-analyst-name"
              className="text-input"
              placeholder="ФИО нового аналитика"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </span>
          <span className="field">
            <label htmlFor="new-analyst-email">Email</label>
            <input
              id="new-analyst-email"
              className="text-input"
              placeholder="email@example.com"
              type="email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
          </span>
          <button
            className="btn subtle"
            type="submit"
            disabled={creating || !newName.trim() || !newEmail.trim()}
            style={{ marginBottom: "1px" }}
          >
            {creating ? "Добавление…" : (
              <>
                <span aria-hidden="true">＋</span> Добавить аналитика
              </>
            )}
          </button>
        </div>
      </form>

      {editing && (
        <form
          className="panel"
          onSubmit={(e) => {
            e.preventDefault();
            saveEdit();
          }}
        >
          <h2>Изменение: {editing.full_name}</h2>
          <div className="form-row">
            <span className="field">
              <label htmlFor="edit-analyst-name">ФИО</label>
              <input
                id="edit-analyst-name"
                className="text-input"
                placeholder="ФИО аналитика"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </span>
            <span className="field">
              <label htmlFor="edit-analyst-email">Email</label>
              <input
                id="edit-analyst-email"
                className="text-input"
                placeholder="Новый email аналитика"
                type="email"
                value={editEmail}
                onChange={(e) => setEditEmail(e.target.value)}
              />
            </span>
            <span className="field">
              <label htmlFor="edit-analyst-username">Username в Confluence</label>
              <input
                id="edit-analyst-username"
                className="text-input"
                placeholder="username в Confluence (пусто — авто)"
                value={editUsername}
                onChange={(e) => setEditUsername(e.target.value)}
              />
            </span>
            <button
              className="btn primary"
              type="submit"
              disabled={savingEdit || !editName.trim() || !editEmail.trim()}
              style={{ marginBottom: "1px" }}
            >
              {savingEdit ? "Сохранение…" : "Сохранить"}
            </button>
            <button
              className="btn subtle"
              type="button"
              onClick={cancelEdit}
              style={{ marginBottom: "1px" }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      <div className="table-wrap">
      <table className="cf">
        <thead>
          <tr>
            <th>ФИО</th>
            <th>Email</th>
            <th>Username в Confluence</th>
            <th className="num">Документов</th>
            <th>Последняя синхронизация</th>
            <th>Ошибки</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {analysts.map((analyst) => (
            <tr key={analyst.id}>
              <td>
                <Link to={`/analysts/${analyst.id}`}>{analyst.full_name}</Link>
              </td>
              <td className="cell-subtle">{analyst.email}</td>
              <td className="cell-subtle">{analyst.confluence_username ?? "auto"}</td>
              <td className="num">{analyst.documents_count}</td>
              <td className="cell-subtle">{formatDate(analyst.last_synced_at)}</td>
              <td className={analyst.sync_error ? "cell-error" : "cell-subtle"}>
                {analyst.sync_error ?? "—"}
              </td>
              <td className="actions-cell">
                <button
                  className="btn small subtle"
                  onClick={() => syncAnalyst(analyst.id)}
                  disabled={syncing || busyAnalyst === analyst.id}
                >
                  {busyAnalyst === analyst.id ? "…" : (
                    <>
                      <span aria-hidden="true">⟳</span> Синхронизировать
                    </>
                  )}
                </button>
                <button
                  className="btn small subtle"
                  onClick={() => startEdit(analyst)}
                  disabled={syncing}
                >
                  <span aria-hidden="true">✎</span> Изменить
                </button>
                <button
                  className="btn small subtle danger"
                  onClick={() => deleteAnalyst(analyst)}
                  disabled={syncing}
                >
                  <span aria-hidden="true">🗑</span> Удалить
                </button>
              </td>
            </tr>
          ))}
          {analysts.length === 0 && (
            <tr>
              <td colSpan={7} className="table-empty">
                Аналитики ещё не заведены
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </section>
  );
}
