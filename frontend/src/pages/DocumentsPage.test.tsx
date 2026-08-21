import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DocumentsPage from "./DocumentsPage";
import { AUTH_STORAGE_KEY } from "../api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    for (const [prefix, payload] of Object.entries(responses)) {
      if (path.split("?")[0] === prefix) {
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
});
