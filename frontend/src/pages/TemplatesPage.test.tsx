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
    // чип «по умолчанию» ровно у одной активной
    expect(screen.getAllByText("по умолчанию").length).toBe(1);

    // мета карточки: версия, разделы, дата создания (макет: «v3 · 12 разделов · …»)
    expect(screen.getByText(/v3 · 12 разделов ·/)).toBeInTheDocument();

    // у дефолтной нет кнопки «По умолчанию», у второй есть
    expect(screen.getAllByRole("button", { name: "⭐ По умолчанию" }).length).toBe(1);

    // архив отдельной секцией с восстановлением
    expect(screen.getByText(/Архив \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Старый шаблон 2025")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "↺ Восстановить" })).toBeInTheDocument();

    // кнопки шапки по макету
    expect(screen.getByRole("button", { name: "🌐 Из общего реестра" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "＋ Новый шаблон" })).toBeInTheDocument();
  });

  it("действия карточки шлют POST и перечитывают список", async () => {
    const fetchMock = mockFetch({ "/api/templates": CARDS }, ["/api/templates/2/default"]);
    renderPage();
    await screen.findByText("Шаблон интеграционных доработок");

    fireEvent.click(screen.getByRole("button", { name: "⭐ По умолчанию" }));

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

  it("Редактировать ведёт на экран редактора", async () => {
    mockFetch({ "/api/templates": CARDS });
    renderPage();
    await screen.findByText("Шаблон интеграционных доработок");

    const edit = screen.getAllByRole("button", { name: "Редактировать" })[1];
    fireEvent.click(edit);
    expect(await screen.findByText("экран редактора")).toBeInTheDocument();
  });

  it("кнопка «Новый шаблон» открывает экран создания", async () => {
    mockFetch({ "/api/templates": CARDS });
    renderPage();
    await screen.findByText("Шаблон системных требований");

    fireEvent.click(screen.getByRole("button", { name: "＋ Новый шаблон" }));
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
