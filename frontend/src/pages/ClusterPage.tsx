import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, notifyOrgChanged, type Cluster, type ClusterInput, type TeamInput } from "../api";
import { clusterColor, clusterColorBg } from "../orgUi";
import { ClusterModal } from "../ClusterModal";
import { TeamModal } from "../TeamModal";

/** Экран кластера: шапка с описанием и счётчиками, команды «колоннами».
 *  Здесь же управление: редактирование/удаление кластера, создание,
 *  редактирование и удаление команд. */
export default function ClusterPage() {
  const { clusterId } = useParams();
  const navigate = useNavigate();
  const id = Number(clusterId);
  const [cluster, setCluster] = useState<Cluster | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [editingCluster, setEditingCluster] = useState<ClusterInput | null>(null);
  // teamModal: null — скрыта; id=null — создание новой команды
  const [teamModal, setTeamModal] = useState<{ id: number | null; form: TeamInput } | null>(null);
  const [saving, setSaving] = useState(false);

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

  const saveCluster = async (form: ClusterInput) => {
    setSaving(true);
    setError("");
    try {
      await api(`/api/clusters/${id}`, { method: "PUT", body: JSON.stringify(form) });
      setInfo("Кластер сохранён");
      setEditingCluster(null);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить кластер");
    } finally {
      setSaving(false);
    }
  };

  const deleteCluster = async () => {
    if (!cluster) return;
    const note = cluster.teams_count
      ? ` Сначала удалите его команды (${cluster.teams_count}).`
      : "";
    if (!window.confirm(`Удалить кластер «${cluster.name}»?${note}`)) return;
    setError("");
    try {
      await api(`/api/clusters/${id}`, { method: "DELETE" });
      notifyOrgChanged();
      navigate("/");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить кластер");
    }
  };

  const saveTeam = async (form: TeamInput) => {
    if (!teamModal) return;
    setSaving(true);
    setError("");
    try {
      if (teamModal.id === null) {
        await api("/api/teams", {
          method: "POST",
          body: JSON.stringify({ cluster_id: id, ...form }),
        });
        setInfo(`Команда «${form.name}» создана`);
      } else {
        await api(`/api/teams/${teamModal.id}`, { method: "PUT", body: JSON.stringify(form) });
        setInfo("Команда сохранена");
      }
      setTeamModal(null);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить команду");
    } finally {
      setSaving(false);
    }
  };

  const deleteTeam = async (teamId: number, teamName: string) => {
    if (!window.confirm(`Удалить команду «${teamName}»? Аналитики останутся без команды.`)) return;
    setError("");
    setInfo("");
    try {
      await api(`/api/teams/${teamId}`, { method: "DELETE" });
      setInfo(`Команда «${teamName}» удалена`);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить команду");
    }
  };

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
        <div className="head-actions">
          <button className="btn subtle" onClick={() => setEditingCluster({
            name: cluster.name,
            description: cluster.description ?? "",
            color: cluster.color,
          })}>
            <span aria-hidden="true">✎</span> Редактировать
          </button>
          <button className="btn subtle danger" onClick={deleteCluster}>
            Удалить
          </button>
          <button className="btn primary" onClick={() => setTeamModal({ id: null, form: { name: "", description: "" } })}>
            <span aria-hidden="true">＋</span> Добавить команду
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="zone-label">Команды кластера</div>
      <div className="org-grid">
        {cluster.teams.map((team) => (
          <div key={team.id} className="team-card team-card-static">
            <Link to={`/teams/${team.id}`} className="team-card-link">
              <span className="team-card-head" style={{ background: clusterColorBg(cluster.color, cluster.id) }}>
                <span className="team-card-name">{team.name}</span>
                <span className="team-card-count">{team.analysts_count}</span>
              </span>
              {team.description && <span className="team-card-desc">{team.description}</span>}
            </Link>
            <span className="team-card-actions">
              <button
                className="btn small subtle"
                onClick={() => setTeamModal({ id: team.id, form: { name: team.name, description: team.description ?? "" } })}
              >
                <span aria-hidden="true">✎</span> Изменить
              </button>
              <button className="btn small subtle danger" onClick={() => deleteTeam(team.id, team.name)}>
                <span aria-hidden="true">🗑</span> Удалить
              </button>
            </span>
          </div>
        ))}
        {cluster.teams.length === 0 && (
          <div className="panel table-empty">В кластере ещё нет команд — добавьте первую.</div>
        )}
      </div>

      {editingCluster && (
        <ClusterModal
          title="Редактирование кластера"
          initial={editingCluster}
          saving={saving}
          onSave={(form) => {
            setEditingCluster(form);
            void saveCluster(form);
          }}
          onClose={() => setEditingCluster(null)}
        />
      )}
      {teamModal && (
        <TeamModal
          title={teamModal.id === null ? "Новая команда" : `Редактирование команды «${teamModal.form.name}»`}
          initial={teamModal.form}
          saving={saving}
          onSave={(form) => {
            setTeamModal({ ...teamModal, form });
            void saveTeam(form);
          }}
          onClose={() => setTeamModal(null)}
        />
      )}
    </section>
  );
}
