import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Team } from "../api";
import { clusterColor, initials } from "../orgUi";

/** Экран команды: шапка с описанием, агрегированные домены участников и
 *  карточки аналитиков с их доменами. Управление составом — следующий шаг. */
export default function TeamPage() {
  const { teamId } = useParams();
  const id = Number(teamId);
  const [team, setTeam] = useState<Team | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setTeam(await api<Team>(`/api/teams/${id}`));
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить команду");
    }
  }, [id]);

  useEffect(() => {
    setTeam(null);
    void load();
  }, [load]);

  if (!team) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  const clusterHue = clusterColor(null, team.cluster_id);

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <Link to="/">Кластеры</Link>
        <span className="sep">/</span>
        <Link to={`/clusters/${team.cluster_id}`}>{team.cluster_name}</Link>
        <span className="sep">/</span>
        <span className="crumb-current">{team.name}</span>
      </nav>

      <div className="page-head">
        <div>
          <h1 className="page-title">{team.name}</h1>
          <div className="page-meta">
            Команда кластера «{team.cluster_name}»
            {team.description ? ` · ${team.description}` : ""}
          </div>
          <div className="cluster-card-stats">
            <span>
              <b>{team.analysts.length}</b> аналитиков
            </span>
            <span>
              <b>{team.domains.length}</b> доменов
            </span>
          </div>
        </div>
      </div>

      {team.domains.length > 0 && (
        <div className="team-domains">
          {team.domains.map((domain) => (
            <span key={domain} className="domain-chip">
              {domain}
            </span>
          ))}
          <span className="muted domains-note">— домены участников</span>
        </div>
      )}

      <div className="zone-label">Состав команды</div>
      <div className="people-grid">
        {team.analysts.map((analyst) => (
          <Link key={analyst.id} to={`/analysts/${analyst.id}`} className="person-card person-card-link">
            <span className="p-avatar" style={{ background: clusterHue }} aria-hidden="true">
              {initials(analyst.full_name)}
            </span>
            <span className="person-card-body">
              <span className="person-card-name">{analyst.full_name}</span>
              <span className="person-card-sub">
                {analyst.email} · {analyst.documents_count} док.
              </span>
              {analyst.domains.length > 0 && (
                <span className="person-card-domains">
                  {analyst.domains.map((domain) => (
                    <span key={domain} className="domain-chip">
                      {domain}
                    </span>
                  ))}
                </span>
              )}
            </span>
          </Link>
        ))}
        {team.analysts.length === 0 && (
          <div className="panel table-empty">В команде ещё нет аналитиков.</div>
        )}
      </div>
    </section>
  );
}
