import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type RegistrationRequest, type Role } from "../api";
import { Breadcrumbs } from "../Breadcrumbs";

/** Заявки на доступ (только God): новые — с выбором роли и решением,
 *  ниже — история; отклонённую можно вернуть в новые. */

const BADGE: Record<RegistrationRequest["status"], { text: string; cls: string }> = {
  pending: { text: "ожидает", cls: "badge-warn" },
  approved: { text: "доступ открыт", cls: "badge-ok" },
  rejected: { text: "отклонена", cls: "badge-danger" },
};

export default function RequestsPage() {
  const [requests, setRequests] = useState<RegistrationRequest[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [roleChoice, setRoleChoice] = useState<Record<number, number>>({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async () => {
    try {
      const [list, roleList] = await Promise.all([
        api<RegistrationRequest[]>("/api/auth/requests"),
        api<Role[]>("/api/roles"),
      ]);
      setRequests(list);
      setRoles(roleList);
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить заявки");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (id: number, action: "approve" | "reject" | "reopen", roleId?: number) => {
    setError("");
    setInfo("");
    try {
      await api(`/api/auth/requests/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify(action === "approve" ? { role_id: roleId } : {}),
      });
      setInfo(
        action === "approve"
          ? "Заявка одобрена — пользователь может войти своим токеном"
          : action === "reject"
            ? "Заявка отклонена"
            : "Заявка возвращена в новые",
      );
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось обработать заявку");
    }
  };

  const pending = requests.filter((r) => r.status === "pending");
  const history = requests.filter((r) => r.status !== "pending");

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Заявки на доступ" }]} />

      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">📥</span>Заявки на доступ
          </h1>
          <div className="page-meta">
            Новых заявок: {pending.length}. Одобренный входит в сервис своим токеном
            Confluence.
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="panel" style={{ padding: 0 }}>
        {pending.map((request) => (
          <div key={request.id} className="request-row">
            <div className="request-main">
              <span className="request-name">{request.full_name}</span>
              <span className="badge badge-warn">ожидает</span>
              <div className="request-sub">
                {request.email} · логин {request.confluence_login}
              </div>
            </div>
            <select
              aria-label={`Роль для ${request.full_name}`}
              value={roleChoice[request.id] ?? roles.find((r) => r.name === "Lead")?.id ?? ""}
              onChange={(e) =>
                setRoleChoice((prev) => ({ ...prev, [request.id]: Number(e.target.value) }))
              }
            >
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  Роль: {role.name}
                </option>
              ))}
            </select>
            <button
              className="btn small primary"
              onClick={() => decide(request.id, "approve", roleChoice[request.id])}
            >
              ✓ Принять
            </button>
            <button className="btn small danger" onClick={() => decide(request.id, "reject")}>
              ✕ Отклонить
            </button>
          </div>
        ))}
        {pending.length === 0 && <div className="request-empty">Новых заявок нет</div>}
      </div>

      {history.length > 0 && (
        <>
          <div className="zone-label">История решений</div>
          <div className="panel" style={{ padding: 0 }}>
            {history.map((request) => (
              <div key={request.id} className="request-row">
                <div className="request-main">
                  <span className="request-name">
                    {request.full_name}{" "}
                    <span className={`badge ${BADGE[request.status].cls}`}>
                      {BADGE[request.status].text}
                    </span>
                  </span>
                  <div className="request-sub">
                    {request.email} · роль:{" "}
                    {roles.find((r) => r.id === request.role_id)?.name ?? "—"}
                    {request.decided_at
                      ? ` · решение ${new Date(request.decided_at + "Z").toLocaleDateString("ru-RU")}`
                      : ""}
                  </div>
                </div>
                {request.status === "rejected" && (
                  <button className="btn small subtle" onClick={() => decide(request.id, "reopen")}>
                    ↺ Вернуть в новые
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
