import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AnalystStatsPage from "./AnalystStatsPage";
import { AUTH_STORAGE_KEY } from "../api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input).split("?")[0];
    for (const [route, payload] of Object.entries(responses)) {
      if (path === route) {
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
  full_name: "Иван Тестов",
  email: "t@mts.ru",
  confluence_username: "ivanov",
  created_at: "2026-07-01T00:00:00",
  documents_count: 12,
  last_synced_at: "2026-08-20T10:00:00",
  sync_error: null,
};

const SUMMARY = {
  analyst_id: 5,
  date_from: null,
  date_to: null,
  overall_average: 3.67,
  total_ratings: 3,
  criteria: [
    {
      criterion_id: 2,
      code: "neprotivorechivost",
      name: "Непротиворечивость требований",
      is_archived: true,
      average: 5,
      ratings_count: 1,
    },
    {
      criterion_id: 1,
      code: "polnota",
      name: "Полнота описания",
      is_archived: false,
      average: 3,
      ratings_count: 2,
    },
  ],
};

/** числа на странице — в ru-RU; в тесте форматируем той же локалью */
const ru = (value: number) => value.toLocaleString("ru-RU", { maximumFractionDigits: 1 });

function renderPage(initialEntries: string[] = ["/analysts/5/stats"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/analysts/:analystId/stats" element={<AnalystStatsPage />} />
        <Route path="/analysts/:analystId" element={<div>Профиль аналитика</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AnalystStatsPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders the overall score, bars and archived marks", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/ratings-summary": SUMMARY,
    });
    renderPage();

    // крошка ведёт в профиль; имя повторяется и в подписи страницы
    expect(await screen.findByRole("link", { name: "Иван Тестов" })).toHaveAttribute(
      "href",
      "/analysts/5",
    );
    const meta = document.querySelector(".page-meta")?.textContent ?? "";
    expect(meta).toContain("Иван Тестов");
    expect(meta).toContain("за всё время");
    // название видно и в крошках, и в заголовке страницы
    expect(screen.getAllByText("Статистика оценок")).toHaveLength(2);

    // hero: общий балл и число оценок
    expect(screen.getByText(ru(3.67))).toBeInTheDocument();
    expect(screen.getByText(/3 оценки/)).toBeInTheDocument();

    // бары в порядке убывания среднего: первый ряд — сильнейший критерий
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Непротиворечивость требований");
    expect(rows[0].textContent).toContain("в архиве");
    expect(rows[1].textContent).toContain("Полнота описания");

    // ширина бара = среднее против шкалы 5: 5 → 100%, 3 → 60%
    const fills = document.querySelectorAll<HTMLElement>(".stats-bar-fill");
    expect(fills[0].style.width).toBe("100%");
    expect(fills[1].style.width).toBe("60%");
  });

  it("applies the date filter to the request", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/ratings-summary": SUMMARY,
    });
    renderPage();
    await screen.findByText(/Средние по критериям/);

    fireEvent.change(screen.getByLabelText("Оценки с"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("по"), { target: { value: "2026-08-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url]) =>
          String(url) ===
          "/api/analysts/5/ratings-summary?date_from=2026-08-01&date_to=2026-08-31",
      );
      expect(call).toBeDefined();
    });
    // период виден в подписи страницы
    expect(screen.getByText(/период: 2026-08-01 — 2026-08-31/)).toBeInTheDocument();
  });

  it("resets the filter back to all time", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/ratings-summary": SUMMARY,
    });
    renderPage();
    await screen.findByText(/Средние по критериям/);

    fireEvent.change(screen.getByLabelText("Оценки с"), { target: { value: "2026-08-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("date_from=2026-08-01")),
      ).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: "За всё время" }));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url]) =>
        String(url).startsWith("/api/analysts/5/ratings-summary"),
      );
      expect(calls.length).toBeGreaterThanOrEqual(2);
      expect(String(calls[calls.length - 1][0])).toBe("/api/analysts/5/ratings-summary");
    });
    expect((screen.getByLabelText("Оценки с") as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("button", { name: "За всё время" })).not.toBeInTheDocument();
  });

  it("shows the empty hint when there are no ratings", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/ratings-summary": { ...SUMMARY, overall_average: null, total_ratings: 0, criteria: [] },
    });
    renderPage();

    expect(await screen.findByText(/Оценок пока нет/)).toBeInTheDocument();
    expect(screen.queryByText(/Средние по критериям/)).not.toBeInTheDocument();
  });

  it("shows the backend error for a missing analyst", async () => {
    mockFetch({}); // и аналитик, и статистика -> 404 из мока
    renderPage();

    expect(await screen.findByText("не найдено")).toBeInTheDocument();
  });
});
