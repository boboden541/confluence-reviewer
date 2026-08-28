// API-клиент: basic-авторизация (НФТ-CR-7), единая обработка ошибок.

export const AUTH_STORAGE_KEY = "cr-auth";
export const UNAUTHORIZED_EVENT = "cr:unauthorized";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// btoa принимает только Latin-1; кодируем UTF-8 вручную, чтобы кириллические
// логин/пароль корректно доходили до backend (он декодирует base64 → utf-8).
function toBase64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function saveCredentials(username: string, password: string): void {
  localStorage.setItem(AUTH_STORAGE_KEY, toBase64(`${username}:${password}`));
}

// Проверка учётки до сохранения: false — неверный логин или пароль.
export async function login(username: string, password: string): Promise<boolean> {
  const resp = await fetch("/api/analysts", {
    headers: { Authorization: `Basic ${toBase64(`${username}:${password}`)}` },
  });
  return resp.status !== 401;
}

export function clearCredentials(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function hasCredentials(): boolean {
  return localStorage.getItem(AUTH_STORAGE_KEY) !== null;
}

// наружу — для SSE-стрима событий (events.ts): EventSource не умеет
// Authorization-заголовок, стрим читаем обычным fetch
export function authHeaders(): Record<string, string> {
  const creds = localStorage.getItem(AUTH_STORAGE_KEY);
  return creds ? { Authorization: `Basic ${creds}` } : {};
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers as Record<string, string> | undefined),
    },
  });

  if (resp.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError("Требуется авторизация", 401);
  }

  if (!resp.ok) {
    let detail = "";
    try {
      const body = (await resp.json()) as { detail?: string };
      detail = body.detail ?? "";
    } catch {
      detail = resp.statusText;
    }
    throw new ApiError(detail || `Ошибка запроса (${resp.status})`, resp.status);
  }

  return (await resp.json()) as T;
}

// --- типы, зеркалящие backend-схемы ---

export interface Analyst {
  id: number;
  full_name: string;
  email: string;
  confluence_username: string | null;
  created_at: string;
  documents_count: number;
  last_synced_at: string | null;
  sync_error: string | null;
}

export type ValidationStatus =
  | "not_checked"
  | "in_progress"
  | "passed"
  | "failed"
  | "error";

export interface DocumentListItem {
  id: number;
  confluence_page_id: string;
  title: string;
  url: string;
  created_in_confluence_at: string | null;
  last_modified_in_confluence_at: string | null;
  validation_status: ValidationStatus;
  last_validated_at: string | null;
  has_note: boolean;
  /** Релевантность семантического поиска, 0..1 (иначе null) */
  score?: number | null;
}

export interface DocumentPage {
  items: DocumentListItem[];
  total: number;
  page: number;
  page_size: number;
}

/** Строка результата глобального поиска (шапка сервиса) */
export interface SearchHit {
  id: number;
  title: string;
  validation_status: ValidationStatus;
  analyst_id: number;
  analyst_name: string;
}

export interface DocumentDetail extends DocumentListItem {
  content_html: string;
  sync_error: string | null;
  analyst_id: number;
  /** Автор документа — видно на странице отчёта, чей документ открыт */
  analyst_name?: string;
  analyst_email?: string | null;
}

export interface ValidationReport {
  id: number;
  document_id: number;
  triggered_by: "auto" | "manual";
  created_at: string;
  /** null — проверка шаблона не запускалась (выбор критериев в диалоге) */
  template_passed: boolean | null;
  template_findings: string;
  ai_passed: boolean | null;
  ai_findings: string | null;
  overall_passed: boolean;
  error_message: string | null;
  comment_sent_at: string | null;
  /** Чем проверяли: версия шаблона и пользовательский промт (null — стандартный) */
  template_version_id?: number | null;
  ai_prompt?: string | null;
  /** Какой моделью ИИ проверяли (null — старые отчёты) */
  ai_model_used?: string | null;
}

