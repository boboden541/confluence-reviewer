import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  api,
  ApiError,
  type AiConnectionConfig,
  type AiProtocol,
  type AiTestResult,
} from "../api";

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

  const keyPlaceholder = clearKey
    ? "токен будет удалён"
    : apiKey
      ? ""
      : cfg?.api_key_masked
        ? `сохранён ${cfg.api_key_masked} — пусто = не менять`
        : cfg?.env.api_key_set
          ? "не задан здесь — используется из окружения"
          : "не задан";

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <Link to="/">Ревью требований</Link>
        <span className="sep">/</span>
        <span>Настройка</span>
        <span className="sep">/</span>
        <span>Подключение ИИ</span>
      </nav>
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">⚙️</span> Подключение ИИ
          </h1>
          <div className="page-meta">
            <span className="muted">
              Применяется ко всем ИИ-проверкам документов
              {cfg?.updated_at &&
                ` · изменено: ${new Date(cfg.updated_at).toLocaleString("ru-RU")}`}
            </span>
          </div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}
      {!cfg && !error && <p className="muted">Загрузка…</p>}

      {cfg && (
        <form className="panel" onSubmit={onSave}>
          <div className="zone-label">Протокол API</div>
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
              <span>
                <span className="name">{card.name}</span>
                <div className="desc">{card.desc}</div>
              </span>
            </label>
          ))}

          <div className="form-row">
            <span className="field">
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
              <span className="field-hint">
                Заполняет URL и модель — значения можно поправить руками
              </span>
            </span>
          </div>

          <div className="form-row">
            <span className="field">
              <label htmlFor="ai-base-url">Базовый URL</label>
              <input
                id="ai-base-url"
                className="text-input"
                style={{ width: "360px" }}
                placeholder={cfg.env.base_url}
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <span className="field-hint">пусто — из окружения (.env)</span>
            </span>
            <span className="field">
              <label htmlFor="ai-model">Модель</label>
              <input
                id="ai-model"
                className="text-input"
                style={{ width: "220px" }}
                placeholder={cfg.env.model}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
              <span className="field-hint">пусто — из окружения (.env)</span>
            </span>
          </div>

          <div className="form-row">
            <span className="field">
              <label htmlFor="ai-key">API-токен</label>
              <input
                id="ai-key"
                className="text-input"
                type="password"
                style={{ width: "320px" }}
                autoComplete="new-password"
                placeholder={keyPlaceholder}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setClearKey(false);
                }}
              />
              <span className="field-hint">
                {clearKey
                  ? "Сохранённый токен будет удалён — проверки пойдут с ключом из окружения"
                  : "Хранится в БД и отдаётся только маской; пусто — не менять"}
              </span>
            </span>
            {cfg.api_key_masked && (
              <button
                type="button"
                className="btn ghost"
                style={{ marginBottom: "14px" }}
                onClick={() => {
                  setClearKey((v) => !v);
                  setApiKey("");
                }}
              >
                {clearKey ? "Отменить удаление" : "Очистить сохранённый токен"}
              </button>
            )}
          </div>

          <div className="head-actions">
            <button
              type="button"
              className="btn subtle"
              onClick={onTest}
              disabled={testing}
            >
              {testing ? "Проверяем…" : "⇄ Проверить подключение"}
            </button>
            <button type="submit" className="btn primary" disabled={busySave}>
              {busySave ? "Сохранение…" : "Сохранить"}
            </button>
          </div>

          {testResult && (
            <div className={`alert ${testResult.ok ? "ok" : "error"}`}>
              {testResult.message}
            </div>
          )}
        </form>
      )}

      <p className="muted">
        Пустые поля берутся из окружения (.env). Поиск по смыслу всегда
        использует AI_BASE_URL / AI_SEARCH_MODEL из окружения и этой
        страницей не переключается.
      </p>
    </section>
  );
}
