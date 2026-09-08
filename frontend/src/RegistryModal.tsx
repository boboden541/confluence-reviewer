import { useEffect, useState } from "react";
import { api, ApiError } from "./api";

/** Модалка «Из общего реестра»: нечёткий поиск по чужим шаблонам
 *  или критериям, копирование себе одним кликом. */

export interface RegistryEntry {
  id: number;
  name: string;
  owner_name: string;
  section_count?: number;
  prompt?: string;
}

export function RegistryModal({
  title,
  endpoint,
  onCopy,
  onClose,
}: {
  title: string;
  endpoint: string;
  onCopy: (entry: RegistryEntry) => Promise<void>;
  onClose: () => void;
}) {
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [copying, setCopying] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  useEffect(() => {
    api<RegistryEntry[]>(endpoint)
      .then(setEntries)
      .catch((exc) =>
        setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить реестр"),
      );
  }, [endpoint]);

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? entries.filter(
        (e) =>
          e.name.toLowerCase().includes(needle) ||
          (e.owner_name ?? "").toLowerCase().includes(needle),
      )
    : entries;

  const copy = async (entry: RegistryEntry) => {
    setCopying(entry.id);
    setError("");
    try {
      await onCopy(entry);
      setCopiedId(entry.id);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось скопировать");
    } finally {
      setCopying(null);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-panel" role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="alert error">{error}</div>}
          <span className="field">
            <input
              className="text-input"
              placeholder="Поиск по названию или автору…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
          </span>
          <div className="found-list">
            {visible.length === 0 && <div className="nav-empty">В реестре пока пусто</div>}
            {visible.map((entry) => (
              <div key={entry.id} className="found-row" style={{ cursor: "default" }}>
                <span className="found-info">
                  <span className="found-name">{entry.name}</span>
                  <span className="found-sub">
                    автор: {entry.owner_name}
                    {entry.section_count != null ? ` · разделов: ${entry.section_count}` : ""}
                  </span>
                </span>
                {copiedId === entry.id ? (
                  <span className="found-state">скопировано ✓</span>
                ) : (
                  <button
                    type="button"
                    className="btn small primary"
                    disabled={copying === entry.id}
                    onClick={() => copy(entry)}
                  >
                    {copying === entry.id ? "…" : "＋ Добавить копию"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="modal-foot">
          <span className="hint" style={{ marginRight: "auto", fontSize: 11.5, color: "var(--text-subtlest)" }}>
            Копия полностью ваша: правки не затрагивают оригинал
          </span>
          <button className="btn subtle" type="button" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
