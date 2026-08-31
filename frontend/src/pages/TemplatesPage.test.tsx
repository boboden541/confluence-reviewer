import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TemplatesPage from "./TemplatesPage";
import type { TemplateCard } from "../api";

const CARDS: TemplateCard[] = [
  {
    id: 1,
    name: "Шаблон системных требований",
    description: null,
    is_default: true,
    is_archived: false,
    active_version_id: 3,
    active_version_created_at: "2026-08-26T10:00:00",
    section_count: 12,
    title_marker: "СТ",
  },
  {
    id: 2,
    name: "Шаблон интеграционных доработок",
    description: "для доработок интеграций",
    is_default: false,
    is_archived: false,
    active_version_id: 5,
    active_version_created_at: "2026-08-25T10:00:00",
    section_count: 9,
    title_marker: "ИНТ",
  },
  {
    id: 3,
    name: "Старый шаблон 2025",
    description: null,
    is_default: false,
    is_archived: true,
    active_version_id: 14,
    active_version_created_at: "2026-03-03T10:00:00",
    section_count: 11,
    title_marker: "",
  },
];

function mockFetch(responses: Record<string, unknown>, posts: string[] = []) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    if (init?.method === "POST" && posts.includes(path)) {
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    for (const [exact, payload] of Object.entries(responses)) {
      if (path === exact) {
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

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/templates"]}>
      <Routes>
        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="/templates/new" element={<p>экран создания</p>} />
        <Route path="/templates/:templateId" element={<p>экран редактора</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TemplatesPage: список карточек", () => {
  it("активные карточки с метой и лозенгами, архив — отдельным блоком", async () => {
    mockFetch({ "/api/templates": CARDS });
    renderPage();

    expect(await screen.findByText("Шаблон системных требований")).toBeInTheDocument();
    expect(screen.getByText("Шаблон интеграционных доработок")).toBeInTheDocument();
    expect(screen.getAllByText("по умолчанию").length).toBe(1);

    // мета активной карточки: разделы, версия, дата, маркер
    expect(screen.getByText(/12 разделов · версия №3/)).toBeInTheDocument();
    expect(screen.getByText(/маркер названия: «СТ»/)).toBeInTheDocument();

    // у дефолтной нет кнопки «По умолчанию», у второй есть
    expect(screen.getAllByRole("button", { name: "По умолчанию" }).length).toBe(1);

    // архивный блок
    expect(screen.getByText("Архив")).toBeInTheDocument();
    expect(screen.getByText("Старый шаблон 2025")).toBeInTheDocument();
    expect(screen.getByText("в архиве")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Вернуть из архива" })).toBeInTheDocument();

    // карточка создания
    expect(screen.getByRole("button", { name: /Создать шаблон/ })).toBeInTheDocument();
  });

  it("действия карточки шлют POST и перечитывают список", async () => {
    const fetchMock = mockFetch({ "/api/templates": CARDS }, ["/api/templates/2/default"]);
    renderPage();
    await screen.findByText("Шаблон интеграционных доработок");

    fireEvent.click(screen.getByRole("button", { name: "По умолчанию" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input) === "/api/templates/2/default" && init?.method === "POST",
        ),
      ).toBe(true);
    });
    // список перечитан
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/api/templates").length).toBe(2);
    });
  });

  it("клик по карточке и по «+» ведёт на соответствующие экраны", async () => {
    mockFetch({ "/api/templates": CARDS });
    renderPage();
    await screen.findByText("Шаблон интеграционных доработок");

    fireEvent.click(screen.getAllByRole("button", { name: "Открыть" })[1]);
    expect(await screen.findByText("экран редактора")).toBeInTheDocument();
  });

  it("карточка «+» открывает экран создания", async () => {
    mockFetch({ "/api/templates": CARDS });
    renderPage();
    await screen.findByText("Шаблон системных требований");

    fireEvent.click(screen.getByRole("button", { name: /Создать шаблон/ }));
    expect(await screen.findByText("экран создания")).toBeInTheDocument();
  });

  it("ошибка загрузки показывается alerts", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "БД недоступна" }), { status: 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    expect(await screen.findByText("БД недоступна")).toBeInTheDocument();
  });
});
