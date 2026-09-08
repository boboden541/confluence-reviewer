import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type TemplateCard } from "../api";
import { Breadcrumbs } from "../Breadcrumbs";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString("ru-RU") : "";
}

/**
 * Список шаблонов требований: карточки в горизонтальной ленте (риск №1 —
 * при большом числе шаблонов лента листается, а не растёт вниз), карточка
 * «+» для создания, архив отдельным блоком. Пометка «по умолчанию»
 * переключается здесь же — она предвыбирает шаблон в диалоге проверки.
 */
export default function TemplatesPage() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<TemplateCard[] | null>(null);
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
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">🧩</span>Шаблоны требований
          </h1>
          <div className="page-meta">
            {active.length === 0
              ? "активных шаблонов нет — создайте первый или верните из архива"
              : `${active.length} ${active.length === 1 ? "шаблон" : "шаблонов"} · активная версия каждого применяется к проверкам, которые её выбрали`}
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="tpl-cards">
        {active.map((card) => (
          <div
            key={card.id}
            className={`tpl-card${card.is_default ? " selected" : ""}`}
            onClick={() => navigate(`/templates/${card.id}`)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") navigate(`/templates/${card.id}`);
            }}
            aria-label={`Открыть шаблон «${card.name}»`}
          >
            <div className="glyph">🧩</div>
            <div className="name">
              {card.name} {card.is_default && <span className="lozenge new">по умолчанию</span>}
            </div>
            <div className="meta">
              {card.section_count} разделов · версия №{card.active_version_id}
              {card.active_version_created_at && ` · ${formatDate(card.active_version_created_at)}`}
              {card.title_marker && (
                <>
                  <br />
                  маркер названия: «{card.title_marker}»
                </>
              )}
            </div>
            <div className="row">
              <button
                className="btn subtle small"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/templates/${card.id}`);
                }}
              >
                Открыть
              </button>
              {!card.is_default && (
                <button
                  className="btn subtle small"
                  disabled={busyId === card.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    action(card, "default");
                  }}
                >
                  По умолчанию
                </button>
              )}
              <button
                className="btn subtle small"
                disabled={busyId === card.id}
                onClick={(e) => {
                  e.stopPropagation();
                  action(card, "archive");
                }}
              >
                В архив
              </button>
            </div>
          </div>
        ))}

        <button className="tpl-new" onClick={() => navigate("/templates/new")} title="Создать шаблон">
          <span className="plus">+</span>
          Создать<br />шаблон
        </button>
      </div>
      <div className="scroll-hint">
        → лента листается горизонтально, когда шаблонов много; создание — карточка «+» в конце
      </div>

      {archived.length > 0 && (
        <>
          <div className="archive-head">Архив</div>
          <div className="tpl-cards">
            {archived.map((card) => (
              <div
                key={card.id}
                className="tpl-card archived"
                onClick={() => navigate(`/templates/${card.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") navigate(`/templates/${card.id}`);
                }}
                aria-label={`Открыть архивный шаблон «${card.name}»`}
              >
                <div className="glyph">🧩</div>
                <div className="name">
                  {card.name} <span className="lozenge moved">в архиве</span>
                </div>
                <div className="meta">
                  {card.section_count} разделов · версия №{card.active_version_id}
                  <br />
                  не участвует в выборе при проверке
                </div>
                <div className="row">
                  <button
                    className="btn subtle small"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/templates/${card.id}`);
                    }}
                  >
                    Открыть
                  </button>
                  <button
                    className="btn subtle small"
                    disabled={busyId === card.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      action(card, "restore");
                    }}
                  >
                    Вернуть из архива
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="muted" style={{ marginTop: "1.2rem" }}>
        Архивация скрывает шаблон из диалога проверки, но карточка, история версий и прошлые отчёты
        остаются. Пометка «по умолчанию» предвыбирает шаблон в диалоге проверки.
      </p>
    </section>
  );
}
