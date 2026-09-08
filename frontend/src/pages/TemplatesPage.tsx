import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type TemplateCard } from "../api";
import { RegistryModal } from "../RegistryModal";
import { Breadcrumbs } from "../Breadcrumbs";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString("ru-RU") : "";
}

/** «Мои шаблоны» (по согласованному макету): сетка карточек — активные,
 *  затем архив отдельной секцией; «🌐 Из общего реестра» и «＋ Новый
 *  шаблон» в шапке. Удалить нельзя — только архив. */
export default function TemplatesPage() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<TemplateCard[] | null>(null);
  const [registryOpen, setRegistryOpen] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setCards(await api<TemplateCard[]>("/api/templates"));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить шаблоны");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const action = async (card: TemplateCard, path: "default" | "archive" | "restore") => {
    setBusyId(card.id);
    setError("");
    try {
      await api(`/api/templates/${card.id}/${path}`, { method: "POST" });
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Действие не удалось");
    } finally {
      setBusyId(null);
    }
  };

  if (cards === null) {
    return (
      <section className="page">
        {error && <div className="alert error">{error}</div>}
        {!error && <p className="muted">Загрузка шаблонов…</p>}
      </section>
    );
  }

  const active = cards.filter((c) => !c.is_archived);
  const archived = cards.filter((c) => c.is_archived);

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Настройка" }, { label: "Шаблоны требований" }]} />

      <div className="page-head" style={{ alignItems: "center" }}>
        <h1 className="page-title" style={{ marginRight: "auto" }}>
          <span className="title-icon">🧩</span>Мои шаблоны
        </h1>
        <div className="head-actions">
          <button className="btn registry-btn" onClick={() => setRegistryOpen(true)}>
            🌐 Из общего реестра
          </button>
          <button className="btn primary" onClick={() => navigate("/templates/new")}>
            ＋ Новый шаблон
          </button>
        </div>
      </div>
      <div className="page-meta" style={{ marginBottom: 14 }}>
        Проверки запускаются по вашим шаблонам. Удалить нельзя — только в архив.
      </div>

      {error && <div className="alert error">{error}</div>}

      {/* активные шаблоны: сетка карточек */}
      <div className="tpl-grid">
        {active.map((card) => (
          <div key={card.id} className="tpl-card">
            <div className="tpl-name">
              {card.name}
              {card.is_default && <span className="chip">по умолчанию</span>}
            </div>
            <div className="tpl-sub">
              v{card.active_version_id} · {card.section_count} разделов ·{" "}
              создан {formatDate(card.active_version_created_at)}
            </div>
            <div className="tpl-actions">
              <button className="btn btn-default small" onClick={() => navigate(`/templates/${card.id}`)}>
                Редактировать
              </button>
              {!card.is_default && (
                <button className="btn btn-default small" disabled={busyId === card.id} onClick={() => action(card, "default")}>
                  ⭐ По умолчанию
                </button>
              )}
              <button className="btn btn-danger small" disabled={busyId === card.id} onClick={() => action(card, "archive")}>
                В архив
              </button>
            </div>
          </div>
        ))}
        {active.length === 0 && (
          <div className="tpl-card" style={{ border: "2px dashed var(--border-subtle)", boxShadow: "none", display: "grid", placeItems: "center", minHeight: 90, color: "var(--text-subtlest)", cursor: "default" }}>
            Активных шаблонов нет — создайте или скопируйте из реестра
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
            {archived.map((card) => (
              <div key={card.id} className="tpl-card" style={{ opacity: 0.75 }}>
                <div className="tpl-name">{card.name}</div>
                <div className="tpl-sub">
                  в архиве с {formatDate(card.active_version_created_at)} · {card.section_count} разделов
                </div>
                <div className="tpl-actions">
                  <button className="btn btn-default small" disabled={busyId === card.id} onClick={() => action(card, "restore")}>
                    ↺ Восстановить
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {registryOpen && (
        <RegistryModal
          title="🌐 Общий реестр шаблонов"
          endpoint="/api/templates/registry"
          onCopy={async (entry) => {
            await api(`/api/templates/${entry.id}/copy`, { method: "POST" });
            await load();
          }}
          onClose={() => setRegistryOpen(false)}
        />
      )}
    </section>
  );
}
