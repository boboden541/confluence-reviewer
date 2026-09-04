import { useEffect, useState } from "react";
import { api, ApiError, type Analyst } from "./api";
import { initials } from "./orgUi";
import { DomainsInput } from "./DomainsInput";

/** Модалка «Добавить аналитиков в команду»: поиск по ФИО/email среди всех
 *  аналитиков с чекбоксами — можно выбрать нескольких сразу. Уже состоящие
 *  в команде помечены и заблокированы. Домены (если введены) применяются
 *  всем выбранным; пустой список отправляется как null — «оставить как
 *  есть», чтобы перевод не стирал существующие теги. */
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
  onSave: (analystIds: number[], domains: string[] | null) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [domains, setDomains] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch((exc) =>
        setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить аналитиков"),
      );
  }, []);

  // Esc закрывает модалку, как и крестик
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const needle = query.trim().toLowerCase();
  const found = analysts
    .filter((a) => !needle || a.full_name.toLowerCase().includes(needle) || a.email.toLowerCase().includes(needle))
    .slice(0, 12);

  const toggle = (analyst: Analyst, inTeam: boolean) => {
    if (inTeam) return;
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(analyst.id)) next.delete(analyst.id);
      else next.add(analyst.id);
      return next;
    });
  };

  const submit = () => {
    if (picked.size === 0) return;
    onSave([...picked], domains.length ? domains : null);
  };

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-panel" role="dialog" aria-label="Добавить аналитиков">
        <div className="modal-head">
          <h2>Добавить аналитиков в команду «{teamName}»</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
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
                onKeyDown={(e) => {
                  // Enter в поиске — не «отправить форму»
                  if (e.key === "Enter") e.preventDefault();
                }}
                autoFocus
              />
            </span>

            <div className="found-list">
              {found.length === 0 && <div className="nav-empty">никого не найдено</div>}
              {found.map((analyst) => {
                const inTeam = memberIds.has(analyst.id);
                const isPicked = picked.has(analyst.id);
                return (
                  <label
                    key={analyst.id}
                    className={`found-row${isPicked ? " picked" : ""}${inTeam ? " disabled" : ""}`}
                  >
                    <input
                      type="checkbox"
                      className="found-check"
                      checked={isPicked}
                      disabled={inTeam}
                      onChange={() => toggle(analyst, inTeam)}
                      aria-label={`Выбрать ${analyst.full_name}`}
                    />
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
                  </label>
                );
              })}
            </div>

            {picked.size > 0 && (
              <span className="field">
                <label>Домены участников (свободные теги)</label>
                <DomainsInput domains={domains} onChange={setDomains} />
                <div className="hint">
                  Применятся всем выбранным ({picked.size}). Пусто — домены аналитиков
                  останутся прежними.
                </div>
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
            <button className="btn primary" type="submit" disabled={saving || picked.size === 0}>
              {saving ? "Добавление…" : `Добавить${picked.size ? ` (${picked.size})` : ""}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
