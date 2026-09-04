import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AnalystProfilePage from "./AnalystProfilePage";
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
  team_id: null,
  team_name: null,
  cluster_id: null,
  cluster_name: null,
  domains: [],
};

// аналитик, распределённый по структуре
const IN_TEAM = {
  ...ANALYST,
  team_id: 12,
  team_name: "GDS",
  cluster_id: 3,
  cluster_name: "Билетный бизнес",
  domains: ["вывод на витрину"],
};

const NOTE = { analyst_id: 5, content: "", created_at: null, updated_at: null };

function renderPage(initialEntries: string[] = ["/analysts/5"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/analysts/:analystId" element={<AnalystProfilePage />} />
        <Route
          path="/analysts/:analystId/documents"
          element={<div>Список документов</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AnalystProfilePage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders the analyst card with a link to their documents", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/note": NOTE,
    });
    renderPage();

    // имя видно и в крошках, и в заголовке профиля
    expect(await screen.findAllByText("Иван Тестов")).toHaveLength(2);
    // мета собрана из фрагментов — проверяем строкой
    const meta = document.querySelector(".page-meta")?.textContent ?? "";
    expect(meta).toContain("t@mts.ru");
    expect(meta).toContain("Confluence: ivanov");
    expect(meta).toContain("документов: 12");
    // главная кнопка профиля — переход к документам аналитика
    const docs = await screen.findByRole("link", { name: /Документы \(12\)/ });
    expect(docs).toHaveAttribute("href", "/analysts/5/documents");
    // соседняя — статистика его оценок
    const stats = screen.getByRole("link", { name: /Статистика оценок/ });
    expect(stats).toHaveAttribute("href", "/analysts/5/stats");
  });

  it("loads the note into the editor with a markdown preview", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/note": {
        ...NOTE,
        content: "## Профиль\n- сильные стороны: **декомпозиция**",
      },
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { level: 2, name: "Профиль" }),
    ).toBeInTheDocument();
    expect(screen.getByText("декомпозиция").tagName).toBe("STRONG");
    const editor = screen.getByRole("textbox", { name: "Заметка руководителя" }) as HTMLTextAreaElement;
    expect(editor.value).toBe("## Профиль\n- сильные стороны: **декомпозиция**");
  });

  it("saves the note via PUT", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/note": NOTE,
    });
    renderPage();

    const editor = (await screen.findByRole("textbox", {
      name: "Заметка руководителя",
    })) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "новая заметка" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить заметку" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/analysts/5/note" && init?.method === "PUT",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ content: "новая заметка" });
    });
    expect(await screen.findByText("Заметка сохранена")).toBeInTheDocument();
  });

  it("deletes the note and clears the editor", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/note": { ...NOTE, content: "старая заметка" },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Удалить заметку" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/analysts/5/note" && init?.method === "DELETE",
      );
      expect(call).toBeDefined();
    });
    expect(await screen.findByText("Заметка удалена")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("старая заметка")).not.toBeInTheDocument();
  });

  it("shows the backend error for a missing analyst", async () => {
    mockFetch({}); // и аналитик, и заметка -> 404 из мока
    renderPage();

    expect(await screen.findByText("не найдено")).toBeInTheDocument();
  });

  it("shows cluster/team breadcrumbs for an assigned analyst", async () => {
    mockFetch({
      "/api/analysts/5": IN_TEAM,
      "/api/analysts/5/note": NOTE,
    });
    renderPage();

    // путь кластер → команда → аналитик, всё кликабельно
    const cluster = await screen.findByText("Билетный бизнес");
    expect(cluster).toHaveAttribute("href", "/clusters/3");
    const team = screen.getByText("GDS");
    expect(team).toHaveAttribute("href", "/teams/12");
    expect(screen.getByText("Кластеры")).toHaveAttribute("href", "/");
  });

  it("keeps plain breadcrumbs for an analyst without a team", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/note": NOTE,
    });
    renderPage();

    expect(await screen.findByText("Аналитики")).toHaveAttribute("href", "/analysts");
    expect(screen.queryByText("Кластеры")).not.toBeInTheDocument();
  });

  it("saves edited domains via PUT", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": IN_TEAM,
      "/api/analysts/5/note": NOTE,
      "/api/analysts/5/domains": ["вывод на витрину", "загрузка данных"],
    });
    renderPage();

    // существующий домен загружен, добавляем второй — сохраняется сам
    expect(await screen.findByText("вывод на витрину")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Новый домен"), { target: { value: "загрузка данных" } });
    fireEvent.click(screen.getByRole("button", { name: "＋ добавить домен" }));

    await waitFor(
      () => {
        const call = fetchMock.mock.calls.find(
          ([url, init]) =>
            String(url) === "/api/analysts/5/domains" && init?.method === "PUT",
        );
        expect(call).toBeDefined();
        expect(JSON.parse(String(call?.[1]?.body))).toEqual({
          domains: ["вывод на витрину", "загрузка данных"],
        });
      },
      { timeout: 3000 },
    );
    expect(await screen.findByText("Домены сохранены")).toBeInTheDocument();
  });

  it("adds a domain by pressing Enter and auto-saves it", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": IN_TEAM,
      "/api/analysts/5/note": NOTE,
      "/api/analysts/5/domains": ["вывод на витрину", "букинг"],
    });
    renderPage();

    expect(await screen.findByText("вывод на витрину")).toBeInTheDocument();
    const input = screen.getByLabelText("Новый домен");
    fireEvent.change(input, { target: { value: "букинг" } });
    // Enter вместо кнопки «＋ добавить домен»
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("букинг")).toBeInTheDocument();

    await waitFor(
      () => {
        const call = fetchMock.mock.calls.find(
          ([url, init]) =>
            String(url) === "/api/analysts/5/domains" && init?.method === "PUT",
        );
        expect(call).toBeDefined();
        expect(JSON.parse(String(call?.[1]?.body))).toEqual({
          domains: ["вывод на витрину", "букинг"],
        });
      },
      { timeout: 3000 },
    );
  });
});
