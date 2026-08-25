import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, type BatchValidationRequest, type ValidationConfig } from "./api";

/**
 * Диалог настроек проверки перед запуском: выбор критериев (шаблон и/или
 * наполнение), шаблона требований и промта ИИ (предзаполнен стандартным).
 * Настройки действуют один запуск и нигде не сохраняются — каждый запуск
 * начинается со стандартных.
 */
export default function ValidationDialog({
  documentIds,
  force = false,
  onClose,
  onLaunched,
}: {
  documentIds: number[];
  /** true — перевалидировать безусловно (кнопка «Актуализировать») */
  force?: boolean;
  onClose: () => void;
  onLaunched: () => void;
}) {
  const [config, setConfig] = useState<ValidationConfig | null>(null);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  // критерии проверки: оба включены по умолчанию, минимум один обязателен
  const [checkTemplate, setCheckTemplate] = useState(true);
  const [checkAi, setCheckAi] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // конфиг грузится на каждое открытие: шаблон могли отредактировать
  useEffect(() => {
    let alive = true;
    api<ValidationConfig>("/api/validation-config")
      .then((cfg) => {
        if (!alive) return;
        setConfig(cfg);
        setTemplateId(cfg.templates.find((t) => t.is_default)?.id ?? cfg.templates[0]?.id ?? null);
        setPrompt(cfg.default_prompt);
      })
      .catch((exc) => {
        if (alive) setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить настройки");
      });
    return () => {
      alive = false;
    };
  }, []);

  // Esc закрывает диалог; фокус — на кнопку «Отмена», чтобы Enter не запустил проверку случайно
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const promptChanged = config !== null && prompt !== config.default_prompt;
  const n = documentIds.length;
  const noChecks = !checkTemplate && !checkAi;

  const launch = async () => {
    setBusy(true);
    setError("");
    try {
      // критерий снят — его настройки не отправляем
      const checks: Array<"template" | "ai"> = [
        ...(checkTemplate ? (["template"] as const) : []),
        ...(checkAi ? (["ai"] as const) : []),
      ];
      const payload: BatchValidationRequest = {
        document_ids: documentIds,
        force,
        checks,
        template_id: checkTemplate ? templateId : null,
        // стандартный промт не отправляем — бэкенд проверит идемпотентность
        ai_prompt: checkAi && promptChanged ? prompt : null,
      };
      await api("/api/documents/validate-batch", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onLaunched();
    } catch (exc) {
      setBusy(false);
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить проверку");
    }
  };

  // Портал в body: fixed-геометрия оверлея не должна зависеть от
  // содержащих блоков (анимация панели просмотра, transform-предки)
  return createPortal(
    <div
      className="overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Настройки проверки">
        <h2>Проверка документов</h2>
        <div className="sub">
          Будет проверено: <b>{n}</b>
          {force && " · повторно, даже если документы не менялись"}
        </div>

        {error && !config && <div className="alert error">{error}</div>}
        {!config && !error && <p className="muted">Загрузка…</p>}

        {config && (
          <>
            <div className="zone-label">Что проверить</div>
            <label className={checkTemplate ? "tpl selected" : "tpl"}>
              <input
                type="checkbox"
                checked={checkTemplate}
                onChange={(e) => setCheckTemplate(e.target.checked)}
              />
              <span>
                <span className="name">Соответствие шаблону</span>
                <div className="desc">
                  Структура разделов документа сверяется с шаблоном требований
                </div>
              </span>
            </label>
            <label className={checkAi ? "tpl selected" : "tpl"}>
              <input
                type="checkbox"
                checked={checkAi}
                onChange={(e) => setCheckAi(e.target.checked)}
              />
              <span>
                <span className="name">Наполнение (ИИ)</span>
                <div className="desc">
                  Полноту и качество содержимого проверяет ИИ по промту ниже
                </div>
              </span>
            </label>
            {noChecks && (
              <div className="alert error">Выберите хотя бы один критерий проверки</div>
            )}

            <div className={checkTemplate ? "" : "zone-off"}>
              <div className="zone-label">Шаблон требований</div>
              {config.templates.length === 0 && (
                <div className="alert error">
                  Шаблон требований не настроен — проверка невозможна
                </div>
              )}
              {config.templates.map((tpl) => (
                <label
                  key={tpl.id}
                  className={templateId === tpl.id ? "tpl selected" : "tpl"}
                >
                  <input
                    type="radio"
                    name="validation-template"
                    checked={templateId === tpl.id}
                    onChange={() => setTemplateId(tpl.id)}
                  />
                  <span>
                    <span className="name">
                      {tpl.name}{" "}
                      {tpl.is_default && <span className="lozenge new">по умолчанию</span>}
                    </span>
                    <div className="desc">
                      {tpl.section_count} разделов
                      {tpl.description ? ` · ${tpl.description}` : ""}
                    </div>
                  </span>
                </label>
              ))}
              <label className="tpl disabled" title="Появится, когда в системе будет несколько шаблонов">
                <input type="radio" disabled />
                <span>
                  <span className="name">
                    Другие шаблоны <span className="lozenge moved">скоро</span>
                  </span>
                  <div className="desc">
                    Список расширится без изменения интерфейса, когда шаблонов станет несколько
                  </div>
                </span>
              </label>
            </div>

            <div className={checkAi ? "" : "zone-off"}>
              <div className="zone-label">Промт ИИ-проверки</div>
              <div className="prompt-note">
                Предзаполнен стандартным промтом. Меняйте, если для этой партии нужен другой
                фокус. Изменение действует <b>только на этот запуск</b> и никуда не сохраняется.
              </div>
              <textarea
                className="prompt"
                spellCheck={false}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                aria-label="Промт ИИ-проверки"
              />
              <div className="prompt-toolbar">
                {promptChanged && (
                  <>
                    <button type="button" className="btn ghost" onClick={() => setPrompt(config.default_prompt)}>
                      ⟲ Вернуть стандартный промт
                    </button>
                    <span className="lozenge moved">промт изменён — применится к этому запуску</span>
                  </>
                )}
              </div>
            </div>

            {error && <div className="alert error">{error}</div>}

            <div className="dialog-foot">
              <button type="button" className="btn subtle" ref={cancelRef} onClick={onClose}>
                Отмена
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={launch}
                disabled={
                  busy ||
                  noChecks ||
                  // шаблон выбран, но не настроен — запуск невозможен;
                  // без шаблонной проверки запуск возможен (только наполнение)
                  (checkTemplate && config.templates.length === 0) ||
                  (checkAi && !prompt.trim())
                }
              >
                <span aria-hidden="true">▶</span> Запустить проверку — {n} док.
              </button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
