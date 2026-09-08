// Авторизация: сессия в localStorage, текущий пользователь (me), вход
// God логином+паролем и лидов токеном Confluence (заявка → модерация).

import { api, ApiError, clearCredentials } from "./api";

export interface Me {
  id: number;
  full_name: string;
  email: string;
  role_id: number;
  role_name: string;
  is_god: boolean;
  permissions: string[];
  ai_configured: boolean;
  pending_requests: number;
}

export function can(me: Me | null, permission: string): boolean {
  if (me === null) return false; // до загрузки me действий не показываем
  return me.permissions.includes(permission);
}

export type TokenLoginOutcome =
  | { kind: "session"; me: Me }
  | { kind: "pending"; fullName: string }
  | { kind: "rejected" }
  | { kind: "error"; message: string };

/** Вход лидов персональным токеном Confluence: сессия, статус заявки или отказ. */
export async function loginWithToken(token: string): Promise<TokenLoginOutcome> {
  try {
    const resp = await fetch("/api/auth/token-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (resp.status === 200) {
      const data = (await resp.json()) as { token: string; user: Me };
      const { saveSession } = await import("./api");
      saveSession(data.token);
      return { kind: "session", me: data.user };
    }
    if (resp.status === 202) {
      const body = (await resp.json()) as { full_name?: string };
      return { kind: "pending", fullName: body.full_name ?? "" };
    }
    if (resp.status === 403) return { kind: "rejected" };
    const body = (await resp.json().catch(() => ({}))) as { detail?: string };
    return { kind: "error", message: body.detail ?? "Не удалось войти по токену" };
  } catch {
    return { kind: "error", message: "Сервис недоступен, попробуйте ещё раз" };
  }
}

/** Повторная подача отклонённой заявки тем же токеном. */
export async function reapply(token: string): Promise<boolean> {
  try {
    const resp = await fetch("/api/auth/reapply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    return resp.status === 202;
  } catch {
    return false;
  }
}

export function fetchMe(): Promise<Me> {
  return api<Me>("/api/auth/me");
}

export function logout(): void {
  clearCredentials();
}

export { ApiError };
