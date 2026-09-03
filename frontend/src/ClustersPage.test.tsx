import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ClustersPage from "./pages/ClustersPage";
import type { Analyst, Cluster } from "./api";

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

const CLUSTERS: Cluster[] = [
  {
    id: 3,
    name: "Билетный бизнес",
    description: "Продажи билетов",
    color: "#0C66E4",
    created_at: "2026-01-01T00:00:00",
    teams_count: 2,
    analysts_count: 2,
    documents_count: 42,
    teams: [
      { id: 12, name: "GDS", description: "Бронирование", analysts_count: 1 },
      { id: 13, name: "Финтех", description: null, analysts_count: 1 },
    ],
  },
];

const ANALYSTS: Analyst[] = [
  {
    id: 7,
    full_name: "Алиев Рустам",
    email: "aliev@company.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 14,
    last_synced_at: null,
    sync_error: null,
    team_id: 12,
    team_name: "GDS",
    cluster_id: 3,
    cluster_name: "Билетный бизнес",
    domains: ["вывод на витрину"],
  },
  {
    id: 9,
    full_name: "Сидоров Пётр",
    email: "sidorov@company.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 2,
    last_synced_at: null,
    sync_error: null,
    team_id: null,
    team_name: null,
    cluster_id: null,
    cluster_name: null,
    domains: [],
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <ClustersPage />
    </MemoryRouter>,
  );
}

describe("ClustersPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders cluster cards with counters, team chips and links", async () => {
    mockFetch({ "/api/clusters": CLUSTERS, "/api/analysts": ANALYSTS });
    renderPage();

    const card = await screen.findByRole("link", { name: "Билетный бизнес" });
    expect(card).toHaveAttribute("href", "/clusters/3");
    expect(screen.getByText("Продажи билетов")).toBeInTheDocument();
    // счётчики кластера
    expect(screen.getByText("42")).toBeInTheDocument(); // документов
    const gds = screen.getByRole("link", { name: /GDS/ });
    expect(gds).toHaveAttribute("href", "/teams/12");
    expect(screen.getByRole("link", { name: /Финтех/ })).toHaveAttribute("href", "/teams/13");
  });

  it("shows only unassigned analysts in 'Без команды'", async () => {
    mockFetch({ "/api/clusters": CLUSTERS, "/api/analysts": ANALYSTS });
    renderPage();

    const free = await screen.findByRole("link", { name: /Сидоров Пётр/ });
    expect(free).toHaveAttribute("href", "/analysts/9");
    expect(screen.queryByText("Алиев Рустам")).not.toBeInTheDocument();
  });

  it("creates a cluster through the modal and reloads", async () => {
    const fetchMock = mockFetch({
      "/api/clusters": CLUSTERS,
      "/api/analysts": ANALYSTS,
      "POST /api/clusters": { ...CLUSTERS[0], id: 4, name: "Медиа" },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Новый кластер/ }));
    const nameInput = await screen.findByLabelText("Название *");
    fireEvent.change(nameInput, { target: { value: "Медиа" } });

    // цвет выбирается свотчем
    fireEvent.click(screen.getByRole("radio", { name: "#6E5DC6" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/clusters" && init?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        name: "Медиа",
        description: null,
        color: "#6E5DC6",
      });
    });
    expect(await screen.findByText("Кластер «Медиа» создан")).toBeInTheDocument();
  });

  it("surfaces a duplicate-name conflict as an alert", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      if (path === "/api/clusters" && init?.method === "POST") {
        return new Response(
          JSON.stringify({ detail: "Кластер «Медиа» уже существует" }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        );
      }
      const map: Record<string, unknown> = { "/api/clusters": CLUSTERS, "/api/analysts": ANALYSTS };
      const payload = map[path];
      return payload !== undefined
        ? new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        : new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Новый кластер/ }));
    fireEvent.change(await screen.findByLabelText("Название *"), { target: { value: "Медиа" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Кластер «Медиа» уже существует")).toBeInTheDocument();
  });

  it("deletes an empty cluster after confirm", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/clusters/3" && method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      const map: Record<string, unknown> = {
        "/api/clusters": CLUSTERS,
        "/api/analysts": ANALYSTS,
      };
      const payload = map[path];
      return payload !== undefined
        ? new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        : new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Удалить/ }));
    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/clusters/3" && init?.method === "DELETE",
      );
      expect(del).toBeDefined();
    });
  });
});
