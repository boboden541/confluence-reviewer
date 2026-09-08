import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Fuse from "fuse.js";
import {
  api,
  ApiError,
  notifyOrgChanged,
  type Analyst,
  type Cluster,
  type ClusterInput,
  type TeamInput,
} from "../api";
import { clusterColor, clusterColorBg, initials } from "../orgUi";
import { ClusterModal } from "../ClusterModal";
import { TeamModal } from "../TeamModal";
import { AddAnalystModal } from "../AddAnalystModal";
import { pushRecent } from "../recent";
import { Breadcrumbs } from "../Breadcrumbs";

/** Экран кластера: шапка с описанием и счётчиками, команды «колоннами»
 *  с составом (мини-карточки участников) и нечётким поиском по командам.
 *  Управление: редактирование/удаление кластера, создание/редактирование/
 *  удаление команд, пополнение команды прямо из карточки. */
export default function ClusterPage() {
  const { clusterId } = useParams();
  const navigate = useNavigate();
  const id = Number(clusterId);
  const [cluster, setCluster] = useState<Cluster | null>(null);
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [query, setQuery] = useState("");
  const [editingCluster, setEditingCluster] = useState<ClusterInput | null>(null);
  // teamModal: null — скрыта; id=null — создание новой команды
  const [teamModal, setTeamModal] = useState<{ id: number | null; form: TeamInput } | null>(null);
  // пополнение команды прямо из карточки
  const [addingFor, setAddingFor] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [clusterData, analystList] = await Promise.all([
        api<Cluster>(`/api/clusters/${id}`),
        api<Analyst[]>("/api/analysts"),
      ]);
      setCluster(clusterData);
      setAnalysts(analystList);
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить кластер");
    }
  }, [id]);

  useEffect(() => {
    setCluster(null);
    void load();
  }, [load]);

  // визит кластера попадает в «Недавние» на главной
  useEffect(() => {
    if (cluster) pushRecent("cluster", cluster.id, cluster.name);
  }, [cluster?.id, cluster?.name]);

  const membersByTeam = useMemo(() => {
    const map = new Map<number, Analyst[]>();
    analysts.forEach((a) => {
      if (a.team_id == null) return;
      const list = map.get(a.team_id);
      if (list) list.push(a);
      else map.set(a.team_id, [a]);
    });
    return map;
  }, [analysts]);

  // нечёткий поиск по командам: название, описание, ФИО участников
  const visibleTeams = useMemo(() => {
    if (!cluster) return [];
    const needle = query.trim();
    if (!needle) return cluster.teams;
    const fuse = new Fuse(
      cluster.teams.map((team) => ({
        team,
        members: (membersByTeam.get(team.id) ?? []).map((m) => m.full_name).join(" "),
      })),
      { keys: ["team.name", "team.description", "members"], threshold: 0.38, ignoreLocation: true },
    );
    return fuse.search(needle).map((r) => r.item.team);
  }, [cluster, query, membersByTeam]);

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
      navigate("/clusters");
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

  const addMembers = async (teamId: number, analystIds: number[], domains: string[] | null) => {
    setSaving(true);
    setError("");
    try {
      await api(`/api/teams/${teamId}/analysts`, {
        method: "POST",
        body: JSON.stringify({ analyst_ids: analystIds, domains }),
      });
      setInfo(analystIds.length > 1 ? `Добавлено аналитиков: ${analystIds.length}` : "Аналитик добавлен в команду");
      setAddingFor(null);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось добавить аналитиков");
    } finally {
      setSaving(false);
    }
  };

  if (!cluster) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  const color = clusterColor(cluster.color, cluster.id);
  const addingTeam = addingFor != null ? cluster.teams.find((t) => t.id === addingFor) ?? null : null;

  return (
    <section className="page">
      <Breadcrumbs
        items={[
          { label: "Кластеры", to: "/clusters" },
          { label: cluster.name },
        ]}
      />

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

      {cluster.teams.length > 0 && (
        <div className="filter-row">
          <input
            className="text-input filter-input"
            placeholder="Поиск команд — по названию, описанию и участникам (нечётко)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск команд"
          />
          {query && (
            <button className="btn subtle" onClick={() => setQuery("")} aria-label="Очистить поиск">
              ✕
            </button>
          )}
        </div>
      )}

      <div className="zone-label">Команды кластера</div>
      <div className="org-grid">
        {visibleTeams.map((team) => {
          const members = membersByTeam.get(team.id) ?? [];
          return (
            <div key={team.id} className="team-card team-card-static">
              <Link to={`/teams/${team.id}`} className="team-card-link">
                <span className="team-card-head" style={{ background: clusterColorBg(cluster.color, cluster.id) }}>
                  <span className="team-card-name">{team.name}</span>
                  <span className="team-card-count">{team.analysts_count}</span>
                </span>
                {team.description && <span className="team-card-desc">{team.description}</span>}
              </Link>
              <span className="team-members">
                {members.slice(0, 4).map((member) => (
                  <Link key={member.id} to={`/analysts/${member.id}`} className="member-chip">
                    <span className="t-avatar" style={{ background: color }} aria-hidden="true">
                      {initials(member.full_name)}
                    </span>
                    {member.full_name}
                  </Link>
                ))}
                {members.length > 4 && (
                  <Link to={`/teams/${team.id}`} className="member-chip more">
                    +{members.length - 4}
                  </Link>
                )}
                {members.length === 0 && <span className="muted member-empty">пока никого</span>}
              </span>
              <span className="team-card-actions" onClick={(e) => e.stopPropagation()}>
                <button
                  className="btn small subtle"
                  onClick={() => {
                    setAddingFor(team.id);
                  }}
                >
                  <span aria-hidden="true">＋</span> Участник
                </button>
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
          );
        })}
        {cluster.teams.length === 0 && (
          <div className="panel table-empty">В кластере ещё нет команд — добавьте первую.</div>
        )}
        {cluster.teams.length > 0 && visibleTeams.length === 0 && (
          <div className="panel table-empty">По запросу «{query}» команд не найдено.</div>
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
      {addingTeam && (
        <AddAnalystModal
          teamName={addingTeam.name}
          memberIds={new Set((membersByTeam.get(addingTeam.id) ?? []).map((a) => a.id))}
          saving={saving}
          onSave={(analystIds, domains) => void addMembers(addingTeam.id, analystIds, domains)}
          onClose={() => setAddingFor(null)}
        />
      )}
    </section>
  );
}
