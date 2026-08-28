import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./App";
import type { Analyst } from "./api";
import { emitServerEvent } from "./events";

// мок: ключи вида "METHOD /path" точечно, голый путь — для GET
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

const ANALYSTS: Analyst[] = [
  {
    id: 5,
    full_name: "Иванов Иван",
    email: "ivanov@bft.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 17,
    last_synced_at: null,
    sync_error: null,
  },
  {
    id: 6,
    full_name: "Козлов Кирилл",
    email: "kozlov@bft.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 0,
    last_synced_at: null,
    sync_error: null,
  },
];

function doc(id: number, title: string) {
  return {
    id,
    confluence_page_id: String(100000 + id),
    title,
    url: "https://confluence/example",
    created_in_confluence_at: "2026-08-01T00:00:00",
    last_modified_in_confluence_at: "2026-08-02T00:00:00",
    validation_status: "not_checked",
    last_validated_at: null,
    has_note: false,
  };
}

const DOC_PAGES = {
  "/api/analysts/5/documents": {
    items: [
      doc(101, "ТЗ Автоматизация отчётности"),
      doc(102, "Требования к модулю интеграции с СМЭВ"),
      doc(103, "BRD Платёжный шлюз"),
      doc(104, "Архитектурные принципы ФТ-платформы"),
      doc(105, "Регламент согласования ТЗ"),
    ],
    total: 17,
    page: 1,
    page_size: 5,
  },
  "/api/analysts/6/documents": { items: [], total: 0, page: 1, page_size: 5 },
};

function baseMocks(extra: Record<string, unknown> = {}) {
  return {
    "/api/analysts": ANALYSTS,
    "/api/sync/status": { running: false, started_at: null, finished_at: null, error: null, last_results: [] },
    ...DOC_PAGES,
    ...extra,
  };
}

