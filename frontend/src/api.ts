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

function authHeaders(): Record<string, string> {
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
}

export interface DocumentPage {
  items: DocumentListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ValidationReport {
  id: number;
  document_id: number;
  triggered_by: "auto" | "manual";
  created_at: string;
  template_passed: boolean;
  template_findings: string;
  ai_passed: boolean | null;
  ai_findings: string | null;
  overall_passed: boolean;
  error_message: string | null;
  comment_sent_at: string | null;
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
