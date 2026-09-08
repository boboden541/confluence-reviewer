import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LoginGate } from "./App";
import { AUTH_STORAGE_KEY } from "./api";

const ME = {
  id: 1,
  full_name: "Р. Руководитель",
  email: "god@service.local",
  role_id: 1,
  role_name: "God",
  is_god: true,
  permissions: ["checks", "moderation"],
  ai_configured: true,
  pending_requests: 0,
};

function renderGate(onAuthenticated = vi.fn()) {
  const onAuth = onAuthenticated;
  render(
    <MemoryRouter>
      <LoginGate onAuthenticated={onAuth} />
    </MemoryRouter>,
  );
  return onAuth;
}

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText("Логин"), {
    target: { value: username },
  });
  fireEvent.change(screen.getByPlaceholderText("Пароль"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

function stubFetch(responses: Record<string, { status: number; body: unknown }>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const method = init?.method ?? "GET";
    const hit = responses[`${method} ${path}`] ?? responses[path];
    if (hit) {
      return new Response(JSON.stringify(hit.body), {
        status: hit.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
}

describe("LoginGate", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("God: ошибка при неверном логине/пароле, сессия не сохраняется", async () => {
    vi.stubGlobal(
      "fetch",
      stubFetch({ "POST /api/auth/login": { status: 401, body: { detail: "x" } } }),
    );
    const onAuth = renderGate();
    fillAndSubmit("boss", "wrong");

    expect(await screen.findByText("Неверный логин или пароль")).toBeInTheDocument();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
    expect(onAuth).not.toHaveBeenCalled();
  });

  it("God: успешный вход сохраняет токен сессии и отдаёт me", async () => {
    const onAuth = vi.fn();
    vi.stubGlobal(
      "fetch",
      stubFetch({
        "POST /api/auth/login": { status: 200, body: { token: "sess-1", user: ME } },
        "GET /api/auth/me": { status: 200, body: ME },
      }),
    );
    const onAuthSpy = renderGate(onAuth);
    fillAndSubmit("boss", "пароль-123");

    await vi.waitFor(() => expect(onAuthSpy).toHaveBeenCalled());
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBe("sess-1");
  });

  it("Lead: токен с ожидающей заявкой показывает экран ожидания", async () => {
    vi.stubGlobal(
      "fetch",
      stubFetch({
        "POST /api/auth/token-login": {
          status: 202,
          body: { status: "pending", full_name: "Мария Смирнова" },
        },
      }),
    );
    renderGate();

    fireEvent.click(screen.getByRole("button", { name: "Токен Confluence" }));
    fireEvent.change(screen.getByPlaceholderText("Персональный токен Confluence"), {
      target: { value: "pat-12345678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));

    expect(await screen.findByText("Заявка отправлена")).toBeInTheDocument();
    expect(screen.getByText(/Мария Смирнова/)).toBeInTheDocument();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("Lead: отклонённая заявка предлагает повторную подачу", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input).split("?")[0];
      if (path === "/api/auth/token-login") {
        return new Response(JSON.stringify({ detail: "отклонена" }), { status: 403 });
      }
      if (path === "/api/auth/reapply") {
        return new Response(JSON.stringify({ status: "pending" }), { status: 202 });
      }
      return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderGate();

    fireEvent.click(screen.getByRole("button", { name: "Токен Confluence" }));
    fireEvent.change(screen.getByPlaceholderText("Персональный токен Confluence"), {
      target: { value: "pat-12345678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));

    expect(await screen.findByText("Заявка отклонена")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Подать заявку повторно" }));
    expect(await screen.findByText("Заявка отправлена")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([u]) => String(u) === "/api/auth/reapply"),
    ).toBe(true);
  });
});
