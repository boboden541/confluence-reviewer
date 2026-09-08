import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Fuse from "fuse.js";
import { api, ApiError, notifyOrgChanged, type Analyst, type Cluster, type ClusterInput, type TeamInput } from "../api";
import { clusterColor, clusterColorBg, initials } from "../orgUi";
import { useCan } from "../userContext";
import { ClusterModal } from "../ClusterModal";
import { TeamModal } from "../TeamModal";
import { Breadcrumbs } from "../Breadcrumbs";

/** Главная страница: карта кластеров (цветные плитки с командами и
 *  счётчиками) и секция «Без команды» — аналитики вне структуры.
 *  Карточка кластера кликабельна целиком; поиск — нечёткий (fuse.js),
 *  фильтрует по названию, описанию и названиям команд. */

const EMPTY_FORM: ClusterInput = { name: "", description: "", color: null };

export default function ClustersPage() {
  const navigate = useNavigate();
  const canDelete = useCan()("delete");
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [freeAnalysts, setFreeAnalysts] = useState<Analyst[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  // модалка кластера: editing=null → скрыта; id=null → создание
  const [editing, setEditing] = useState<{ id: number | null; form: ClusterInput } | null>(null);
  const [saving, setSaving] = useState(false);
  // попап создания команды прямо с карточки кластера
  const [teamModalFor, setTeamModalFor] = useState<Cluster | null>(null);
  const [teamForm, setTeamForm] = useState<TeamInput>({ name: "", description: "" });

  const load = useCallback(async () => {
    try {
      const [clusterList, analysts] = await Promise.all([
        api<Cluster[]>("/api/clusters"),
        api<Analyst[]>("/api/analysts"),
      ]);
      setClusters(clusterList);
      setFreeAnalysts(analysts.filter((a) => a.team_id === null));
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить кластеры");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // нечёткий поиск: опечатки и неполные слова допустимы; ищем и по командам
  const fuse = useMemo(
    () =>
      new Fuse(clusters, {
        keys: ["name", "description", "teams.name"],
        threshold: 0.38,
        ignoreLocation: true,
      }),
    [clusters],
  );
  const visibleClusters = query.trim()
    ? fuse.search(query.trim()).map((r) => r.item)
    : clusters;

  const openCreate = () => setEditing({ id: null, form: { ...EMPTY_FORM } });
  const openEdit = (cluster: Cluster) =>
    setEditing({
      id: cluster.id,
      form: {
        name: cluster.name,
        description: cluster.description ?? "",
        color: cluster.color,
      },
    });

  const saveClusterWith = async (form: ClusterInput) => {
    if (!editing || !form.name.trim()) return;
    setEditing({ ...editing, form });
    setSaving(true);
    setError("");
    try {
      const payload: ClusterInput = {
        name: form.name.trim(),
        description: form.description?.trim() || null,
        color: form.color,
      };
      if (editing.id === null) {
        await api("/api/clusters", { method: "POST", body: JSON.stringify(payload) });
        setInfo(`Кластер «${payload.name}» создан`);
      } else {
        await api(`/api/clusters/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setInfo("Кластер сохранён");
      }
      setEditing(null);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить кластер");
    } finally {
      setSaving(false);
    }
  };

  const deleteCluster = async (cluster: Cluster) => {
    const note = cluster.teams_count
      ? ` Сначала удалите его команды (${cluster.teams_count}).`
      : "";
    if (!window.confirm(`Удалить кластер «${cluster.name}»?${note}`)) return;
    setError("");
    setInfo("");
    try {
      await api(`/api/clusters/${cluster.id}`, { method: "DELETE" });
      setInfo(`Кластер «${cluster.name}» удалён`);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить кластер");
    }
  };

  // создание команды прямо с карты кластеров
  const createTeam = async (form: TeamInput) => {
    if (!teamModalFor || !form.name.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api("/api/teams", {
        method: "POST",
        body: JSON.stringify({
          cluster_id: teamModalFor.id,
          name: form.name.trim(),
          description: form.description?.trim() || null,
        }),
      });
      setInfo(`Команда «${form.name.trim()}» создана в кластере «${teamModalFor.name}»`);
      setTeamModalFor(null);
      setTeamForm({ name: "", description: null });
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось создать команду");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Кластеры" }]} />

      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">🗂</span>Кластеры
          </h1>
          <div className="page-meta">
            {clusters.length} кластеров ·{" "}
            {clusters.reduce((acc, c) => acc + c.analysts_count, 0)} аналитиков в командах ·{" "}
            {freeAnalysts.length} без команды
          </div>
        </div>
        <div className="head-actions">
          <button className="btn primary" onClick={openCreate}>
            <span aria-hidden="true">＋</span> Новый кластер
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}
      {loading && <p className="muted">Загрузка…</p>}

      {clusters.length > 0 && (
        <div className="filter-row">
          <input
            className="text-input filter-input"
            placeholder="Поиск кластеров и команд — нечёткий, опечатки допустимы"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск кластеров"
          />
          {query && (
            <button className="btn subtle" onClick={() => setQuery("")} aria-label="Очистить поиск">
              ✕
            </button>
          )}
        </div>
      )}

      <div className="cluster-grid">
        {visibleClusters.map((cluster) => {
          const color = clusterColor(cluster.color, cluster.id);
          return (
            <div
              key={cluster.id}
              className="cluster-card clickable"
              style={{ borderTopColor: color }}
              role="link"
              tabIndex={0}
              aria-label={`Кластер ${cluster.name}`}
              onClick={() => navigate(`/clusters/${cluster.id}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  navigate(`/clusters/${cluster.id}`);
                }
              }}
            >
              <div className="cluster-card-head">
                <span className="cluster-glyph" style={{ background: color }} aria-hidden="true">
                  {initials(cluster.name)}
                </span>
                <div className="cluster-card-title">
                  <span className="cluster-card-name">{cluster.name}</span>
                  {cluster.description && (
                    <div className="cluster-card-desc">{cluster.description}</div>
                  )}
                </div>
                <div className="cluster-card-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="btn small subtle" onClick={() => openEdit(cluster)}>
                    <span aria-hidden="true">✎</span> Изменить
                  </button>
                  {canDelete && (<button className="btn small subtle danger" onClick={() => deleteCluster(cluster)}>
                    <span aria-hidden="true">🗑</span> Удалить
                  </button>)}
                </div>
              </div>
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
              <div className="cluster-card-map" onClick={(e) => e.stopPropagation()}>
                {cluster.teams.map((team) => (
                  <Link
                    key={team.id}
                    to={`/teams/${team.id}`}
                    className="cluster-team-chip"
                    style={{ color, background: clusterColorBg(cluster.color, cluster.id) }}
                  >
                    {team.name}
                    <em>{team.analysts_count}</em>
                  </Link>
                ))}
                <button
                  className="cluster-team-add"
                  onClick={() => {
                    setTeamForm({ name: "", description: "" });
                    setTeamModalFor(cluster);
                  }}
                >
                  ＋ команда
                </button>
              </div>
            </div>
          );
        })}
        {!loading && clusters.length === 0 && (
          <div className="panel table-empty">
            Кластеров ещё нет — создайте первый и заведите в нём команды.
          </div>
        )}
        {!loading && clusters.length > 0 && visibleClusters.length === 0 && (
          <div className="panel table-empty">
            По запросу «{query}» кластеров не найдено.
          </div>
        )}
      </div>

      {!loading && freeAnalysts.length > 0 && (
        <>
          <div className="zone-label">Без команды</div>
          <div className="people-grid">
            {freeAnalysts.map((analyst) => (
              <Link
                key={analyst.id}
                to={`/analysts/${analyst.id}`}
                className="person-card person-card-link"
              >
                <span className="p-avatar" style={{ background: "#8993A4" }} aria-hidden="true">
                  {initials(analyst.full_name)}
                </span>
                <span className="person-card-body">
                  <span className="person-card-name">{analyst.full_name}</span>
                  <span className="person-card-sub">
                    {analyst.email} · {analyst.documents_count} док.
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </>
      )}

      {editing && (
        <ClusterModal
          title={editing.id === null ? "Новый кластер" : "Редактирование кластера"}
          initial={editing.form}
          saving={saving}
          onSave={(form) => {
            setEditing({ ...editing, form });
            void saveClusterWith(form);
          }}
          onClose={() => setEditing(null)}
        />
      )}
      {teamModalFor && (
        <TeamModal
          title={`Новая команда в кластере «${teamModalFor.name}»`}
          initial={teamForm}
          saving={saving}
          onSave={(form) => {
            setTeamForm(form);
            void createTeam(form);
          }}
          onClose={() => setTeamModalFor(null)}
        />
      )}
    </section>
  );
}
