import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TeamPage from "./TeamPage";
import type { Team } from "../api";

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
    expect(await screen.findByText("В команде ещё нет аналитиков.")).toBeInTheDocument();
  });

  it("shows an error when the team is missing", async () => {
    mockFetch({});
    renderPage("999");
    expect(await screen.findByText("не найдено")).toBeInTheDocument();
  });
});
