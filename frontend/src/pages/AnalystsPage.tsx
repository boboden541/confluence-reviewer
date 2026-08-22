import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Analyst, type SyncStatus } from "../api";

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
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      setAnalysts(await api<Analyst[]>("/api/analysts"));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить список");
    }
  }, []);

  const pollWhileRunning = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const status = await api<SyncStatus>("/api/sync/status");
        if (!status.running) {
          if (timer.current) clearInterval(timer.current);
          timer.current = null;
          setSyncing(false);
          setBusyAnalyst(null);
          const failures = (status.last_results ?? []).filter((r) => r.error);
          const created = (status.last_results ?? []).reduce((acc, r) => acc + r.created, 0);
          const updated = (status.last_results ?? []).reduce((acc, r) => acc + r.updated, 0);
          setInfo(
            failures.length
              ? `Синхронизация завершена с ошибками: ${failures.map((f) => `${f.analyst_name}: ${f.error}`).join("; ")}`
              : `Синхронизация завершена: новых ${created}, обновлено ${updated}`,
          );
          await load();
        }
      } catch {
        // статус недоступен — продолжаем опрос до таймаута интервала
      }
    }, 1000);
  }, [load]);

  useEffect(() => {
    load();
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  const syncAnalyst = async (id: number) => {
    setBusyAnalyst(id);
    setInfo("");
    setError("");
    try {
      await api(`/api/analysts/${id}/sync`, { method: "POST" });
      setSyncing(true);
      pollWhileRunning();
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
      pollWhileRunning();
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
    <section>
      <div className="page-head">
        <h1>Аналитики</h1>
        <button onClick={syncAll} disabled={syncing}>
          {syncing ? "Синхронизация…" : "Синхронизировать всех"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <form
        className="search"
        onSubmit={(e) => {
          e.preventDefault();
          addAnalyst();
        }}
      >
        <input
          placeholder="ФИО нового аналитика"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <input
          placeholder="email@example.com"
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
        />
        <button type="submit" disabled={creating || !newName.trim() || !newEmail.trim()}>
          {creating ? "Добавление…" : "Добавить аналитика"}
        </button>
      </form>

      {editing && (
        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            saveEdit();
          }}
        >
          <input
            placeholder="ФИО аналитика"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <input
            placeholder="Новый email аналитика"
            type="email"
            value={editEmail}
            onChange={(e) => setEditEmail(e.target.value)}
          />
          <input
            placeholder="username в Confluence (пусто — авто)"
            value={editUsername}
            onChange={(e) => setEditUsername(e.target.value)}
          />
          <button type="submit" disabled={savingEdit || !editName.trim() || !editEmail.trim()}>
            {savingEdit ? "Сохранение…" : "Сохранить"}
          </button>
          <button type="button" className="secondary" onClick={cancelEdit}>
            Отмена
          </button>
        </form>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>ФИО</th>
            <th>Email</th>
            <th>Username в Confluence</th>
            <th>Документов</th>
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
              <td>{analyst.email}</td>
              <td>{analyst.confluence_username ?? "auto"}</td>
              <td>{analyst.documents_count}</td>
              <td>{formatDate(analyst.last_synced_at)}</td>
              <td className={analyst.sync_error ? "error" : ""}>
                {analyst.sync_error ?? "—"}
              </td>
              <td className="actions">
                <button
                  onClick={() => syncAnalyst(analyst.id)}
                  disabled={syncing || busyAnalyst === analyst.id}
                >
                  {busyAnalyst === analyst.id ? "…" : "Синхронизировать"}
                </button>
                <button
                  className="secondary"
                  onClick={() => startEdit(analyst)}
                  disabled={syncing}
                >
                  Изменить
                </button>
                <button
                  className="secondary"
                  onClick={() => deleteAnalyst(analyst)}
                  disabled={syncing}
                >
                  Удалить
                </button>
              </td>
            </tr>
          ))}
          {analysts.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">
                Аналитики ещё не заведены
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
