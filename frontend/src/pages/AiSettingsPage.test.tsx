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

  it("renders env placeholders, steps and the current-connection summary", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();

    expect(await screen.findByRole("heading", { name: /Мой доступ к ИИ/ })).toBeInTheDocument();
    // шаги ориентируют в форме
    expect(screen.getByText("Протокол API")).toBeInTheDocument();
    expect(screen.getByText("Провайдер и модель")).toBeInTheDocument();
    expect(screen.getByText("API-токен")).toBeInTheDocument();
    // плейсхолдеры показывают, что подхватится из окружения
    expect(screen.getByPlaceholderText("https://api.z.ai/api/anthropic")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("glm-4.5")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("введите, чтобы заменить")).toBeInTheDocument();
    // сводка: эффективные значения (env) и источник токена
    const summary = document.querySelector(".current-conn")?.textContent ?? "";
    expect(summary).toContain("glm-4.5");
    expect(summary).toContain("https://api.z.ai/api/anthropic");
    expect(summary).toContain("токен из окружения");
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
    // маска — строкой статуса под полем, с кнопкой удаления
    expect(screen.getByText("sk-…ken")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Удалить сохранённый токен" })).toBeInTheDocument();
  });

  it("sends the typed token on save", async () => {
    const fetchMock = mockFetch({
      "/api/ai-settings": CONFIG,
      "PUT /api/ai-settings": { ...CONFIG, api_key_masked: "new…key" },
    });
    renderPage();

    fireEvent.change(await screen.findByLabelText("Новый токен"), {
      target: { value: "sk-new-typed-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(putCall(fetchMock)?.api_key).toBe("sk-new-typed-token");
    });
  });

  it("deleting the saved token sends an empty api_key", async () => {
    const withKey = { ...CONFIG, api_key_masked: "sk-…ken" };
    const fetchMock = mockFetch({
      "/api/ai-settings": withKey,
      "PUT /api/ai-settings": { ...withKey, api_key_masked: "" },
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Удалить сохранённый токен" }),
    );
    // режим удаления объясняет последствия и отменяется
    expect(await screen.findByText(/будет удалён/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отменить удаление" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(putCall(fetchMock)?.api_key).toBe(""); // "" → очистить, проверки пойдут с env-ключом
    });
  });

  it("test connection posts current form values and shows an inline result", async () => {
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
    // результат — плашка в строке действий, не баннер на всю страницу
    expect(await screen.findByText(/Модель glm-4.5 ответила/)).toBeInTheDocument();
    expect(document.querySelector(".test-result.ok")).not.toBeNull();
    expect(document.querySelector(".alert.ok")).toBeNull();
  });

  it("test connection failure shows an error pill, not a page error", async () => {
    mockFetch({
      "/api/ai-settings": CONFIG,
      "POST /api/ai-settings/test": { ok: false, message: "Неверный API-ключ ИИ (401)" },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "⇄ Проверить подключение" }));

    expect(await screen.findByText(/Неверный API-ключ ИИ \(401\)/)).toBeInTheDocument();
    expect(document.querySelector(".test-result.error")).not.toBeNull();
    expect(screen.queryByText("Настройки сохранены")).not.toBeInTheDocument();
  });

  it("preset select prefills base url and model", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();
    await screen.findByRole("heading", { name: /Мой доступ к ИИ/ });

    fireEvent.change(screen.getByLabelText("Пресет провайдера"), {
      target: { value: "zai" },
    });

    expect(screen.getByDisplayValue("https://api.z.ai/api/anthropic")).toBeInTheDocument();
    expect(screen.getByDisplayValue("glm-4.5")).toBeInTheDocument();
  });

  it("switching protocol filters the preset list", async () => {
    mockFetch({ "/api/ai-settings": CONFIG });
    renderPage();
    await screen.findByRole("heading", { name: /Мой доступ к ИИ/ });

    fireEvent.click(screen.getByText("OpenAI-совместимый"));

    expect(screen.queryByRole("option", { name: "z.ai · GLM" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Локальный Ollama" })).toBeInTheDocument();
  });
});
