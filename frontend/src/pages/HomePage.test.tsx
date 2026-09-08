import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import HomePage from "./HomePage";
import { emitServerEvent } from "../events";
import { pushRecent } from "../recent";
import type { DashboardOut } from "../api";

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

const DASHBOARD: DashboardOut = {
  sections: [
    {
      type: "failed",
      title: "Провалены проверки",
      total: 2,
      items: [
        {
          key: "doc-5",
          title: "Системные требования СМЭ",
          subtitle: "Алиев Рустам · GDS · ИИ-проверка: есть замечания",
          at: "2026-09-10T09:41:00",
          document_id: 5,
          analyst_id: null,
          template_id: null,
          section: null,
        },
        {
          key: "doc-6",
          title: "Доработка витрины",
          subtitle: "Белышева Жанна · Финтех · не пройдена проверка по шаблону",
          at: null,
          document_id: 6,
          analyst_id: null,
          template_id: null,
          section: null,
        },
      ],
    },
    { type: "stale", title: "Устарели после правок в Confluence", total: 0, items: [] },
    { type: "ratings", title: "Ждут оценки руководителя", total: 0, items: [] },
    {
      type: "no_team",
      title: "Аналитики без команды",
      total: 1,
      items: [
        {
          key: "analyst-9",
          title: "Сидоров Пётр",
          subtitle: "sidorov@company.ru · 5 документов",
          at: null,
          document_id: null,
          analyst_id: 9,
          template_id: null,
          section: null,
        },
      ],
    },
    { type: "references", title: "Проблемы справочников", total: 0, items: [] },
  ],
};

const CLUSTERS = [
  {
    id: 3,
    name: "Билетный бизнес",
    description: null,
    color: "#0C66E4",
    created_at: "2026-01-01T00:00:00",
    teams_count: 1,
    analysts_count: 1,
    documents_count: 4,
    teams: [{ id: 12, name: "GDS", description: null, analysts_count: 1 }],
  },
];

