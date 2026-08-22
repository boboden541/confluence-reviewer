import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DocumentsPage from "./DocumentsPage";
import { AUTH_STORAGE_KEY } from "../api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    const bare = path.split("?")[0];
    for (const [prefix, payload] of Object.entries(responses)) {
      // точное совпадение (с query-строкой) либо без неё
      if (path === prefix || bare === prefix) {
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

const ANALYST = {
  id: 5,
  full_name: "Никулин Владислав",
  email: "nikulinva@mts.ru",
  confluence_username: null,
  created_at: "2026-08-01T10:00:00",
  documents_count: 2,
  last_synced_at: null,
  sync_error: null,
};

const DOCUMENTS = {
  items: [
    {
      id: 11,
      confluence_page_id: "2380439645",
      title: "[СТ] GDS-15 Загрузка кино",
      url: "https://confluence.mts.ru/x/1",
      created_in_confluence_at: "2026-07-01T00:00:00",
      last_modified_in_confluence_at: "2026-08-10T00:00:00",
      validation_status: "failed",
      last_validated_at: "2026-08-11T00:00:00",
      has_note: true,
    },
    {
      id: 12,
      confluence_page_id: "2380439999",
      title: "[СТ] Вторая доработка",
      url: "https://confluence.mts.ru/x/2",
      created_in_confluence_at: "2026-07-05T00:00:00",
      last_modified_in_confluence_at: "2026-08-12T00:00:00",
      validation_status: "not_checked",
      last_validated_at: null,
      has_note: false,
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

describe("DocumentsPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders analyst name and documents with status badges", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Никулин Владислав")).toBeInTheDocument();
    expect(await screen.findByText("[СТ] GDS-15 Загрузка кино")).toBeInTheDocument();
    expect(screen.getByText("не пройдено")).toBeInTheDocument();
    expect(screen.getByText("не проверено")).toBeInTheDocument();
    expect(screen.getByText("Всего документов: 2")).toBeInTheDocument();
    // у первого документа есть заметка — это видно в списке
    expect(screen.getByTitle("Есть заметка руководителя").textContent).toBe("📝");
  });

  it("passes search query to the API", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": { items: [], total: 0, page: 1, page_size: 20 },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText("Поиск по названию…");
    fireEvent.change(input, { target: { value: "GDS" } });

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) =>
        String(url).includes("query=GDS"),
      );
      expect(call).toBeDefined();
    });
  });

  it("shows empty state when no documents match", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": { items: [], total: 0, page: 1, page_size: 20 },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Документы не найдены")).toBeInTheDocument();
  });

  it("runs single validation from the row button", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // doc 11 — failed → «Актуализировать», doc 12 — not_checked → «Проверить»
    const refresh = await screen.findByRole("button", { name: "Актуализировать" });
    fireEvent.click(refresh);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/11/validate" && init?.method === "POST",
      );
      expect(call).toBeDefined();
    });
  });

  it("starts bulk validation for the analyst", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/sync/bulk-validation": {
        running: false,
        analyst_id: null,
        total: 0,
        done: 0,
        started_at: null,
        finished_at: null,
        error: null,
      },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Проверить все" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/analysts/5/validate-all" && init?.method === "POST",
      );
      expect(call).toBeDefined();
    });
  });

  it("appends the next page when the sentinel becomes visible", async () => {
    // Мок IntersectionObserver: колбэк можно дёрнуть вручную из теста.
    class MockIntersectionObserver {
      static instances: MockIntersectionObserver[] = [];
      callback: (entries: { isIntersecting: boolean }[]) => void;

      constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
        this.callback = callback;
        MockIntersectionObserver.instances.push(this);
      }

      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    const doc = (id: number, title: string) => ({
      id,
      confluence_page_id: String(1000 + id),
      title,
      url: `https://confluence.mts.ru/x/${id}`,
      created_in_confluence_at: "2026-07-01T00:00:00",
      last_modified_in_confluence_at: "2026-08-10T00:00:00",
      validation_status: "not_checked",
      last_validated_at: null,
      has_note: false,
    });
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents?page=1&page_size=20": {
        items: [doc(1, "Первая страница — 1")],
        total: 25,
        page: 1,
        page_size: 20,
      },
      "/api/analysts/5/documents?page=2&page_size=20": {
        items: [doc(21, "Вторая страница — 21")],
        total: 25,
        page: 2,
        page_size: 20,
      },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Первая страница — 1")).toBeInTheDocument();
    expect(screen.getByText("Показано 1 из 25")).toBeInTheDocument();

    // скролл дошёл до сентинела — подгружается вторая страница
    MockIntersectionObserver.instances[0].callback([{ isIntersecting: true }]);

    expect(await screen.findByText("Вторая страница — 21")).toBeInTheDocument();
    expect(screen.getByText("Показано 2 из 25")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("page=2"))).toBe(
      true,
    );
  });
});
