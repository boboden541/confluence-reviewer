import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Reminder } from "./api";
import { useReminders } from "./remindersContext";

/** Панель напоминаний: открытые группами «просрочено / сегодня / дальше»
 *  (по локальной дате пользователя), выполненные — свёрнутым блоком.
 *  analystId ограничивает список одним аналитиком (блок в профиле);
 *  showDoneToggle включает свёрнутый блок выполненных (главная). */

type Group = "overdue" | "today" | "later";

function dayStamp(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date.toDateString();
}

export default function RemindersPanel({
  analystId,
  showDoneToggle = false,
  compact = false,
}: {
  analystId?: number;
  showDoneToggle?: boolean;
  compact?: boolean;
}) {
  const { open } = useReminders();
  const [items, setItems] = useState<Reminder[] | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const query = analystId != null ? `?analyst_id=${analystId}` : "";
      setItems(await api<Reminder[]>(`/api/reminders${query}`));
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить напоминания");
    }
  }, [analystId]);

  useEffect(() => {
    void load();
    // напоминания создаёт и глобальная кнопка, и кнопки на страницах —
    // панель перечитывает себя сама
    const handler = () => void load();
    window.addEventListener("reminders-changed", handler);
    return () => window.removeEventListener("reminders-changed", handler);
  }, [load]);

  const act = async (id: number, path: "done" | "reopen") => {
    setBusyId(id);
    setError("");
    try {
      await api(`/api/reminders/${id}/${path}`, { method: "POST" });
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Действие не удалось");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm("Удалить выполненное напоминание? История не сохранится.")) return;
    setBusyId(id);
    setError("");
    try {
      await api(`/api/reminders/${id}`, { method: "DELETE" });
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить");
    } finally {
      setBusyId(null);
    }
  };

  const todayStamp = new Date().toDateString();
  const openItems = (items ?? []).filter((r) => r.status === "open");
  const done = (items ?? []).filter((r) => r.status === "done");
  const groups: Record<Group, Reminder[]> = { overdue: [], today: [], later: [] };
  for (const reminder of openItems) {
    const stamp = dayStamp(reminder.remind_at);
    if (stamp === null) groups.later.push(reminder);
    else if (new Date(stamp).getTime() < new Date(todayStamp).getTime()) groups.overdue.push(reminder);
    else if (stamp === todayStamp) groups.today.push(reminder);
    else groups.later.push(reminder);
  }

  const renderOne = (reminder: Reminder, done: boolean) => (
    <div key={reminder.id} className={`rem-item${done ? " done" : ""}`}>
      <input
        type="checkbox"
        className="rem-check"
        checked={done}
        disabled={busyId === reminder.id}
        aria-label={done ? "Вернуть в открытые" : "Выполнить"}
        onChange={() => act(reminder.id, done ? "reopen" : "done")}
      />
      <span className="rem-main">
        <span className="rem-text">{reminder.text}</span>
        <span className="rem-who">
          👤 <Link to={`/analysts/${reminder.analyst_id}`}>{reminder.analyst_name}</Link>
          {reminder.document_id != null && (
            <>
              {" · "}📄 <Link to={`/documents/${reminder.document_id}`}>{reminder.document_title}</Link>
            </>
          )}
        </span>
      </span>
      {done ? (
        <>
          <span className="rem-date">выполнено</span>
          <button className="btn btn-danger small" disabled={busyId === reminder.id} onClick={() => remove(reminder.id)}>
            🗑
          </button>
        </>
      ) : (
        reminder.remind_at && <span className="rem-date">{dayStamp(reminder.remind_at) === todayStamp ? "сегодня" : new Date(reminder.remind_at).toLocaleDateString("ru-RU")}</span>
      )}
    </div>
  );

  const groupHead = (cls: string, label: string) => (
    <div className={`rem-group ${cls}`}>{label}</div>
  );

  return (
    <>
      {error && <div className="alert error">{error}</div>}
      {items !== null && (
        <div className="panel" style={{ padding: 0 }}>
          <div className="panel-head">
            <h2>⏰ Напоминания{analystId != null ? "" : ""}</h2>
            <span className="count">
              {compact
                ? `${openItems.length} открыт`
                : `${openItems.length} открыт · ${done.length} выполнено`}
            </span>
            <button className="btn btn-default small" onClick={() => open({ analyst_id: analystId })}>
              ＋
            </button>
          </div>
          <div>
            {openItems.length === 0 && done.length === 0 && (
              <div className="rem-empty">
                Напоминаний нет — создайте кнопкой справа снизу или «＋»
              </div>
            )}

            {groups.overdue.length > 0 && (
              <>
                {groupHead("overdue", "🔴 Просрочено")}
                {groups.overdue.map((r) => renderOne(r, false))}
              </>
            )}
            {groups.today.length > 0 && (
              <>
                {groupHead("today", "🟡 Сегодня")}
                {groups.today.map((r) => renderOne(r, false))}
              </>
            )}
            {groups.later.length > 0 && (
              <>
                {groupHead("later", "📅 Дальше")}
                {groups.later.map((r) => renderOne(r, false))}
              </>
            )}

            {showDoneToggle && done.length > 0 && (
              <>
                <button className="rem-done-toggle" onClick={() => setShowDone((v) => !v)}>
                  {showDone ? "▾" : "▸"} Выполненные ({done.length})
                </button>
                {showDone && done.map((r) => renderOne(r, true))}
              </>
            )}
            {!showDoneToggle && done.length > 0 && done.map((r) => renderOne(r, true))}
          </div>
        </div>
      )}
    </>
  );
}
