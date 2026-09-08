import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  type AiConnectionConfig,
  type AiProtocol,
  type AiTestResult,
} from "../api";
import { Breadcrumbs } from "../Breadcrumbs";

// Пресеты провайдеров: только prefill полей — значения можно править руками
const PRESETS: {
  id: string;
  label: string;
  protocol: AiProtocol;
  base_url: string;
  model: string;
}[] = [
  {
    id: "zai",
    label: "z.ai · GLM",
    protocol: "anthropic",
    base_url: "https://api.z.ai/api/anthropic",
    model: "glm-4.5",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    protocol: "anthropic",
    base_url: "https://api.deepseek.com/anthropic",
    model: "deepseek-chat",
  },
  {
    id: "kimi",
    label: "Kimi (Moonshot)",
    protocol: "anthropic",
    base_url: "https://api.moonshot.cn/anthropic",
    model: "kimi-k2-0905-preview",
  },
  {
    id: "openai",
    label: "OpenAI",
    protocol: "openai",
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    protocol: "openai",
    base_url: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o",
  },
  {
    id: "ollama",
    label: "Локальный Ollama",
    protocol: "openai",
    base_url: "http://host.docker.internal:11434/v1",
    model: "qwen2.5:7b",
  },
];

const PROTOCOL_CARDS: { id: AiProtocol; name: string; desc: string }[] = [
  { id: "anthropic", name: "Anthropic-совместимый", desc: "z.ai (GLM), DeepSeek, Kimi" },
  { id: "openai", name: "OpenAI-совместимый", desc: "OpenAI, OpenRouter, локальные Ollama / vLLM" },
];

