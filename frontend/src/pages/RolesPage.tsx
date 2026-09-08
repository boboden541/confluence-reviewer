import { useCallback, useEffect, useState } from "react";
import { api, ApiError, PERMISSION_LABELS, type Role } from "../api";
import { Breadcrumbs } from "../Breadcrumbs";
import { useCan, useMe } from "../userContext";

/** Роли и права: таблица «право × роль». God управляет (создание, галочки,
 *  переименование, удаление не назначенных ролей); остальные — просмотр. */

const PERMISSION_ORDER = [
  "checks",
  "comments",
  "templates.own",
  "criteria.own",
  "clusters.edit",
  "teams.edit",
  "analysts.edit",
  "lead.assign",
  "delete",
  "ai.default",
  "moderation",
  "roles.manage",
];

export default function RolesPage() {
  const me = useMe();
  const canManage = useCan()("roles.manage");
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    try {
      setRoles(await api<Role[]>("/api/roles"));
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить роли");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createRole = async () => {
    if (!newName.trim()) return;
    setError("");
    try {
      await api("/api/roles", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim(), permissions: ["checks"] }),
      });
      setInfo(`Роль «${newName.trim()}» создана`);
      setNewName("");
      setCreating(false);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось создать роль");
    }
  };

  const toggle = async (role: Role, permission: string) => {
    const next = role.permissions.includes(permission)
      ? role.permissions.filter((p) => p !== permission)
      : [...role.permissions, permission];
    // оптимистично: чекбокс переключается сразу, ошибка откатывает перезагрузкой
    try {
      await api(`/api/roles/${role.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: role.name, permissions: next }),
      });
      setRoles((prev) =>
        prev.map((r) => (r.id === role.id ? { ...r, permissions: next } : r)),
      );
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить роль");
      await load();
    }
  };

  const renameRole = async (role: Role) => {
    const name = window.prompt("Новое название роли", role.name);
    if (!name || name === role.name) return;
    try {
      await api(`/api/roles/${role.id}`, {
        method: "PUT",
        body: JSON.stringify({ name, permissions: role.permissions }),
      });
      setInfo("Роль переименована");
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось переименовать роль");
    }
  };

  const deleteRole = async (role: Role) => {
    if (!window.confirm(`Удалить роль «${role.name}»?`)) return;
    setError("");
    try {
      await api(`/api/roles/${role.id}`, { method: "DELETE" });
      setInfo(`Роль «${role.name}» удалена`);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось удалить роль");
    }
  };

  const ordered = [...roles].sort((a, b) => a.id - b.id);

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Роли и права" }]} />

      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">🛡</span>Роли и права
          </h1>
          <div className="page-meta">
            {canManage
              ? "Роль — столбец: добавляйте роли и настраивайте их права галочками."
              : "Просмотр матрицы прав (изменять может только администратор)."}
          </div>
        </div>
        {canManage && (
          <div className="head-actions">
            {creating ? (
              <span className="role-create">
                <input
                  className="text-input"
                  placeholder="Название роли"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  aria-label="Название роли"
                  autoFocus
                />
                <button className="btn small primary" onClick={createRole}>
                  Создать
                </button>
                <button className="btn small subtle" onClick={() => setCreating(false)}>
                  Отмена
                </button>
              </span>
            ) : (
              <button className="btn primary" onClick={() => setCreating(true)}>
                <span aria-hidden="true">＋</span> Новая роль
              </button>
            )}
          </div>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="roles-table-wrap">
        <table className="perms">
          <thead>
            <tr>
              <th>Право</th>
              {ordered.map((role) => (
                <th key={role.id} style={{ width: 140 }}>
                  {role.name}
                  {role.is_system ? (
                    <span className="lock-note"> · системная</span>
                  ) : (
                    canManage && (
                      <span className="role-controls">
                        <button
                          className="btn small subtle"
                          aria-label={`Переименовать роль ${role.name}`}
                          onClick={() => renameRole(role)}
                        >
                          ✎
                        </button>
                        <button
                          className="btn small subtle danger"
                          aria-label={`Удалить роль ${role.name}`}
                          onClick={() => deleteRole(role)}
                        >
                          🗑
                        </button>
                      </span>
                    )
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERMISSION_ORDER.map((permission) => (
              <tr key={permission}>
                <td>{PERMISSION_LABELS[permission] ?? permission}</td>
                {ordered.map((role) => {
                  const allowed = role.is_system || role.permissions.includes(permission);
                  if (!canManage || role.is_system) {
                    return (
                      <td key={role.id} className={allowed ? "yes" : "no"}>
                        {allowed ? "✓" : "✕"}
                      </td>
                    );
                  }
                  return (
                    <td key={role.id}>
                      <input
                        type="checkbox"
                        checked={allowed}
                        aria-label={`${role.name}: ${PERMISSION_LABELS[permission]}`}
                        onChange={() => toggle(role, permission)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="page-meta" style={{ marginTop: 8 }}>
        God — системная роль со всеми правами. Роль нельзя удалить, пока она назначена
        пользователю. Права применяются к следующим запросам без перезапуска.
      </div>
      {me === null && <div className="alert error">Не удалось определить пользователя</div>}
    </section>
  );
}