function baseResponses(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    "/api/dashboard": DASHBOARD,
    "/api/clusters": CLUSTERS,
    "/api/analysts": [
      { id: 9, full_name: "Сидоров Пётр", team_id: null },
      { id: 7, full_name: "Алиев Рустам", team_id: 12 },
    ],
    "/api/sync/status": { running: false, started_at: null, finished_at: null, error: null, last_results: [] },
    "/api/sync/bulk-validation": { running: false, analyst_id: null, total: 0, done: 0, started_at: null, finished_at: null },
    "/api/dashboard/feed": [],
    "/api/templates": [{ id: 1, name: "СТ", is_default: true, is_archived: false }],
    "/api/ai-criteria": [{ id: 1, is_archived: false }],
    "/api/ai-settings": {
      protocol: "openai-compatible",
      base_url: "https://ai.test/v1",
      model: "glm-4.6",
      api_key_masked: "sk-…",
      updated_at: null,
      env: { protocol: "openai-compatible", base_url: "", model: "", api_key_set: false },
    },
    ...extra,
  };
}

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/documents/:documentId" element={<div>Экран отчёта</div>} />
        <Route path="/analysts/:analystId" element={<div>Экран профиля</div>} />
        <Route path="/clusters/:clusterId" element={<div>Экран кластера</div>} />
        <Route path="/clusters" element={<div>Карта кластеров</div>} />
        <Route path="/templates" element={<div>Шаблоны</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HomePage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders attention sections with counters and item subtitles", async () => {
    mockFetch(baseResponses());
    renderHome();

    // первая секция раскрыта: строки с причинами
    expect(await screen.findByText("Системные требования СМЭ")).toBeInTheDocument();
    expect(screen.getByText(/ИИ-проверка: есть замечания/)).toBeInTheDocument();
    expect(screen.getByText(/не пройдена проверка по шаблону/)).toBeInTheDocument();
    // счётчик секции = полный total (2), а не число показанных строк
    const failedHead = screen.getByRole("button", { name: /Провалены проверки/ });
    expect(within(failedHead).getByText("2")).toBeInTheDocument();
    // свёрнутые секции не показывают строк, пока не раскрыты
    expect(screen.queryByText("Сидоров Пётр")).not.toBeInTheDocument();
  });

  it("navigates from a queue item to the document report", async () => {
    mockFetch(baseResponses());
    renderHome();

    fireEvent.click(await screen.findByText("Системные требования СМЭ"));
    expect(await screen.findByText("Экран отчёта")).toBeInTheDocument();
  });

  it("navigates an unassigned analyst to their profile after expanding the section", async () => {
    mockFetch(baseResponses());
    renderHome();

    fireEvent.click(await screen.findByRole("button", { name: /Аналитики без команды/ }));
    fireEvent.click(await screen.findByText("Сидоров Пётр"));
    expect(await screen.findByText("Экран профиля")).toBeInTheDocument();
  });

  it("expands and collapses sections on demand", async () => {
    mockFetch(baseResponses());
    renderHome();

    await screen.findByText("Системные требования СМЭ");
    fireEvent.click(screen.getByRole("button", { name: /Провалены проверки/ }));
    expect(screen.queryByText("Системные требования СМЭ")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Провалены проверки/ }));
    expect(await screen.findByText("Системные требования СМЭ")).toBeInTheDocument();
  });

  it("shows the all-clear state when nothing needs attention", async () => {
    const empty: DashboardOut = {
      sections: DASHBOARD.sections.map((s) => ({ ...s, total: 0, items: [] })),
    };
    mockFetch({ ...baseResponses(), "/api/dashboard": empty });
    renderHome();

    expect(await screen.findByText(/Всё под контролем/)).toBeInTheDocument();
  });

  it("shows live feed from the server journal and prepends SSE events", async () => {
    const fetchMock = mockFetch(
      baseResponses({
        "/api/dashboard/feed": [
          { type: "sync", at: "2026-09-10T09:00:00", payload: { running: false, last_results: [{ created: 2, updated: 5 }] } },
        ],
      }),
    );
    renderHome();

    // журнал: последнее событие синхронизации с итогом
    expect(await screen.findByText("Синхронизация завершена")).toBeInTheDocument();
    expect(screen.getByText("+2 новых, 5 обновлено")).toBeInTheDocument();

    // живое событие приходит само и встаёт наверх ленты
    emitServerEvent("validation", { type: "validation", document_id: 5, status: "done", report_id: 77, at: new Date().toISOString() });
    expect(await screen.findByText("Проверка завершена")).toBeInTheDocument();
    const first = screen.getAllByText(/Проверка завершена|Синхронизация завершена/)[0];
    expect(first).toHaveTextContent("Проверка завершена");
    expect(fetchMock.mock.calls.some(([u]) => String(u) === "/api/dashboard/feed")).toBe(true);
  });

  it("reflects a running bulk validation in 'Сейчас происходит'", async () => {
    mockFetch(
      baseResponses({
        "/api/sync/bulk-validation": {
          running: true, analyst_id: 7, total: 7, done: 3, started_at: null, finished_at: null,
        },
      }),
    );
    renderHome();

    const nowPanel = (await screen.findByText("⏳ Сейчас происходит")).closest(".panel");
    expect(within(nowPanel as HTMLElement).getByText("3 из 7")).toBeInTheDocument();
  });

  it("warns when AI connection is not configured", async () => {
    mockFetch(
      baseResponses({
        "/api/ai-settings": {
          protocol: "openai-compatible",
          base_url: "",
          model: "",
          api_key_masked: "",
          updated_at: null,
          env: { protocol: "openai-compatible", base_url: "", model: "", api_key_set: false },
        },
      }),
    );
    renderHome();

    const chip = await screen.findByText("⚡ Подключите ИИ");
    expect(chip.closest("a")).toHaveAttribute("href", "/ai-connection");
  });

  it("lists recently visited objects with links", async () => {
    pushRecent("document", 5, "Системные требования СМЭ");
    pushRecent("cluster", 3, "Билетный бизнес");
    mockFetch(baseResponses());
    renderHome();

    const docs = await screen.findAllByRole("link", { name: /Системные требования СМЭ/ });
    expect(docs.some((a) => a.getAttribute("href") === "/documents/5")).toBe(true);
    const clusters = screen.getAllByRole("link", { name: /Билетный бизнес/ });
    expect(clusters.some((a) => a.getAttribute("href") === "/clusters/3")).toBe(true);
  });

  it("renders the collapsed structure mini-map", async () => {
    mockFetch(baseResponses());
    renderHome();

    const map = (await screen.findByText("🗂 Структура")).closest(".panel");
    const gds = within(map as HTMLElement).getByText("GDS");
    expect(gds).toBeInTheDocument();
  });
});
