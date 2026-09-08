import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type AiCriterion } from "../api";
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
  const [items, setItems] = useState<AiCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [creating, setCreating] = useState<CritForm>(EMPTY_FORM);
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
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">✅</span>Критерии ИИ-проверок
          </h1>
          <div className="page-meta">
            {active.length} активных · из них собирается промт проверки наполнения
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="panel">
        <h2>Новый критерий</h2>
        <p className="muted">
          Название увидит руководитель в блоке оценок; промт — инструкция для ИИ,
          станет блоком в собранном промте проверки.
        </p>
        <div className="crit-form">
          <input
            value={creating.name}
            onChange={(e) => setCreating((f) => ({ ...f, name: e.target.value }))}
            placeholder="Название, например: Трассировка требований"
            aria-label="Название критерия"
          />
          <textarea
            value={creating.prompt}
            onChange={(e) => setCreating((f) => ({ ...f, prompt: e.target.value }))}
            placeholder="Промт-инструкция: что именно ИИ должен проверять в документе"
            aria-label="Промт критерия"
            rows={3}
          />
          <div className="crit-form-foot">
            <button
              className="btn primary"
              onClick={add}
              disabled={adding || !creating.name.trim() || creating.prompt.trim().length < 10}
            >
              {adding ? "Добавление…" : "+ Добавить критерий"}
            </button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Активные критерии</h2>
        {active.length === 0 && (
          <p className="muted">
            Активных критериев нет — проверка наполнения не запустится, пока не
            добавите или не восстановите хотя бы один.
          </p>
        )}
        {active.map((crit) => (
          <div key={crit.id} className="crit-item">
            {editing?.id === crit.id ? (
              <div className="crit-edit">
                <input
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                  aria-label={`Название критерия «${crit.name}»`}
                />
                <textarea
                  value={editing.prompt}
                  onChange={(e) => setEditing({ ...editing, prompt: e.target.value })}
                  aria-label={`Промт критерия «${crit.name}»`}
                  rows={3}
                />
                <div className="alert warn">
                  ⚠️ Переименование увидят и прошлые оценки в статистике руководителя —
                  снапшота названий на момент оценки нет. Код критерия не меняется.
                </div>
                <div className="crit-form-foot">
                  <button
                    className="btn primary"
                    onClick={saveEdit}
                    disabled={busyId === crit.id || !editing.name.trim() || editing.prompt.trim().length < 10}
                  >
                    Сохранить
                  </button>
                  <button
                    className="btn subtle"
                    onClick={() => setEditing(null)}
                    disabled={busyId === crit.id}
                  >
                    Отмена
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="crit-head">
                  <span className="crit-name">{crit.name}</span>
                  <code className="crit-code">{crit.code}</code>
                </div>
                <div className="crit-prompt">{crit.prompt}</div>
                <div className="crit-actions">
                  <button
                    className="btn ghost small"
                    onClick={() => setEditing({ id: crit.id, name: crit.name, prompt: crit.prompt })}
                  >
                    ✏️ Изменить
                  </button>
                  <button
                    className="btn ghost small danger"
                    onClick={() => archive(crit)}
                    disabled={busyId === crit.id}
                  >
                    📦 В архив
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {archived.length > 0 && (
        <div className="panel">
          <h2>Архив ({archived.length})</h2>
          <p className="muted">
            Не попадают в новые проверки; сохраняются в статистике оценок. Восстановимы.
          </p>
          {archived.map((crit) => (
            <div key={crit.id} className="crit-item archived">
              <div className="crit-head">
                <span className="crit-name">{crit.name}</span>
                <code className="crit-code">{crit.code}</code>
              </div>
              <div className="crit-prompt">{crit.prompt}</div>
              <div className="crit-actions">
                <button
                  className="btn ghost small"
                  onClick={() => restore(crit)}
                  disabled={busyId === crit.id}
                >
                  ↩️ Восстановить
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
