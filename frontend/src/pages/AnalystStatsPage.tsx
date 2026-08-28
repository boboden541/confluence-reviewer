import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Analyst, type RatingsSummary } from "../api";

/** «3.7» — одна цифра после разделителя, как в оценках */
function formatScore(value: number): string {
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

function pluralRatings(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} оценка`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${count} оценки`;
  return `${count} оценок`;
}

/**
 * Статистика оценок руководителя по ИИ-критериям аналитика: общий балл и
 * средние по критериям за период. Открывается из профиля («Статистика»).
 */
export default function AnalystStatsPage() {
  const { analystId } = useParams();
  const id = Number(analystId);
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [summary, setSummary] = useState<RatingsSummary | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(
    async (from: string, to: string) => {
      try {
        setAnalyst(await api<Analyst>(`/api/analysts/${id}`));
        const params = new URLSearchParams();
        if (from) params.set("date_from", from);
        if (to) params.set("date_to", to);
        const query = params.toString();
        setSummary(
          await api<RatingsSummary>(`/api/analysts/${id}/ratings-summary${query ? `?${query}` : ""}`),
        );
        setError("");
      } catch (exc) {
        setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить статистику");
      }
    },
    [id],
  );

  useEffect(() => {
    setAnalyst(null);
    setSummary(null);
    setDateFrom("");
    setDateTo("");
    void load("", "");
  }, [load]);

  // фильтр по периоду: даты оценки (когда руководитель выставил балл)
  const applyFilter = () => void load(dateFrom, dateTo);
  const resetFilter = () => {
    setDateFrom("");
    setDateTo("");
    void load("", "");
  };

  if (!analyst) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <Link to="/">Аналитики</Link>
        <span className="sep">/</span>
        <Link to={`/analysts/${id}`}>{analyst.full_name}</Link>
        <span className="sep">/</span>
        <span className="crumb-current">Статистика оценок</span>
      </nav>

      <div className="page-head">
        <div>
          <h1 className="page-title">Статистика оценок</h1>
          <div className="page-meta">
            {analyst.full_name}
            {" · шкала 1–5 · "}
            {dateFrom || dateTo
              ? `период: ${dateFrom || "…"} — ${dateTo || "…"}`
              : "за всё время"}
          </div>
        </div>
        <div className="head-actions">
          <Link className="btn ghost" to={`/analysts/${id}`}>
            <span aria-hidden="true">←</span> В профиль
          </Link>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="stats-filters">
        <label>
          <span>Оценки с</span>
          <input
            type="date"
            className="text-input"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label>
          <span>по</span>
          <input
            type="date"
            className="text-input"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <button className="btn small primary" onClick={applyFilter}>
          Применить
        </button>
        {(dateFrom || dateTo) && (
          <button className="btn small ghost" onClick={resetFilter}>
            За всё время
          </button>
        )}
      </div>

      {summary && summary.total_ratings > 0 ? (
        <>
          <div className="stats-hero">
            <div className="stats-hero-value">{formatScore(summary.overall_average ?? 0)}</div>
            <div className="stats-hero-caption">
              общий средний балл
              <br />
              {pluralRatings(summary.total_ratings)}
            </div>
          </div>

          <div className="zone-label">Средние по критериям</div>

          <ul className="stats-bars">
            {summary.criteria.map((criterion) => (
              <li
                className="stats-row"
                key={criterion.criterion_id}
                title={`${criterion.name}: ${formatScore(criterion.average)} из 5 (${pluralRatings(criterion.ratings_count)})`}
              >
                <div className="stats-row-label">
                  <span className="stats-row-name">{criterion.name}</span>
                  {criterion.is_archived && (
                    <span className="lozenge moved" title="Критерий в архиве — новых проверок с ним нет">
                      в архиве
                    </span>
                  )}
                </div>
                <div className="stats-row-main">
                  <div className="stats-bar-track" role="presentation">
                    <div
                      className="stats-bar-fill"
                      style={{ width: `${(criterion.average / 5) * 100}%` }}
                    />
                  </div>
                  <span className="stats-row-value">{formatScore(criterion.average)}</span>
                  <span className="muted stats-row-count">{pluralRatings(criterion.ratings_count)}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        summary && (
          <div className="empty-hint">
            Оценок пока нет. Оценивайте документы в блоке «Оценка руководителя» —
            статистика соберётся здесь.
          </div>
        )
      )}
    </section>
  );
}
