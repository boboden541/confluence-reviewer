import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type AiCriterion } from "../api";
import { RegistryModal } from "../RegistryModal";
import { Breadcrumbs } from "../Breadcrumbs";

/**
 * Справочник ИИ-критериев (раздел настроек): название + промт-инструкция.
 * Промт ИИ-проверки в диалоге запуска собирается из активных критериев;
 * удаление — архив: критерий выпадает из новых проверок, но остаётся в
 * статистике оценок и восстановим.
 */

interface CritForm {
  name: string;
  prompt: string;
}

const EMPTY_FORM: CritForm = { name: "", prompt: "" };

export default function CriteriaPage() {
  const [registryOpen, setRegistryOpen] = useState(false);
  const [items, setItems] = useState<AiCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [creating, setCreating] = useState<CritForm | null>(null);
  const [adding, setAdding] = useState(false);
  // правка конкретного критерия: id + поля формы (инлайн)
  const [editing, setEditing] = useState<CritForm & { id: number } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await api<AiCriterion[]>("/api/ai-criteria"));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить критерии");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    setAdding(true);
    setError("");
    setInfo("");
    try {
      await api<AiCriterion>("/api/ai-criteria", {
        method: "POST",
        body: JSON.stringify(creating),
      });
      setCreating(EMPTY_FORM);
      setInfo("Критерий добавлен — попадёт в следующие запуски проверки.");
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось добавить критерий");
    } finally {
      setAdding(false);
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    setBusyId(editing.id);
    setError("");
    setInfo("");
    try {
      await api<AiCriterion>(`/api/ai-criteria/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: editing.name, prompt: editing.prompt }),
      });
      setEditing(null);
      setInfo("Критерий обновлён. Правка промта меняет собранный промт следующих запусков.");
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить критерий");
    } finally {
      setBusyId(null);
    }
  };

  const archive = async (crit: AiCriterion) => {
    setBusyId(crit.id);
    setError("");
    setInfo("");
    try {
      await api<AiCriterion>(`/api/ai-criteria/${crit.id}`, { method: "DELETE" });
      setInfo(`Критерий «${crit.name}» в архиве: новые проверки его не используют.`);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось архивировать критерий");
    } finally {
      setBusyId(null);
    }
  };

  const restore = async (crit: AiCriterion) => {
    setBusyId(crit.id);
    setError("");
    setInfo("");
    try {
      await api<AiCriterion>(`/api/ai-criteria/${crit.id}/restore`, { method: "POST" });
      setInfo(`Критерий «${crit.name}» снова активен.`);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось восстановить критерий");
    } finally {
      setBusyId(null);
    }
  };


  const active = items.filter((c) => !c.is_archived);
  const archived = items.filter((c) => c.is_archived);

  if (loading) {
    return (
      <section className="page">
        <p className="muted">Загрузка критериев…</p>
      </section>
    );
  }

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Настройка" }, { label: "Критерии ИИ-проверок" }]} />

      <div className="page-head" style={{ alignItems: "center" }}>
        <h1 className="page-title" style={{ marginRight: "auto" }}>
          <span className="title-icon">✅</span>Мои критерии ИИ
        </h1>
        <div className="head-actions">
          <button className="btn registry-btn" onClick={() => setRegistryOpen(true)}>
            🌐 Из общего реестра
          </button>
          <button className="btn primary" onClick={() => setCreating(EMPTY_FORM)}>
            ＋ Новый критерий
          </button>
        </div>
      </div>
      <div className="page-meta" style={{ marginBottom: 14 }}>
        Из активных критериев собирается промт ИИ-проверки; по ним же руководитель
        ставит оценки. Удалить нельзя — только в архив.
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      {registryOpen && (
        <RegistryModal
          title="🌐 Общий реестр критериев"
          endpoint="/api/ai-criteria/registry"
          onCopy={async (entry) => {
            await api(`/api/ai-criteria/${entry.id}/copy`, { method: "POST" });
            await load();
          }}
          onClose={() => setRegistryOpen(false)}
        />
      )}

      {/* модалка создания/правки */}
      {(creating !== null || editing !== null) && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && (setCreating(null), setEditing(null))}>
          <div className="modal-panel" role="dialog" aria-label={editing ? "Правка критерия" : "Новый критерий"}>
            <div className="modal-head">
              <h2>{editing ? "Правка критерия" : "Новый критерий"}</h2>
              <button className="modal-close" onClick={() => { setCreating(null); setEditing(null); }} aria-label="Закрыть">✕</button>
            </div>
            <div className="modal-body">
              {(() => {
                const form = editing ?? creating;
                if (!form) return null;
                return (
                  <>
                  <span className="field">
                    <label htmlFor="crit-name">Название</label>
                    <input
                      id="crit-name"
                      className="text-input"
                      value={form.name}
                      onChange={(e) =>
                        editing
                          ? setEditing({ ...editing, name: e.target.value })
                          : setCreating({ name: e.target.value, prompt: e.target.value })
                      }
                      placeholder="Например: Трассировка требований"
                    />
                  </span>
                  <span className="field">
                    <label htmlFor="crit-prompt">Промт-инструкция</label>
                    <textarea
                      id="crit-prompt"
                      className="text-input"
                      rows={4}
                      value={form.prompt}
                      onChange={(e) =>
                        editing
                          ? setEditing({ ...editing, prompt: e.target.value })
                          : setCreating({ name: creating?.name ?? "", prompt: e.target.value })
                      }
                      placeholder="Что именно ИИ должен проверять в документе"
                    />
                  </span>
                  {editing && (
                    <div className="alert warn">
                      ⚠️ Переименование увидят и прошлые оценки в статистике — снапшота
                      названий нет. Код критерия не меняется.
                    </div>
                  )}
                  </>
                );
              })()}
            </div>
            <div className="modal-foot">
              <button className="btn subtle" type="button" onClick={() => { setCreating(null); setEditing(null); }}>
                Отмена
              </button>
              {editing ? (
                <button
                  className="btn primary"
                  onClick={saveEdit}
                  disabled={busyId === editing.id || !editing.name.trim() || editing.prompt.trim().length < 10}
                >
                  {busyId === editing.id ? "Сохранение…" : "Сохранить"}
                </button>
              ) : (
                <button
                  className="btn primary"
                  onClick={add}
                  disabled={adding || !creating || !creating.name.trim() || creating.prompt.trim().length < 10}
                >
                  {adding ? "Добавление…" : "Добавить критерий"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* активные критерии: сетка карточек */}
      <div className="tpl-grid">
        {active.map((crit) => (
          <div key={crit.id} className="tpl-card">
            <div className="tpl-name">{crit.name}</div>
            <code className="crit-code">{crit.code}</code>
            <div className="tpl-sub crit-preview" title={crit.prompt}>
              {crit.prompt}
            </div>
            <div className="tpl-actions">
              <button
                className="btn btn-default small"
                onClick={() => setEditing({ id: crit.id, name: crit.name, prompt: crit.prompt })}
              >
                Править
              </button>
              <button className="btn btn-danger small" disabled={busyId === crit.id} onClick={() => archive(crit)}>
                В архив
              </button>
            </div>
          </div>
        ))}
        {active.length === 0 && (
          <div className="tpl-card" style={{ border: "2px dashed var(--border-subtle)", boxShadow: "none", display: "grid", placeItems: "center", minHeight: 90, color: "var(--text-subtlest)", cursor: "default" }}>
            Активных критериев нет — ИИ-проверка не запустится
          </div>
        )}
      </div>

      {/* архив отдельной секцией */}
      {archived.length > 0 && (
        <>
          <div className="zone-label" style={{ marginTop: 26 }}>
            Архив ({archived.length})
          </div>
          <div className="tpl-grid">
            {archived.map((crit) => (
              <div key={crit.id} className="tpl-card" style={{ opacity: 0.75 }}>
                <div className="tpl-name">{crit.name}</div>
                <code className="crit-code">{crit.code}</code>
                <div className="tpl-sub crit-preview">{crit.prompt}</div>
                <div className="tpl-actions">
                  <button className="btn btn-default small" disabled={busyId === crit.id} onClick={() => restore(crit)}>
                    ↺ Восстановить
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

