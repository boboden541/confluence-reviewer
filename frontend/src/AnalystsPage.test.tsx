import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AnalystsPage from "./pages/AnalystsPage";
import { AUTH_STORAGE_KEY } from "./api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    for (const [prefix, payload] of Object.entries(responses)) {
      if (path.startsWith(prefix)) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ANALYSTS = [
  {
    id: 1,
    full_name: "Алиев Рустам Азадович",
    email: "raaliev@mts.ru",
    confluence_username: null,
    created_at: "2026-08-01T10:00:00",
    documents_count: 12,
    last_synced_at: "2026-08-20T09:15:00",
    sync_error: null,
  },
  {
    id: 2,
    full_name: "Грудинин Александр",
    email: "aigrudini2@mts.ru",
    confluence_username: "aigrudini2",
    created_at: "2026-08-01T10:00:00",
    documents_count: 3,
    last_synced_at: null,
    sync_error: "Confluence API 401",
  },
];

describe("AnalystsPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders analysts from /api/analysts", async () => {
    mockFetch({ "/api/analysts": ANALYSTS });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Алиев Рустам Азадович")).toBeInTheDocument();
    expect(screen.getByText("aigrudini2@mts.ru")).toBeInTheDocument();
    expect(screen.getByText("Confluence API 401")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("sends stored basic credentials with the request", async () => {
    const fetchMock = mockFetch({ "/api/analysts": [] });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      `Basic ${btoa("u:p")}`,
    );
  });

  it("shows empty state when there are no analysts", async () => {
    mockFetch({ "/api/analysts": [] });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Аналитики ещё не заведены")).toBeInTheDocument();
  });

  it("creates a new analyst from the form and reloads the list", async () => {
    let listCalls = 0;
    const CREATED = {
      id: 3,
      full_name: "Тестов Тест Тестович",
      email: "testov@mts.ru",
      confluence_username: null,
      created_at: "2026-08-22T10:00:00",
      documents_count: 0,
      last_synced_at: null,
      sync_error: null,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/analysts" && init?.method === "POST") {
        return new Response(JSON.stringify(CREATED), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      listCalls += 1;
      return new Response(JSON.stringify(listCalls === 1 ? [] : [CREATED]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    await screen.findByText("Аналитики ещё не заведены");
    fireEvent.change(screen.getByPlaceholderText("ФИО нового аналитика"), {
      target: { value: "Тестов Тест Тестович" },
    });
    fireEvent.change(screen.getByPlaceholderText("email@example.com"), {
      target: { value: "testov@mts.ru" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Добавить аналитика" }));

    expect(await screen.findByText("Тестов Тест Тестович")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === "/api/analysts" && init?.method === "POST",
    ) as [RequestInfo | URL, RequestInit] | undefined;
    expect(post).toBeDefined();
    expect(JSON.parse(post![1].body as string)).toEqual({
      full_name: "Тестов Тест Тестович",
      email: "testov@mts.ru",
    });
  });

  it("shows backend error on duplicate email", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/analysts" && init?.method === "POST") {
        return new Response(
          JSON.stringify({ detail: "Аналитик с email dup@mts.ru уже существует" }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    await screen.findByText("Аналитики ещё не заведены");
    fireEvent.change(screen.getByPlaceholderText("ФИО нового аналитика"), {
      target: { value: "Дубль Дублиевич" },
    });
    fireEvent.change(screen.getByPlaceholderText("email@example.com"), {
      target: { value: "dup@mts.ru" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Добавить аналитика" }));

    expect(await screen.findByText(/уже существует/)).toBeInTheDocument();
  });

  it("edits an analyst from the row button", async () => {
    const fetchMock = mockFetch({ "/api/analysts": ANALYSTS });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    const buttons = await screen.findAllByRole("button", { name: "Изменить" });
    fireEvent.click(buttons[0]); // Алиев

    // форма предзаполнена данными карточки
    const nameInput = screen.getByPlaceholderText("ФИО аналитика") as HTMLInputElement;
    expect(nameInput.value).toBe("Алиев Рустам Азадович");
    expect(
      (screen.getByPlaceholderText("Новый email аналитика") as HTMLInputElement).value,
    ).toBe("raaliev@mts.ru");
    expect(
      (screen.getByPlaceholderText("username в Confluence (пусто — авто)") as HTMLInputElement)
        .value,
    ).toBe("");

    fireEvent.change(nameInput, { target: { value: "Алиев Рустам Новое ФИО" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/analysts/1" && (init as RequestInit | undefined)?.method === "PUT",
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
        full_name: "Алиев Рустам Новое ФИО",
        email: "raaliev@mts.ru",
        confluence_username: null,
      });
    });
    expect(await screen.findByText("Карточка аналитика сохранена")).toBeInTheDocument();
  });

  it("cancels editing without a request", async () => {
    const fetchMock = mockFetch({ "/api/analysts": ANALYSTS });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    const editButtons = await screen.findAllByRole("button", { name: "Изменить" });
    fireEvent.click(editButtons[0]);
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));

    expect(screen.queryByPlaceholderText("ФИО аналитика")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(0);
  });

  it("deletes an analyst after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = mockFetch({ "/api/analysts": ANALYSTS });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    const buttons = await screen.findAllByRole("button", { name: "Удалить" });
    fireEvent.click(buttons[1]); // Грудинин, 3 документа

    expect(confirmSpy).toHaveBeenCalledWith(
      "Удалить аналитика «Грудинин Александр» и все его документы (3)?",
    );
    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/analysts/2" &&
          (init as RequestInit | undefined)?.method === "DELETE",
      );
      expect(del).toBeDefined();
    });
    expect(await screen.findByText(/удалён/)).toBeInTheDocument();
  });

  it("keeps the analyst when confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = mockFetch({ "/api/analysts": ANALYSTS });

    render(
      <MemoryRouter>
        <AnalystsPage />
      </MemoryRouter>,
    );

    const buttons = await screen.findAllByRole("button", { name: "Удалить" });
    fireEvent.click(buttons[0]);

    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE"),
    ).toHaveLength(0);
  });
});
