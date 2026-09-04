import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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
  {
    id: 4,
    name: "Медиа",
    description: "Медиа-экосистема",
    color: "#6E5DC6",
    created_at: "2026-01-02T00:00:00",
    teams_count: 1,
    analysts_count: 1,
    documents_count: 17,
    teams: [{ id: 21, name: "Развитие SEO", description: null, analysts_count: 1 }],
  },
];

const ANALYSTS: Analyst[] = [
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
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<ClustersPage />} />
        <Route path="/clusters/:clusterId" element={<div>Экран кластера</div>} />
        <Route path="/teams/:teamId" element={<div>Экран команды</div>} />
        <Route path="/analysts/:analystId" element={<div>Профиль</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function baseMock(extra: Record<string, unknown> = {}) {
  return { "/api/clusters": CLUSTERS, "/api/analysts": ANALYSTS, ...extra };
}

describe("ClustersPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders cluster cards with counters and team chips", async () => {
    mockFetch(baseMock());
    renderPage();

    // карточка кластера — кликабельный элемент с aria-меткой
    const card = await screen.findByRole("link", { name: "Кластер Билетный бизнес" });
    expect(card).toBeInTheDocument();
    expect(screen.getByText("Продажи билетов")).toBeInTheDocument();
    const gds = screen.getByRole("link", { name: /GDS/ });
    expect(gds).toHaveAttribute("href", "/teams/12");
    expect(screen.getByRole("link", { name: /Финтех/ })).toHaveAttribute("href", "/teams/13");
    expect(screen.getByText("42")).toBeInTheDocument(); // документов
  });

  it("navigates to the cluster page when clicking anywhere on the card", async () => {
    mockFetch(baseMock());
    renderPage();

    // клик не по заголовку, а по счётчикам — вглубь карточки
    fireEvent.click(await screen.findByText("42"));
    expect(await screen.findByText("Экран кластера")).toBeInTheDocument();
  });

  it("card action buttons do not trigger navigation", async () => {
    mockFetch(baseMock());
    renderPage();

    // «Изменить» на карточке Билетного бизнеса открывает модалку,
    // а не уводит на экран кластера
    const card = await screen.findByRole("link", { name: "Кластер Билетный бизнес" });
    fireEvent.click(within(card).getByRole("button", { name: /Изменить/ }));
    expect(await screen.findByRole("dialog", { name: "Кластер" })).toBeInTheDocument();
    expect(screen.queryByText("Экран кластера")).not.toBeInTheDocument();
  });

  it("filters clusters with fuzzy search as you type", async () => {
    mockFetch(baseMock());
    renderPage();

    const input = await screen.findByLabelText("Поиск кластеров");
    // опечатка в «билетный» — нечёткий поиск всё равно находит
    fireEvent.change(input, { target: { value: "билетнй бизнес" } });
    expect(screen.getByRole("link", { name: "Кластер Билетный бизнес" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Кластер Медиа" })).not.toBeInTheDocument();

    // ищем по названию команды — находим кластер, в котором она состоит
    fireEvent.change(input, { target: { value: "SEO" } });
    expect(screen.getByRole("link", { name: "Кластер Медиа" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Кластер Билетный бизнес" })).not.toBeInTheDocument();

    // очистка возвращает всё
    fireEvent.click(screen.getByRole("button", { name: "Очистить поиск" }));
    expect(screen.getByRole("link", { name: "Кластер Медиа" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Кластер Билетный бизнес" })).toBeInTheDocument();
  });

  it("opens the team-creation popup right from the cluster card", async () => {
    const fetchMock = mockFetch(
      baseMock({ "POST /api/teams": { id: 14, cluster_id: 3, name: "Возвраты" } }),
    );
    renderPage();

    // кнопка «＋ команда» на карточке — не навигация, а попап
    const card = await screen.findByRole("link", { name: "Кластер Билетный бизнес" });
    fireEvent.click(within(card).getByRole("button", { name: "＋ команда" }));
    const dialog = await screen.findByRole("dialog", { name: "Команда" });
    expect(dialog).toHaveTextContent("Билетный бизнес");
    expect(screen.queryByText("Экран кластера")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Название *"), { target: { value: "Возвраты" } });
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
    expect(
      await screen.findByText("Команда «Возвраты» создана в кластере «Билетный бизнес»"),
    ).toBeInTheDocument();
  });

  it("shows only unassigned analysts in 'Без команды'", async () => {
    mockFetch(baseMock());
    renderPage();

    const free = await screen.findByRole("link", { name: /Сидоров Пётр/ });
    expect(free).toHaveAttribute("href", "/analysts/9");
  });

  it("creates a cluster through the modal and reloads", async () => {
    const fetchMock = mockFetch(
      baseMock({ "POST /api/clusters": { ...CLUSTERS[0], id: 4, name: "Медиа" } }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Новый кластер/ }));
    fireEvent.change(await screen.findByLabelText("Название *"), { target: { value: "Медиа" } });
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

  it("shows 'Без команды' empty state only when there are free analysts", async () => {
    mockFetch({
      "/api/clusters": [],
      "/api/analysts": [],
    });
    renderPage();

    expect(await screen.findByText(/Кластеров ещё нет/)).toBeInTheDocument();
    expect(screen.queryByText("Без команды")).not.toBeInTheDocument();
  });
});
