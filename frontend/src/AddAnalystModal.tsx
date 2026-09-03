import { useEffect, useState } from "react";
import { api, ApiError, type Analyst } from "./api";
import { initials } from "./orgUi";
import { DomainsInput } from "./DomainsInput";

/** Модалка «Добавить аналитика в команду»: поиск по ФИО/email среди всех
 *  аналитиков (уже состоящие в команде помечены), домены нового участника. */
export function AddAnalystModal({
  teamName,
  memberIds,
  saving,
  onSave,
  onClose,
}: {
  teamName: string;
  memberIds: Set<number>;
  saving: boolean;
  onSave: (analystId: number, domains: string[]) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [selected, setSelected] = useState<Analyst | null>(null);
  const [domains, setDomains] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch((exc) =>
        setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить аналитиков"),
      );
  }, []);

  const needle = query.trim().toLowerCase();
  const found = analysts
    .filter((a) => !needle || a.full_name.toLowerCase().includes(needle) || a.email.toLowerCase().includes(needle))
    .slice(0, 8);

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-panel" role="dialog" aria-label="Добавить аналитика">
        <div className="modal-head">
          <h2>Добавить аналитика в команду «{teamName}»</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (selected) onSave(selected.id, domains);
          }}
        >
          <div className="modal-body">
            {error && <div className="alert error">{error}</div>}
            <span className="field">
              <label htmlFor="analyst-search">Поиск по ФИО или email</label>
              <input
                id="analyst-search"
                className="text-input"
                placeholder="Начните вводить…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
            </span>

            <div className="found-list">
              {found.length === 0 && <div className="nav-empty">никого не найдено</div>}
              {found.map((analyst) => {
                const inTeam = memberIds.has(analyst.id);
                const isPicked = selected?.id === analyst.id;
                return (
                  <button
                    key={analyst.id}
                    type="button"
                    className={`found-row${isPicked ? " picked" : ""}`}
                    onClick={() => {
                      if (!inTeam) setSelected(analyst);
                    }}
                    disabled={inTeam}
                  >
                    <span className="p-avatar small" aria-hidden="true">
                      {initials(analyst.full_name)}
                    </span>
                    <span className="found-info">
                      <span className="found-name">{analyst.full_name}</span>
                      <span className="found-sub">
                        {analyst.email} ·{" "}
                        {inTeam ? "уже в этой команде" : analyst.team_name ? `сейчас в «${analyst.team_name}»` : "без команды"}
                      </span>
                    </span>
                    {inTeam && <span className="found-state">в команде</span>}
                  </button>
                );
              })}
            </div>

            {selected && (
              <span className="field">
                <label>Домены участника (свободные теги)</label>
                <DomainsInput domains={domains} onChange={setDomains} />
              </span>
            )}
            <div className="hint">
              Аналитик состоит в одной команде: перевод из другой заменяет привязку. Его
              документы, заметки и оценки не затрагиваются.
            </div>
          </div>
          <div className="modal-foot">
            <button className="btn subtle" type="button" onClick={onClose}>
              Отмена
            </button>
            <button className="btn primary" type="submit" disabled={saving || !selected}>
              {saving ? "Добавление…" : "Добавить"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
