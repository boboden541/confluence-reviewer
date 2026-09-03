import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ClusterPage from "./ClusterPage";
import type { Cluster } from "../api";

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

const CLUSTER: Cluster = {
  id: 3,
  name: "Билетный бизнес",
  description: "Продажи билетов: витрина, данные, платежи",
  color: "#0C66E4",
  created_at: "2026-01-01T00:00:00",
  teams_count: 2,
  analysts_count: 2,
  documents_count: 42,
  teams: [
    { id: 12, name: "GDS", description: "Бронирование и данные", analysts_count: 1 },
    { id: 13, name: "Финтех", description: null, analysts_count: 1 },
  ],
};

function renderPage(clusterId = "3") {
  return render(
    <MemoryRouter initialEntries={[`/clusters/${clusterId}`]}>
      <Routes>
        <Route path="/clusters/:clusterId" element={<ClusterPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ClusterPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders the cluster header, breadcrumbs and team columns", async () => {
    mockFetch({ "/api/clusters/3": CLUSTER });
    renderPage();

    expect(await screen.findByRole("heading", { name: "Билетный бизнес" })).toBeInTheDocument();
    expect(screen.getByText("Продажи билетов: витрина, данные, платежи")).toBeInTheDocument();
    expect(screen.getByText("Кластеры")).toHaveAttribute("href", "/");
    // команды-колонны ведут на экраны команд
    const gds = screen.getByRole("link", { name: /GDS/ });
    expect(gds).toHaveAttribute("href", "/teams/12");
    expect(screen.getByRole("link", { name: /Финтех/ })).toHaveAttribute("href", "/teams/13");
    expect(screen.getByText("Бронирование и данные")).toBeInTheDocument();
  });

  it("shows an error when the cluster is missing", async () => {
    mockFetch({});
    renderPage("999");
    expect(await screen.findByText("не найдено")).toBeInTheDocument();
  });
});
