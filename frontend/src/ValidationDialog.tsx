import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  api,
  ApiError,
  type BatchValidationRequest,
  type CriterionOption,
  type ValidationConfig,
} from "./api";

/** Сборка промта — та же схема, что на бэкенде (services.criteria.assemble_prompt):
 *  каркас + нумерованные блоки отмеченных критериев. */
export function assemblePrompt(
  head: string,
  criteria: CriterionOption[],
  tail: string,
): string {
  const blocks = criteria.map((c, i) => `${i + 1}. «${c.name}» — ${c.prompt}`);
  return head + blocks.join("\n") + tail;
}

/**
 * Диалог настроек проверки перед запуском: выбор критериев (шаблон и/или
 * наполнение), шаблона требований и ИИ-критериев. Промт ИИ под замком
 * собирается из отмеченных критериев живьём (снял галочку — блок исчез,
 * нумерация пересобралась); снятие замка замораживает текст и превращает
 * его в override на этот запуск. Настройки нигде не сохраняются — каждый
 * запуск начинается со стандартных.
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
  // отмеченные ИИ-критерии (все активные по умолчанию) и замок промта
  const [criteriaOn, setCriteriaOn] = useState<Set<number>>(new Set());
  const [promptLocked, setPromptLocked] = useState(true);
  // текст промта значим только при снятом замке (замороженная копия);
  // под замком textarea показывает собранное превью и пересобирается сама
  const [prompt, setPrompt] = useState("");
  // критерии проверки: оба включены по умолчанию, минимум один обязателен
  const [checkTemplate, setCheckTemplate] = useState(true);
  const [checkAi, setCheckAi] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  // конфиг грузится на каждое открытие: шаблон и критерии могли изменить
  useEffect(() => {
    let alive = true;
    api<ValidationConfig>("/api/validation-config")
      .then((cfg) => {
        if (!alive) return;
        setConfig(cfg);
        setTemplateId(cfg.templates.find((t) => t.is_default)?.id ?? cfg.templates[0]?.id ?? null);
        setCriteriaOn(new Set(cfg.criteria.map((c) => c.id)));
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

  // живое превью под замком: пересобирается на каждую смену галочек
  const selectedCriteria = useMemo(
    () => (config?.criteria ?? []).filter((c) => criteriaOn.has(c.id)),
    [config, criteriaOn],
  );
  const assembled = useMemo(
    () =>
      config
        ? assemblePrompt(config.prompt_head, selectedCriteria, config.prompt_tail)
        : "",
    [config, selectedCriteria],
  );

  const n = documentIds.length;
  const noChecks = !checkTemplate && !checkAi;
  const noCriteria = checkAi && (config?.criteria.length ?? 0) > 0 && criteriaOn.size === 0;

  const unlockPrompt = () => {
    // замораживаем текущее собранное превью — дальше текст редактируется руками
    setPrompt(assembled);
    setPromptLocked(false);
  };

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
        // под замком промт собирает бэкенд из критериев; строка — только override
        ai_prompt: checkAi && !promptLocked ? prompt : null,
        criterion_ids: checkAi ? [...criteriaOn] : null,
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
                  Полноту и качество содержимого проверяет ИИ по критериям ниже
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
              <div className="dlg-tpl-cards" role="radiogroup" aria-label="Шаблон для проверки">
                {config.templates.map((tpl) => (
                  <button
                    type="button"
                    key={tpl.id}
                    role="radio"
                    aria-checked={templateId === tpl.id}
                    className={`dlg-tpl${templateId === tpl.id ? " selected" : ""}`}
                    onClick={() => setTemplateId(tpl.id)}
                    title={tpl.description ?? undefined}
                  >
                    <span className="name">
                      {tpl.name}{" "}
                      {tpl.is_default && <span className="lozenge new">по умолчанию</span>}
                    </span>
                    <span className="meta">
                      {tpl.section_count} разделов
                      {tpl.description ? ` · ${tpl.description}` : ""}
                    </span>
                  </button>
                ))}
              </div>
              <div className="scroll-hint">
                → лента листается горизонтально, когда шаблонов много; архивные шаблоны в выборе не
                участвуют
              </div>
            </div>

            <div className={checkAi ? "" : "zone-off"}>
              <div className="zone-label">ИИ-критерии и промт</div>
              {config.criteria.length === 0 && (
                <div className="alert error">
                  Нет активных ИИ-критериев — добавьте их в разделе «Критерии ИИ-проверок»
                </div>
              )}
              {config.criteria.map((crit) => (
                <label key={crit.id} className={criteriaOn.has(crit.id) ? "tpl selected" : "tpl"}>
                  <input
                    type="checkbox"
                    checked={criteriaOn.has(crit.id)}
                    onChange={(e) =>
                      setCriteriaOn((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(crit.id);
                        else next.delete(crit.id);
                        return next;
                      })
                    }
                  />
                  <span>
                    <span className="name">{crit.name}</span>
                    {/* промт критерия одной строкой: полный текст — в тултипе
                        и в собранном промте ниже, карточки не раздуваем */}
                    <div className="desc clip" title={crit.prompt}>
                      {crit.prompt}
                    </div>
                  </span>
                </label>
              ))}
              {noCriteria && (
                <div className="alert error">
                  Отметьте хотя бы один ИИ-критерий — иначе проверке не по чему оценивать документ
                </div>
              )}

              <div className="lockbar">
                {promptLocked ? (
                  <>
                    <span className="lock-title">🔒 Промт собран из отмеченных критериев</span>
                    <button type="button" className="btn ghost small" onClick={unlockPrompt}>
                      ✏️ Изменить промт
                    </button>
                  </>
                ) : (
                  <>
                    <span className="lock-title">
                      🔓 Промт изменён вручную — действует только на этот запуск
                    </span>
                    <button
                      type="button"
                      className="btn ghost small"
                      onClick={() => setPromptLocked(true)}
                    >
                      ⟲ Вернуть собранный промт
                    </button>
                  </>
                )}
              </div>
              <div className="prompt-note">
                {promptLocked
                  ? "Снятие галочки убирает блок критерия из промта и пересобирает нумерацию. Действует на этот запуск и никуда не сохраняется."
                  : "Замок снят: галочки критериев больше не меняют промт, он уйдёт в проверку как есть."}
              </div>
              <textarea
                className={`prompt${promptLocked ? " locked" : ""}`}
                spellCheck={false}
                readOnly={promptLocked}
                value={promptLocked ? assembled : prompt}
                onChange={(e) => setPrompt(e.target.value)}
                aria-label="Промт ИИ-проверки"
              />
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
                  // ИИ-проверка: нечего собирать (нет критериев или все сняты)
                  // или промт вручную очищен
                  (checkAi && (config.criteria.length === 0 || criteriaOn.size === 0)) ||
                  (checkAi && !promptLocked && !prompt.trim())
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
