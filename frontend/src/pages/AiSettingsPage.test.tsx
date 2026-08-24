import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AiSettingsPage from "./AiSettingsPage";
import { AUTH_STORAGE_KEY } from "../api";

// мок: ключи вида "METHOD /path" точечно, голый путь — для GET
function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const payload = responses[`${init?.method ?? "GET"} ${path}`] ?? responses[path];
    if (payload !== undefined) {
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const CONFIG = {
  protocol: "anthropic",
  base_url: "",
  model: "",
  api_key_masked: "",
  updated_at: null,
  env: {
    protocol: "anthropic",
    base_url: "https://api.z.ai/api/anthropic",
    model: "glm-4.5",
    api_key_set: true,
  },
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/ai-connection"]}>
      <AiSettingsPage />
    </MemoryRouter>,
  );
}

function putCall(fetchMock: ReturnType<typeof mockFetch>) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url) === "/api/ai-settings" && init?.method === "PUT",
  );
  return call ? JSON.parse(String(call[1]?.body)) : null;
}

function postTestCall(fetchMock: ReturnType<typeof mockFetch>) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url) === "/api/ai-settings/test" && init?.method === "POST",
  );
  return call ? JSON.parse(String(call[1]?.body)) : null;
}

describe("AiSettingsPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders env placeholders and hints when nothing is saved", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();

    expect(await screen.findByRole("heading", { name: /Подключение ИИ/ })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("https://api.z.ai/api/anthropic")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("glm-4.5")).toBeInTheDocument();
    // токен из окружения — плейсхолдер поля говорит об этом
    expect(
      screen.getByPlaceholderText("не задан здесь — используется из окружения"),
    ).toBeInTheDocument();
  });

  it("saves with null api_key when token untouched, shows mask after reload", async () => {
    const withKey = { ...CONFIG, api_key_masked: "sk-…ken" };
    const fetchMock = mockFetch({
      "/api/ai-settings": withKey,
      "PUT /api/ai-settings": withKey,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(putCall(fetchMock)).toEqual({
        protocol: "anthropic",
        base_url: "",
        model: "",
        api_key: null, // не трогаем сохранённый токен
      });
    });
    expect(await screen.findByText("Настройки сохранены — применятся к следующим проверкам")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/сохранён sk-…ken/)).toBeInTheDocument();
  });

  it("sends the typed token on save", async () => {
    const fetchMock = mockFetch({
      "/api/ai-settings": CONFIG,
      "PUT /api/ai-settings": { ...CONFIG, api_key_masked: "new…key" },
    });
    renderPage();

    fireEvent.change(await screen.findByLabelText("API-токен"), {
      target: { value: "sk-new-typed-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(putCall(fetchMock)?.api_key).toBe("sk-new-typed-token");
    });
  });

  it("test connection posts current form values and shows the result", async () => {
    const fetchMock = mockFetch({
      "/api/ai-settings": CONFIG,
      "POST /api/ai-settings/test": { ok: true, message: "Модель glm-4.5 ответила" },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "⇄ Проверить подключение" }));

    await waitFor(() => {
      expect(postTestCall(fetchMock)).toEqual({
        protocol: "anthropic",
        base_url: "",
        model: "",
        api_key: "", // пустая строка → бэкенд возьмёт сохранённый/env ключ
      });
    });
    expect(await screen.findByText("Модель glm-4.5 ответила")).toBeInTheDocument();
  });

  it("test connection failure shows an error alert, not a page error", async () => {
    mockFetch({
      "/api/ai-settings": CONFIG,
      "POST /api/ai-settings/test": { ok: false, message: "Неверный API-ключ ИИ (401)" },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "⇄ Проверить подключение" }));

    expect(await screen.findByText("Неверный API-ключ ИИ (401)")).toBeInTheDocument();
    expect(screen.queryByText("Настройки сохранены")).not.toBeInTheDocument();
  });

  it("preset select prefills base url and model", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();
    await screen.findByRole("heading", { name: /Подключение ИИ/ });

    fireEvent.change(screen.getByLabelText("Пресет провайдера"), {
      target: { value: "zai" },
    });

    expect(screen.getByDisplayValue("https://api.z.ai/api/anthropic")).toBeInTheDocument();
    expect(screen.getByDisplayValue("glm-4.5")).toBeInTheDocument();
  });

  it("switching protocol filters the preset list", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();
    await screen.findByRole("heading", { name: /Подключение ИИ/ });

    fireEvent.click(screen.getByText("OpenAI-совместимый"));

    expect(screen.queryByRole("option", { name: "z.ai · GLM" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Локальный Ollama" })).toBeInTheDocument();
  });
});
