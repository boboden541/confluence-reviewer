import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Analyst, type Cluster, type ClusterInput } from "../api";
import { CLUSTER_PALETTE, clusterColor, clusterColorBg, initials } from "../orgUi";

/** Главная страница: карта кластеров (цветные плитки с командами и
 *  счётчиками) и секция «Без команды» — аналитики вне структуры. */

const EMPTY_FORM: ClusterInput = { name: "", description: "", color: null };

export default function ClustersPage() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [freeAnalysts, setFreeAnalysts] = useState<Analyst[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  // модалка кластера: editing=null → скрыта; id=null → создание
  const [editing, setEditing] = useState<{ id: number | null; form: ClusterInput } | null>(null);
  const [saving, setSaving] = useState(false);

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

  const saveCluster = async () => {
    if (!editing || !editing.form.name.trim()) return;
    setSaving(true);
    setError("");
    try {
      const payload: ClusterInput = {
        name: editing.form.name.trim(),
        description: editing.form.description?.trim() || null,
        color: editing.form.color,
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
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить кластер");
    }
  };

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <span>Ревью требований</span>
        <span className="sep">/</span>
        <span className="crumb-current">Кластеры</span>
      </nav>

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

      <div className="cluster-grid">
        {clusters.map((cluster) => {
          const color = clusterColor(cluster.color, cluster.id);
          return (
            <div key={cluster.id} className="cluster-card" style={{ borderTopColor: color }}>
              <div className="cluster-card-head">
                <span className="cluster-glyph" style={{ background: color }} aria-hidden="true">
                  {initials(cluster.name)}
                </span>
                <div className="cluster-card-title">
                  <Link to={`/clusters/${cluster.id}`}>{cluster.name}</Link>
                  {cluster.description && (
                    <div className="cluster-card-desc">{cluster.description}</div>
                  )}
                </div>
                <div className="cluster-card-actions">
                  <button className="btn small subtle" onClick={() => openEdit(cluster)}>
                    <span aria-hidden="true">✎</span> Изменить
                  </button>
                  <button className="btn small subtle danger" onClick={() => deleteCluster(cluster)}>
                    <span aria-hidden="true">🗑</span> Удалить
                  </button>
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
              <div className="cluster-card-map">
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
                <Link to={`/clusters/${cluster.id}`} className="cluster-team-add">
                  ＋ команда
                </Link>
              </div>
            </div>
          );
        })}
        {!loading && clusters.length === 0 && (
          <div className="panel table-empty">
            Кластеров ещё нет — создайте первый и заведите в нём команды.
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
        <div
          className="modal-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setEditing(null);
          }}
        >
          <div className="modal-panel" role="dialog" aria-label="Кластер">
            <div className="modal-head">
              <h2>{editing.id === null ? "Новый кластер" : "Редактирование кластера"}</h2>
              <button className="modal-close" onClick={() => setEditing(null)} aria-label="Закрыть">
                ✕
              </button>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void saveCluster();
              }}
            >
              <div className="modal-body">
                <span className="field">
                  <label htmlFor="cluster-name">Название *</label>
                  <input
                    id="cluster-name"
                    className="text-input"
                    placeholder="Например: Билетный бизнес"
                    value={editing.form.name}
                    onChange={(e) =>
                      setEditing({ ...editing, form: { ...editing.form, name: e.target.value } })
                    }
                    autoFocus
                  />
                </span>
                <span className="field">
                  <label htmlFor="cluster-desc">Описание</label>
                  <textarea
                    id="cluster-desc"
                    className="text-input"
                    rows={3}
                    placeholder="Для чего этот кластер, что в него входит"
                    value={editing.form.description ?? ""}
                    onChange={(e) =>
                      setEditing({
                        ...editing,
                        form: { ...editing.form, description: e.target.value },
                      })
                    }
                  />
                </span>
                <span className="field">
                  <label>Цвет</label>
                  <div className="swatches" role="radiogroup" aria-label="Цвет кластера">
                    {CLUSTER_PALETTE.map((hex) => (
                      <button
                        key={hex}
                        type="button"
                        role="radio"
                        aria-label={hex}
                        aria-checked={editing.form.color === hex}
                        className={`swatch${editing.form.color === hex ? " active" : ""}`}
                        style={{ background: hex }}
                        onClick={() => setEditing({ ...editing, form: { ...editing.form, color: hex } })}
                      />
                    ))}
                  </div>
                </span>
              </div>
              <div className="modal-foot">
                <button className="btn subtle" type="button" onClick={() => setEditing(null)}>
                  Отмена
                </button>
                <button className="btn primary" type="submit" disabled={saving || !editing.form.name.trim()}>
                  {saving ? "Сохранение…" : "Сохранить"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}