export default function AiSettingsPage() {
  const [cfg, setCfg] = useState<AiConnectionConfig | null>(null);
  const [protocol, setProtocol] = useState<AiProtocol>("anthropic");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [presetId, setPresetId] = useState("");
  const [busySave, setBusySave] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = async () => {
    try {
      const data = await api<AiConnectionConfig>("/api/ai-settings");
      setCfg(data);
      setProtocol(data.protocol);
      setBaseUrl(data.base_url);
      setModel(data.model);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить настройки");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const switchProtocol = (next: AiProtocol) => {
    setProtocol(next);
    // пресет прошлого протокола больше не показывается в списке
    if (PRESETS.find((p) => p.id === presetId)?.protocol !== next) setPresetId("");
  };

  const applyPreset = (id: string) => {
    setPresetId(id);
    const preset = PRESETS.find((p) => p.id === id);
    if (preset) {
      setBaseUrl(preset.base_url);
      setModel(preset.model);
    }
  };

  // «Проверить подключение»: мини-запрос с текущими (возможно несохранёнными) значениями
  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    setError("");
    try {
      const result = await api<AiTestResult>("/api/ai-settings/test", {
        method: "POST",
        body: JSON.stringify({
          protocol,
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: clearKey ? "" : apiKey.trim(),
        }),
      });
      setTestResult(result);
    } catch (exc) {
      setTestResult({
        ok: false,
        message: exc instanceof ApiError ? exc.message : "Не удалось выполнить запрос",
      });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    setBusySave(true);
    setError("");
    setInfo("");
    try {
      await api<AiConnectionConfig>("/api/ai-settings", {
        method: "PUT",
        body: JSON.stringify({
          protocol,
          base_url: baseUrl.trim(),
          model: model.trim(),
          // null — не менять сохранённый токен, "" — удалить (→ окружение)
          api_key: clearKey ? "" : apiKey.trim() || null,
        }),
      });
      setApiKey("");
      setClearKey(false);
      setPresetId("");
      setTestResult(null);
      await load();
      setInfo("Настройки сохранены — применятся к следующим проверкам");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить настройки");
    } finally {
      setBusySave(false);
    }
  };

  // «изменено: 21.08.2026, 14:02» — без секунд
  const formatUpdatedAt = (iso: string) =>
    new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <section className="page">
      <Breadcrumbs items={[{ label: "Настройка" }, { label: "Подключение ИИ" }]} />
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">⚙️</span> Подключение ИИ
          </h1>
          <div className="page-meta">
            Применяется ко всем ИИ-проверкам документов
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}
      {!cfg && !error && <p className="muted">Загрузка…</p>}

      {cfg && (
        <>
          {/* якорь: чем проверяют прямо сейчас — эффективные значения (сохранённое || env) */}
          <div className="current-conn">
            <span className="lbl">Сейчас проверяют через:</span>
            <span>
              <span className="dot">●</span>{" "}
              {cfg.model || cfg.env.model} ·{" "}
              <code>{cfg.base_url || cfg.env.base_url}</code>
            </span>
            <span>
              ·{" "}
              {cfg.api_key_masked
                ? "токен из базы"
                : cfg.env.api_key_set
                  ? "токен из окружения"
                  : "токен не задан"}
            </span>
            {cfg.updated_at && (
              <span>· изменено: {formatUpdatedAt(cfg.updated_at)}</span>
            )}
          </div>

          <form className="settings-form" onSubmit={onSave}>
            {/* 01 · протокол */}
            <div className="step">
              <div className="step-head">
                <span className="step-num">01</span>
                <span className="step-title">Протокол API</span>
              </div>
              <p className="step-sub">
                Определяет формат запросов к провайдеру. Если не уверены —
                оставьте как есть.
              </p>
              <div className="protocol-grid">
                {PROTOCOL_CARDS.map((card) => (
                  <label
                    key={card.id}
                    className={protocol === card.id ? "tpl selected" : "tpl"}
                  >
                    <input
                      type="radio"
                      name="ai-protocol"
                      checked={protocol === card.id}
                      onChange={() => switchProtocol(card.id)}
                    />
                    <span className="proto-mark">
                      {card.id === "anthropic" ? "A" : "O"}
                    </span>
                    <span>
                      <span className="name">{card.name}</span>
                      <div className="desc">{card.desc}</div>
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* 02 · провайдер и модель */}
            <div className="step">
              <div className="step-head">
                <span className="step-num">02</span>
                <span className="step-title">Провайдер и модель</span>
              </div>
              <p className="step-sub">
                Выберите пресет — поля заполнятся сами, значения можно поправить
                руками. Оставьте поле пустым, чтобы брать значение из окружения
                (<code>.env</code>).
              </p>
              <div className="field" style={{ marginBottom: 18 }}>
                <label htmlFor="ai-preset">Пресет провайдера</label>
                <select
                  id="ai-preset"
                  className="select-input"
                  value={presetId}
                  onChange={(e) => applyPreset(e.target.value)}
                >
                  <option value="">— выбрать —</option>
                  {PRESETS.filter((p) => p.protocol === protocol).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="fields-grid">
                <div className="field">
                  <label htmlFor="ai-base-url">Базовый URL</label>
                  <input
                    id="ai-base-url"
                    className="text-input"
                    placeholder={cfg.env.base_url}
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                  />
                  <span className="field-hint">
                    пусто — из окружения: <code>AI_BASE_URL</code>
                  </span>
                </div>
                <div className="field">
                  <label htmlFor="ai-model">Модель</label>
                  <input
                    id="ai-model"
                    className="text-input"
                    placeholder={cfg.env.model}
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                  />
                  <span className="field-hint">
                    пусто — <code>AI_MODEL</code>
                  </span>
                </div>
              </div>
            </div>

            {/* 03 · токен */}
            <div className="step">
              <div className="step-head">
                <span className="step-num">03</span>
                <span className="step-title">API-токен</span>
              </div>
              <p className="step-sub">
                Хранится в базе и отдаётся только маской. Оставьте поле пустым —
                ничего не изменится; чтобы вернуться к ключу из окружения,
                удалите сохранённый токен.
              </p>
              <div className="field">
                <label htmlFor="ai-key">Новый токен</label>
                <input
                  id="ai-key"
                  className="text-input"
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    clearKey ? "токен будет удалён" : "введите, чтобы заменить"
                  }
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setClearKey(false);
                  }}
                />
                {cfg.api_key_masked && !clearKey && (
                  <div className="key-status">
                    <span>Сохранён:</span>
                    <span className="mask">{cfg.api_key_masked}</span>
                    <button
                      type="button"
                      className="btn ghost danger"
                      onClick={() => {
                        setClearKey(true);
                        setApiKey("");
                      }}
                    >
                      Удалить сохранённый токен
                    </button>
                  </div>
                )}
                {clearKey && (
                  <div className="key-status">
                    <span>
                      Сохранённый токен будет удалён — проверки пойдут с ключом
                      из окружения
                    </span>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() => setClearKey(false)}
                    >
                      Отменить удаление
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* действия: тест с inline-результатом слева, сохранение справа */}
            <div className="form-foot">
              <button
                type="button"
                className="btn subtle"
                onClick={onTest}
                disabled={testing}
              >
                {testing ? "Проверяем…" : "⇄ Проверить подключение"}
              </button>
              {testResult && (
                <span
                  className={`test-result ${testResult.ok ? "ok" : "error"}`}
                >
                  {testResult.ok ? "✓" : "✗"} {testResult.message}
                </span>
              )}
              <span className="spacer" />
              <button type="submit" className="btn primary" disabled={busySave}>
                {busySave ? "Сохранение…" : "Сохранить"}
              </button>
            </div>
          </form>
        </>
      )}

      <p className="muted foot-note">
        Пустые поля берутся из окружения (<code>.env</code>). Поиск по смыслу
        всегда использует <code>AI_BASE_URL</code> / <code>AI_SEARCH_MODEL</code>{" "}
        из окружения и этой страницей не переключается.
      </p>
    </section>
  );
}
