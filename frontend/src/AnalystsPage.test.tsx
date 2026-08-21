import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AnalystsPage from "./pages/AnalystsPage";
import { AUTH_STORAGE_KEY } from "./api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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
});
