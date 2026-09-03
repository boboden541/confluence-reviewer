import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("creates a team through the modal and reloads", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/teams" && method === "POST") {
        return new Response(JSON.stringify({ id: 14 }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = { "/api/clusters/3": CLUSTER };
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

    fireEvent.click(await screen.findByRole("button", { name: /Добавить команду/ }));
    fireEvent.change(await screen.findByLabelText("Название *"), { target: { value: "Возвраты" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/teams" && init?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        cluster_id: 3,
        name: "Возвраты",
        description: null,
      });
    });
    expect(await screen.findByText("Команда «Возвраты» создана")).toBeInTheDocument();
  });

  it("deletes a team after confirm", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/teams/12" && method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      const map: Record<string, unknown> = { "/api/clusters/3": CLUSTER };
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

    // у каждой команды-колонны свои кнопки; удаляем первую (GDS)
    const card = (await screen.findByText("GDS")).closest(".team-card");
    fireEvent.click(within(card as HTMLElement).getByRole("button", { name: /Удалить/ }));

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/teams/12" && init?.method === "DELETE",
      );
      expect(del).toBeDefined();
    });
    expect(await screen.findByText("Команда «GDS» удалена")).toBeInTheDocument();
  });

  it("edits the cluster through the modal", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = init?.method ?? "GET";
      if (path === "/api/clusters/3" && method === "PUT") {
        return new Response(JSON.stringify({ ...CLUSTER, description: "Новое описание" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = { "/api/clusters/3": CLUSTER };
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

    fireEvent.click(await screen.findByRole("button", { name: /Редактировать/ }));
    fireEvent.change(await screen.findByLabelText("Описание"), {
      target: { value: "Новое описание" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/clusters/3" && init?.method === "PUT",
      );
      expect(put).toBeDefined();
      expect(JSON.parse(String(put?.[1]?.body))["description"]).toBe("Новое описание");
    });
    expect(await screen.findByText("Кластер сохранён")).toBeInTheDocument();
  });
});
