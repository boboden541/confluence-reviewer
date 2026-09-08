import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, notifyOrgChanged, type Team, type TeamInput } from "../api";
import { clusterColor, initials } from "../orgUi";
import { TeamModal } from "../TeamModal";
import { AddAnalystModal } from "../AddAnalystModal";
import { Breadcrumbs } from "../Breadcrumbs";

/** Экран команды: шапка с описанием, агрегированные домены участников и
 *  карточки аналитиков. Здесь же управление: редактирование/удаление
 *  команды, добавление и удаление участников. */
export default function TeamPage() {
  const { teamId } = useParams();
  const navigate = useNavigate();
  const id = Number(teamId);
  const [team, setTeam] = useState<Team | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [editingTeam, setEditingTeam] = useState<TeamInput | null>(null);
  const [addingAnalyst, setAddingAnalyst] = useState(false);
  const [busy, setBusy] = useState(false);

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

  const saveTeam = async (form: TeamInput) => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/teams/${id}`, { method: "PUT", body: JSON.stringify(form) });
      setInfo("Команда сохранена");
      setEditingTeam(null);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить команду");
    } finally {
      setBusy(false);
    }
  };

  const deleteTeam = async () => {
    if (!team) return;
    if (!window.confirm(`Удалить команду «${team.name}»? Аналитики останутся без команды.`)) return;
    setError("");
    try {
      await api(`/api/teams/${id}`, { method: "DELETE" });
      notifyOrgChanged();
      navigate(`/clusters/${team.cluster_id}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить команду");
    }
  };

  const addAnalyst = async (analystIds: number[], domains: string[] | null) => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/teams/${id}/analysts`, {
        method: "POST",
        body: JSON.stringify({ analyst_ids: analystIds, domains }),
      });
      setInfo(analystIds.length > 1 ? `Добавлено аналитиков: ${analystIds.length}` : "Аналитик добавлен в команду");
      setAddingAnalyst(false);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось добавить аналитиков");
    } finally {
      setBusy(false);
    }
  };

  const removeAnalyst = async (analystId: number, analystName: string) => {
    if (!window.confirm(`Убрать «${analystName}» из команды? Документы и оценки останутся.`)) return;
    setError("");
    setInfo("");
    try {
      await api(`/api/teams/${id}/analysts/${analystId}`, { method: "DELETE" });
      setInfo(`«${analystName}» убран из команды`);
      notifyOrgChanged();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось убрать аналитика");
    }
  };

  if (!team) {
    return error ? <div className="alert error">{error}</div> : <p className="muted">Загрузка…</p>;
  }

  const clusterHue = clusterColor(team.cluster_color, team.cluster_id);

  return (
    <section className="page">
      <Breadcrumbs
        items={[
          { label: "Кластеры", to: "/clusters" },
          { label: team.cluster_name, to: `/clusters/${team.cluster_id}` },
          { label: `Команда ${team.name}` },
        ]}
      />

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
        <div className="head-actions">
          <button
            className="btn subtle"
            onClick={() => setEditingTeam({ name: team.name, description: team.description ?? "" })}
          >
            <span aria-hidden="true">✎</span> Редактировать
          </button>
          <button className="btn subtle danger" onClick={deleteTeam}>
            Удалить
          </button>
          <button className="btn primary" onClick={() => setAddingAnalyst(true)}>
            <span aria-hidden="true">＋</span> Добавить аналитика
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

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
          <div key={analyst.id} className="person-card">
            <span className="p-avatar" style={{ background: clusterHue }} aria-hidden="true">
              {initials(analyst.full_name)}
            </span>
            <span className="person-card-body">
              <Link className="person-card-name" to={`/analysts/${analyst.id}`}>
                {analyst.full_name}
              </Link>
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
            <span className="person-card-actions">
              <button
                className="btn small subtle danger"
                onClick={() => removeAnalyst(analyst.id, analyst.full_name)}
              >
                Убрать
              </button>
            </span>
          </div>
        ))}
        {team.analysts.length === 0 && (
          <div className="panel table-empty">В команде ещё нет аналитиков — добавьте первого.</div>
        )}
      </div>

      {editingTeam && (
        <TeamModal
          title={`Редактирование команды «${team.name}»`}
          initial={editingTeam}
          saving={busy}
          onSave={(form) => {
            setEditingTeam(form);
            void saveTeam(form);
          }}
          onClose={() => setEditingTeam(null)}
        />
      )}
      {addingAnalyst && (
        <AddAnalystModal
          teamName={team.name}
          memberIds={new Set(team.analysts.map((a) => a.id))}
          saving={busy}
          onSave={(analystId, domains) => void addAnalyst(analystId, domains)}
          onClose={() => setAddingAnalyst(false)}
        />
      )}
    </section>
  );
}
