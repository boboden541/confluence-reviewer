import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Cluster } from "../api";
import { clusterColor, clusterColorBg } from "../orgUi";

/** Экран кластера: шапка с описанием и счётчиками, команды «колоннами».
 *  Редактирование/создание команд — следующий шаг (TeamPage-модалки). */
export default function ClusterPage() {
  const { clusterId } = useParams();
  const id = Number(clusterId);
  const [cluster, setCluster] = useState<Cluster | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setCluster(await api<Cluster>(`/api/clusters/${id}`));
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить кластер");
    }
  }, [id]);

  useEffect(() => {
    setCluster(null);
    void load();
  }, [load]);

  if (!cluster) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  const color = clusterColor(cluster.color, cluster.id);

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <Link to="/">Кластеры</Link>
        <span className="sep">/</span>
        <span className="crumb-current">{cluster.name}</span>
      </nav>

      <div className="page-head cluster-head" style={{ borderTopColor: color }}>
        <span className="cluster-glyph big" style={{ background: color }} aria-hidden="true">
          {cluster.name.charAt(0).toUpperCase()}
        </span>
        <div>
          <h1 className="page-title">{cluster.name}</h1>
          <div className="page-meta">{cluster.description ?? "Без описания"}</div>
          <div className="cluster-card-stats">
            <span>
              <b>{cluster.teams_count}</b> команд
            </span>
            <span>
              <b>{cluster.analysts_count}</b> аналитиков
            </span>
            <span>
              <b>{cluster.documents_count}</b> документов
            </span>
          </div>
        </div>
      </div>

      <div className="zone-label">Команды кластера</div>
      <div className="org-grid">
        {cluster.teams.map((team) => (
          <Link key={team.id} to={`/teams/${team.id}`} className="team-card">
            <span className="team-card-head" style={{ background: clusterColorBg(cluster.color, cluster.id) }}>
              <span className="team-card-name">{team.name}</span>
              <span className="team-card-count">{team.analysts_count}</span>
            </span>
            {team.description && <span className="team-card-desc">{team.description}</span>}
          </Link>
        ))}
        {cluster.teams.length === 0 && (
          <div className="panel table-empty">В кластере ещё нет команд.</div>
        )}
      </div>
    </section>
  );
}
