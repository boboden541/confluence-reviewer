import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TeamPage from "./TeamPage";
import type { Analyst, Team } from "../api";

function mockFetch(responses: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0];
      const payload = responses[path];
      if (payload !== undefined) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
    }),
  );
}

const TEAM: Team = {
  id: 12,
  cluster_id: 3,
  cluster_name: "Билетный бизнес",
  cluster_color: null,
  name: "GDS",
  description: "Бронирование и обмен данными",
  created_at: "2026-01-01T00:00:00",
  analysts: [
    {
      id: 7,
      full_name: "Алиев Рустам",
      email: "aliev@company.ru",
      documents_count: 14,
      domains: ["вывод на витрину", "загрузка данных"],
    },
  ],
  domains: ["вывод на витрину", "загрузка данных"],
};

function renderPage(teamId = "12") {
  return render(
    <MemoryRouter initialEntries={[`/teams/${teamId}`]}>
      <Routes>
        <Route path="/teams/:teamId" element={<TeamPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TeamPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders breadcrumbs, aggregated domains and analyst cards", async () => {
    mockFetch({ "/api/teams/12": TEAM });
    renderPage();

    expect(await screen.findByRole("heading", { name: "GDS" })).toBeInTheDocument();
    // хлебные крошки ведут в кластер
    const crumb = screen.getByText("Билетный бизнес");
    expect(crumb).toHaveAttribute("href", "/clusters/3");
    // агрегированные домены команды (и в карточке аналитика — те же чипы)
    expect(screen.getAllByText("вывод на витрину").length).toBeGreaterThan(0);
    expect(screen.getAllByText("загрузка данных").length).toBeGreaterThan(0);
    expect(screen.getByText("— домены участников")).toBeInTheDocument();
    // карточка аналитика с его доменами
    const person = screen.getByRole("link", { name: /Алиев Рустам/ });
    expect(person).toHaveAttribute("href", "/analysts/7");
  });

  it("shows an empty state for a team without analysts", async () => {
    mockFetch({
      "/api/teams/12": { ...TEAM, analysts: [], domains: [] },
    });
    renderPage();
    expect(await screen.findByText(/В команде ещё нет аналитиков/)).toBeInTheDocument();
  });

  it("shows an error when the team is missing", async () => {
    mockFetch({});
    renderPage("999");
    expect(await screen.findByText("не найдено")).toBeInTheDocument();
  });

  it("adds an analyst through the modal with domains, excluding current members", async () => {
    const FREE: Analyst = {
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
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/teams/12/analysts" && method === "POST") {
        return new Response(JSON.stringify({ id: 12 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = {
        "/api/teams/12": TEAM,
        "/api/analysts": [
          { ...TEAM.analysts[0], confluence_username: null, team_id: 12, team_name: "GDS", cluster_id: 3, cluster_name: "Билетный бизнес" },
          FREE,
        ],
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
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Добавить аналитика/ }));

    // участник команды в списке помечен и заблокирован
    expect(await screen.findByText(/уже в этой команде/)).toBeInTheDocument();
    const memberRow = screen.getByRole("button", { name: /Алиев Рустам/ });
    expect(memberRow).toBeDisabled();

    // поиск и выбор свободного аналитика
    fireEvent.change(screen.getByLabelText("Поиск по ФИО или email"), { target: { value: "Сидоров" } });
    fireEvent.click(await screen.findByRole("button", { name: /Сидоров Пётр/ }));
    fireEvent.change(screen.getByLabelText("Новый домен"), { target: { value: "витрина" } });
    fireEvent.click(screen.getByRole("button", { name: "＋ добавить домен" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/teams/12/analysts" && init?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        analyst_id: 9,
        domains: ["витрина"],
      });
    });
    expect(await screen.findByText("Аналитик добавлен в команду")).toBeInTheDocument();
  });

  it("sends domains: null when nothing typed, keeping the analyst's tags", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/teams/12/analysts" && method === "POST") {
        return new Response(JSON.stringify({ id: 12 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = {
        "/api/teams/12": TEAM,
        "/api/analysts": [
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
            domains: ["букинг"],
          },
        ],
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
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Добавить аналитика/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Сидоров Пётр/ }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/teams/12/analysts" && init?.method === "POST",
      );
      expect(post).toBeDefined();
      // null = «домены не трогать»: перевод не стирает теги аналитика
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        analyst_id: 9,
        domains: null,
      });
    });
  });

  it("removes an analyst after confirm", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/teams/12/analysts/7" && method === "DELETE") {
        return new Response(JSON.stringify({ id: 12, analysts: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = { "/api/teams/12": TEAM };
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

    fireEvent.click(await screen.findByRole("button", { name: "Убрать" }));
    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/teams/12/analysts/7" && init?.method === "DELETE",
      );
      expect(del).toBeDefined();
    });
    expect(await screen.findByText("«Алиев Рустам» убран из команды")).toBeInTheDocument();
  });
});
