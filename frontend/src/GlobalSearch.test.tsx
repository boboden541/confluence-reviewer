import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import GlobalSearch from "./GlobalSearch";

const DEBOUNCE_MS = 300; // как в GlobalSearch

// зонд маршрута: показываем, куда ушёл переход
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderSearch() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<GlobalSearch />} />
        <Route path="/documents/:documentId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const HITS = [
  {
    id: 11,
    title: "[СТ] GDS-15 Загрузка кино",
    validation_status: "failed",
    analyst_id: 5,
    analyst_name: "Никулин Владислав",
  },
  {
    id: 12,
    title: "GDS-15 ревью",
    validation_status: "passed",
    analyst_id: 6,
    analyst_name: "Второй Аналитик",
  },
];

function mockFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input).split("?")[0];
    if (path === "/api/documents/search") {
      return new Response(JSON.stringify(HITS), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Набираем запрос и проматываем дебаунс. */
async function typeAndWait(value: string) {
  await act(async () => {
    fireEvent.change(screen.getByLabelText("Поиск документов"), { target: { value } });
    vi.advanceTimersByTime(DEBOUNCE_MS);
  });
}

describe("GlobalSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("показывает результаты всех аналитиков после паузы в наборе", async () => {
    const fetchMock = mockFetch();
    renderSearch();

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Поиск документов"), {
        target: { value: "GDS" },
      });
    });
    // дебаунс: сразу после набора бэкенд не дёргаем
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("[СТ] GDS-15 Загрузка кино")).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(DEBOUNCE_MS);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("q=GDS");
    screen.getByText("[СТ] GDS-15 Загрузка кино");
    screen.getByText("Никулин Владислав");
    screen.getByText("GDS-15 ревью");
  });

  it("короткий запрос не уходит на бэкенд", async () => {
    const fetchMock = mockFetch();
    renderSearch();

    await act(async () => {
      fireEvent.change(screen.getByLabelText("Поиск документов"), {
        target: { value: "G" },
      });
      vi.advanceTimersByTime(DEBOUNCE_MS + 100);
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("[СТ] GDS-15 Загрузка кино")).toBeNull();
  });

  it("клик по результату открывает отчёт документа", async () => {
    mockFetch();
    renderSearch();
    await typeAndWait("GDS");

    await act(async () => {
      fireEvent.click(screen.getByText("GDS-15 ревью"));
    });

    expect(screen.getByTestId("location")).toHaveTextContent("/documents/12");
  });

  it("Enter открывает первый результат", async () => {
    mockFetch();
    renderSearch();
    await typeAndWait("GDS");

    await act(async () => {
      fireEvent.keyDown(screen.getByLabelText("Поиск документов"), { key: "Enter" });
    });

    expect(screen.getByTestId("location")).toHaveTextContent("/documents/11");
  });
});