function renderSidebar(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar open={false} onClose={() => {}} />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders the analysts tree: group link to / and analyst links to their pages", async () => {
    const fetchMock = mockFetch(baseMocks());
    renderSidebar();

    const group = await screen.findByRole("link", { name: "👥 Аналитики" });
    expect(group).toHaveAttribute("href", "/");
    const analyst = screen.getByRole("link", { name: "Иванов Иван" });
    expect(analyst).toHaveAttribute("href", "/analysts/5");
    // старого пункта «Документы» больше нет — дублирование навигации убрано
    expect(screen.queryByText("Документы")).not.toBeInTheDocument();
    // без раскрытия ветки документы не грузятся — запроса нет вовсе (ленивость)
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/api/analysts/5/documents")),
    ).toBe(false);
  });

  it("expanding an analyst lazily loads 5 docs (page_size=5) and shows the rest-link", async () => {
    const fetchMock = mockFetch(baseMocks());
    renderSidebar();

    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" }));

    const docLink = await screen.findByRole("link", { name: "ТЗ Автоматизация отчётности" });
    expect(docLink).toHaveAttribute("href", "/documents/101");
    expect(screen.getByRole("link", { name: "BRD Платёжный шлюз" })).toBeInTheDocument();
    // грузим ровно последние 5
    const called = fetchMock.mock.calls
      .map(([url]) => String(url))
      .find((url) => url.includes("/api/analysts/5/documents"));
    expect(called).toContain("page_size=5");
    // «остальные» появляются только когда документов больше пяти
    const more = screen.getByRole("link", { name: /Показать остальные документы · 12/ });
    expect(more).toHaveAttribute("href", "/analysts/5/documents");
  });

  it("hides the rest-link when total ≤ 5", async () => {
    mockFetch(
      baseMocks({
        "/api/analysts/6/documents": {
          items: [doc(201, "Единственный документ")],
          total: 1,
          page: 1,
          page_size: 5,
        },
      }),
    );
    renderSidebar();

    // один документ — строки «остальные» нет
    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Козлов Кирилл" }));
    expect(await screen.findByRole("link", { name: "Единственный документ" })).toBeInTheDocument();
    expect(screen.queryByText(/Показать остальные документы/)).not.toBeInTheDocument();
  });

  it("shows 'нет документов' for an analyst without documents", async () => {
    mockFetch(baseMocks());
    renderSidebar();

    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Козлов Кирилл" }));
    expect(await screen.findByText("нет документов")).toBeInTheDocument();
  });

  it("auto-expands the active analyst branch on /analysts/5", async () => {
    mockFetch(baseMocks());
    renderSidebar("/analysts/5");

    // ветка раскрыта без кликов, документы на месте
    expect(await screen.findByRole("link", { name: "ТЗ Автоматизация отчётности" })).toBeInTheDocument();
    const analyst = screen.getByRole("link", { name: "Иванов Иван" });
    expect(analyst).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Документы аналитика Иванов Иван" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("marks the open document active inside the tree", async () => {
    mockFetch(baseMocks());
    renderSidebar("/documents/102");

    // на странице документа активного аналитика в URL нет — ветку раскрываем вручную
    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" }));
    const active = await screen.findByRole("link", { name: "Требования к модулю интеграции с СМЭВ" });
    expect(active).toHaveClass("active");
    expect(screen.getByRole("link", { name: "ТЗ Автоматизация отчётности" }).className).not.toContain("active");
  });

  it("shows an error state and retries on the next expand", async () => {
    let docAttempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0];
      if (path === "/api/analysts/5/documents") {
        docAttempts += 1;
        // первый запрос падает, повторный после сворачивания — отвечает
        if (docAttempts === 1) {
          return new Response(JSON.stringify({ detail: "бой" }), { status: 500 });
        }
        return new Response(JSON.stringify(DOC_PAGES["/api/analysts/5/documents"]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const map: Record<string, unknown> = {
        "/api/analysts": ANALYSTS,
        "/api/sync/status": { running: false, started_at: null, finished_at: null, error: null, last_results: [] },
      };
      return new Response(JSON.stringify(map[path] ?? { detail: "не найдено" }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderSidebar();

    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" }));
    expect(await screen.findByText("не удалось загрузить")).toBeInTheDocument();

    // свернули и раскрыли снова — повторный запрос вытаскивает документы
    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" }));
    fireEvent.click(await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" }));
    expect(await screen.findByRole("link", { name: "BRD Платёжный шлюз" })).toBeInTheDocument();
    expect(docAttempts).toBe(2);
  });

  it("collapses the whole analysts group with the group arrow", async () => {
    mockFetch(baseMocks());
    renderSidebar();

    const group = await screen.findByRole("button", { name: "Список аналитиков в дереве" });
    expect(group).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(group);
    expect(screen.queryByRole("link", { name: "Иванов Иван" })).not.toBeInTheDocument();
    expect(group).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(group);
    expect(await screen.findByRole("link", { name: "Иванов Иван" })).toBeInTheDocument();
  });

  it("caches the branch: re-expanding does not refetch", async () => {
    const fetchMock = mockFetch(baseMocks());
    renderSidebar();

    const disc = await screen.findByRole("button", { name: "Документы аналитика Иванов Иван" });
    fireEvent.click(disc);
    expect(await screen.findByRole("link", { name: "BRD Платёжный шлюз" })).toBeInTheDocument();
    const docCalls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/analysts/5/documents")).length;
    expect(docCalls()).toBe(1);

    // свернули и раскрыли снова — документы из кэша, без повторного запроса
    fireEvent.click(disc);
    fireEvent.click(disc);
    expect(await screen.findByRole("link", { name: "BRD Платёжный шлюз" })).toBeInTheDocument();
    expect(docCalls()).toBe(1);
  });

  it("resizes the sidebar by dragging the right edge, clamps and persists", async () => {
    mockFetch(baseMocks());
    const { container } = renderSidebar();

    const handle = await screen.findByRole("separator", { name: /Изменить ширину сайдбара/ });
    const w = () => (container.querySelector(".sidebar") as HTMLElement).style.getPropertyValue("--sidebar-w");
    expect(w()).toBe("256px");

    // jsdom без PointerEvent: fireEvent теряет clientX, собираем события сами
    const pointer = (type: string, x: number) => {
      const Ctor = window.PointerEvent ?? window.MouseEvent;
      return new Ctor(type, {
        bubbles: true,
        cancelable: true,
        pointerId: 1,
        clientX: x,
      } as PointerEventInit);
    };
    // потянули далеко вправо — верхний кламп 480
    fireEvent(handle, pointer("pointerdown", 256));
    fireEvent(handle, pointer("pointermove", 600));
    expect(w()).toBe("480px");
    fireEvent(handle, pointer("pointerup", 600));
    expect(localStorage.getItem("cr-sidebar-w")).toBe("480");

    // влево почти в ноль — нижний кламп 200; двойной клик — сброс к стандартной
    fireEvent(handle, pointer("pointerdown", 480));
    fireEvent(handle, pointer("pointermove", 100));
    expect(w()).toBe("200px");
    fireEvent(handle, pointer("pointerup", 100));
    fireEvent.dblClick(handle);
    expect(w()).toBe("256px");
    expect(localStorage.getItem("cr-sidebar-w")).toBe("256");
  });

  it("resizes the sidebar with arrow keys and remembers the width", async () => {
    mockFetch(baseMocks());
    const { container } = renderSidebar();

    const handle = await screen.findByRole("separator", { name: /Изменить ширину сайдбара/ });
    const w = () => (container.querySelector(".sidebar") as HTMLElement).style.getPropertyValue("--sidebar-w");

    fireEvent.keyDown(handle, { key: "ArrowRight" }); // вправо — шире
    expect(w()).toBe("288px");
    fireEvent.keyDown(handle, { key: "ArrowLeft" }); // влево — уже
    expect(w()).toBe("256px");
    expect(localStorage.getItem("cr-sidebar-w")).toBe("256");
  });

  it("restores the saved sidebar width from localStorage", async () => {
    localStorage.setItem("cr-sidebar-w", "300");
    mockFetch(baseMocks());
    const { container } = renderSidebar();

    await screen.findByRole("link", { name: "Иванов Иван" });
    expect(
      (container.querySelector(".sidebar") as HTMLElement).style.getPropertyValue("--sidebar-w"),
    ).toBe("300px");
  });

  it("falls back to the default width for invalid saved values", async () => {
    localStorage.setItem("cr-sidebar-w", "999"); // вне диапазона
    mockFetch(baseMocks());
    const { container } = renderSidebar();

    await screen.findByRole("link", { name: "Иванов Иван" });
    expect(
      (container.querySelector(".sidebar") as HTMLElement).style.getPropertyValue("--sidebar-w"),
    ).toBe("256px");
  });

  it("живые события sync меняют статус в футере сайдбара", async () => {
    const fetchMock = mockFetch(baseMocks());
    renderSidebar();

    expect(
      await screen.findByText("⟳ Синхронизация ещё не запускалась"),
    ).toBeInTheDocument();

    // плановая синхронизация стартовала — футер ожил сам
    emitServerEvent("sync", {
      type: "sync", running: true, started_at: "2026-08-26T10:00:00",
      finished_at: null, error: null, last_results: [],
    });
    expect(await screen.findByText("⟳ Идёт синхронизация…")).toBeInTheDocument();

    const analystLoads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url) === "/api/analysts").length;
    const before = analystLoads();

    // завершилась — время последнего прогона и свежий список аналитиков
    emitServerEvent("sync", {
      type: "sync", running: false, started_at: "2026-08-26T10:00:00",
      finished_at: "2026-08-26T10:05:00", error: null, last_results: [],
    });
    await waitFor(() => {
      expect(analystLoads()).toBeGreaterThan(before);
    });
    expect(screen.getByText(/⟳ Синхронизация: 26\.08\.2026/)).toBeInTheDocument();
  });
});
