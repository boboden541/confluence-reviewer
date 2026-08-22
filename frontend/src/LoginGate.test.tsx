import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LoginGate } from "./App";
import { AUTH_STORAGE_KEY } from "./api";

// Декодирует base64-строку как UTF-8 (обратная операция к TextEncoder + btoa).
function decodeBase64Utf8(value: string): string {
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function renderGate() {
  return render(
    <MemoryRouter>
      <LoginGate />
    </MemoryRouter>,
  );
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

function stubFetch(status: number) {
  return vi.fn(async () => new Response("[]", { status }));
}

describe("LoginGate", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("shows error and stores nothing on wrong credentials", async () => {
    const fetchMock = stubFetch(401);
    vi.stubGlobal("fetch", fetchMock);

    renderGate();
    fillAndSubmit("boss", "wrong");

    expect(await screen.findByText("Неверный логин или пароль")).toBeInTheDocument();
    expect(localStorage.getItem(AUTH_STORAGE_KEY)).toBeNull();
  });

  it("stores credentials after successful check (UTF-8, кириллица)", async () => {
    const fetchMock = stubFetch(200);
    vi.stubGlobal("fetch", fetchMock);

    renderGate();
    fillAndSubmit("босс", "пароль-123");

    await screen.findByText("Войти");
    const stored = localStorage.getItem(AUTH_STORAGE_KEY);
    expect(stored).not.toBeNull();
    expect(decodeBase64Utf8(stored!)).toBe("босс:пароль-123");
    // Заголовок запроса проверки содержит те же UTF-8 base64-креды
    const [, init] = fetchMock.mock.calls[0] as unknown as [
      RequestInfo | URL,
      RequestInit,
    ];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      `Basic ${stored}`,
    );
  });

  it("shows outage message when the service is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down");
      }),
    );

    renderGate();
    fillAndSubmit("boss", "pass");

    expect(await screen.findByText("Сервис недоступен, попробуйте ещё раз")).toBeInTheDocument();
  });
});