export interface SyncStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  last_results: {
    analyst_id: number;
    analyst_name: string;
    created: number;
    updated: number;
    error: string | null;
  }[];
}

export interface BulkValidationStatus {
  running: boolean;
  analyst_id: number | null;
  total: number;
  done: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

// --- диалог настроек проверки (шаблон + промт ИИ) ---

export interface TemplateOption {
  /** id = номер версии шаблона */
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  section_count: number;
}

/** Активный критерий ИИ-проверки в конфиге диалога: галочка + блок промта */
export interface CriterionOption {
  id: number;
  code: string;
  name: string;
  prompt: string;
}

export interface ValidationConfig {
  templates: TemplateOption[];
  default_prompt: string;
  /** ИИ-критерии для галочек диалога; превью промта = head + блоки + tail */
  criteria: CriterionOption[];
  prompt_head: string;
  prompt_tail: string;
}

/** Критерий последнего прогона с оценкой руководителя (блок оценивания) */
export interface RatingItem {
  criterion_id: number;
  code: string;
  name: string;
  is_archived: boolean;
  /** null — оценка ещё не выставлена («—») */
  score: number | null;
  updated_at: string | null;
  /** Документ перепроверен после выставления оценки */
  stale: boolean;
}

/** GET/PUT /api/documents/:id/ratings */
export interface DocumentRatings {
  document_id: number;
  /** Пусто — прогона с ИИ-проверкой ещё не было: оценивать нечего */
  criteria: RatingItem[];
}

/** POST /api/documents/validate-batch */
export interface BatchValidationRequest {
  document_ids: number[];
  force?: boolean;
  /** Какие критерии запускать; отсутствует = оба (обратная совместимость) */
  checks?: Array<"template" | "ai">;
  template_id?: number | null;
  /** null/undefined — стандартный промт; строка — пользовательский на этот запуск */
  ai_prompt?: string | null;
  /** ИИ-критерии этого запуска (id); null/undefined — все активные */
  criterion_ids?: number[] | null;
}

// --- справочник ИИ-критериев (раздел настроек) ---

/** Критерий ИИ-проверки: название + промт-инструкция. Код стабилен после создания */
export interface AiCriterion {
  id: number;
  code: string;
  name: string;
  prompt: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

// --- настройки подключения ИИ (глобальные) ---

export type AiProtocol = "anthropic" | "openai";

/** Загрузочные дефолты из окружения — плейсхолдеры полей формы */
export interface AiEnvInfo {
  protocol: AiProtocol;
  base_url: string;
  model: string;
  api_key_set: boolean;
}

export interface AiConnectionConfig {
  /** Сохранённые значения: "" = берётся из env */
  protocol: AiProtocol;
  base_url: string;
  model: string;
  /** Маска сохранённого токена ("" — в БД не задан); открытым текстом не отдаётся */
  api_key_masked: string;
  updated_at: string | null;
  env: AiEnvInfo;
}

/** PUT /api/ai-settings: api_key null — не менять, "" — очистить (→ env) */
export interface AiConnectionUpdate {
  protocol: AiProtocol;
  base_url: string;
  model: string;
  api_key: string | null;
}

/** POST /api/ai-settings/test: текущие (возможно несохранённые) значения формы */
export interface AiTestRequest {
  protocol: AiProtocol;
  base_url: string;
  model: string;
  api_key: string;
}

export interface AiTestResult {
  ok: boolean;
  message: string;
}

// --- Шаблон требований (редактор) ---

export interface TemplateSection {
  /** Уровень 1..3 задаёт вложенность; порядок — позиция в списке */
  level: number;
  text: string;
  required: boolean;
  aliases: string[];
}

export interface TemplateInfo {
  /** id = номер версии */
  id: number;
  name: string;
  description: string | null;
  title_marker: string;
  sections: TemplateSection[];
  created_at: string;
}

export interface TemplateVersionInfo {
  id: number;
  name: string;
  created_at: string;
  is_active: boolean;
  section_count: number;
}
