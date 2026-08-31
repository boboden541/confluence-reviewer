import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import TemplatePage from "./TemplatePage";
import { AUTH_STORAGE_KEY, type TemplateInfo, type TemplateVersionInfo } from "../api";

const TEMPLATE: TemplateInfo = {
  id: 1,
  name: "Шаблон системных требований [СТ] (MTSLIVE)",
  description: null,
  title_marker: "СТ",
  created_at: "2026-08-20T10:00:00",
  sections: [
    { level: 1, text: "Введение", required: true, aliases: [] },
    { level: 2, text: "Общая информация", required: true, aliases: [] },
    { level: 1, text: "Общее описание", required: true, aliases: ["Цель документа"] },
  ],
};

const VERSIONS: TemplateVersionInfo[] = [
  { id: 1, name: "Шаблон", created_at: "2026-08-20T10:00:00", is_active: true, section_count: 3 },
];

/** fetch-мок с точным сопоставлением пути и метода. */
function mockFetch(
  responses: Record<string, unknown>,
  handlers: {
    put?: (body: unknown) => { status: number; payload: unknown };
    post?: (path: string, body: unknown) => { status: number; payload: unknown };
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    if (init?.method === "PUT" && handlers.put) {
      const { status, payload } = handlers.put(JSON.parse(String(init.body)));
      return new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (init?.method === "POST" && handlers.post) {
      const { status, payload } = handlers.post(path, init.body ? JSON.parse(String(init.body)) : null);
      return new Response(JSON.stringify(payload), {
        status,
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

function renderPage(url = "/templates/1") {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/templates/new" element={<TemplatePage />} />
        <Route path="/templates/:templateId" element={<TemplatePage />} />
        <Route path="/templates" element={<p>список шаблонов</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function rowInputs(): HTMLInputElement[] {
  return screen
    .getAllByPlaceholderText("Название раздела")
    .map((el) => el as HTMLInputElement);
}

describe("TemplatePage: редактирование", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("загружает шаблон и показывает предпросмотр с иерархической нумерацией", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });

    renderPage();

    expect(await screen.findByDisplayValue("Введение")).toBeInTheDocument();
    expect((screen.getByDisplayValue("СТ") as HTMLInputElement).value).toBe("СТ");
    // название шаблона — редактируемое поле
    expect(
      (screen.getByLabelText(/Название \(видно в диалоге проверки\)/) as HTMLInputElement).value,
    ).toBe("Шаблон системных требований [СТ] (MTSLIVE)");
    const preview = screen.getByText("Структура разделов (1 → 1.1 → 1.1.1):").parentElement!;
    expect(preview.textContent).toContain("1.✱ Введение");
    expect(preview.textContent).toContain("1.1.✱ Общая информация");
    expect(preview.textContent).toContain("2.✱ Общее описание");
    expect(screen.getByText(/версия №1/)).toBeInTheDocument();
  });

  it("маркер названия: чипы-примеры переключаются ok/bad", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    const withMarker = screen.getByText("[СТ] GDS-15 Загрузка кино");
    const withoutMarker = screen.getByText("GDS-15 Загрузка кино");
    expect(withMarker.className).toContain("ok");
    expect(withoutMarker.className).toContain("bad");

    fireEvent.change(screen.getByDisplayValue("СТ"), { target: { value: "GDS" } });
    expect(withoutMarker.className).toContain("ok");

    fireEvent.change(screen.getByDisplayValue("GDS"), { target: { value: "за" } });
    expect(withoutMarker.className).toContain("bad"); // «Загрузка» не содержит «за» отдельным словом
  });

  it("переключение ✱ сразу видно в предпросмотре", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getAllByTitle("Обязательный раздел")[0]);
    const preview = screen.getByText(/1\.1\.1/).parentElement!;
    expect(preview.textContent).toContain("1.○ Введение");
  });

  it("удаление убирает раздел вместе с подразделами", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getAllByTitle("Удалить вместе с подразделами")[0]);
    const inputs = rowInputs();
    expect(inputs.map((i) => i.value)).toEqual(["Общее описание"]);
  });

  it("смена уровня пересчитывает нумерацию", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.change(screen.getAllByLabelText("Уровень раздела «Общее описание»")[0], {
      target: { value: "2" },
    });
    const preview = screen.getByText(/1\.1\.1/).parentElement!;
    expect(preview.textContent).toContain("1.2.✱ Общее описание");
  });

  it("добавляет новый раздел в конец", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getByText("+ Добавить раздел"));
    const inputs = rowInputs();
    expect(inputs[inputs.length - 1].value).toBe("Новый раздел");
  });

  it("сохранение шлёт PUT с названием, описанием, маркером и секциями", async () => {
    const fetchMock = mockFetch(
      { "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS },
      {
        put: (body) => ({
          status: 200,
          payload: { ...TEMPLATE, id: 2, ...(body as object) },
        }),
      },
    );
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.change(screen.getByLabelText(/Описание \(необязательно\)/), {
      target: { value: "для доработок" },
    });
    fireEvent.change(screen.getByDisplayValue("Цель документа"), {
      target: { value: "Цель документа, Назначение системы" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Сохранить шаблон" })[0]);

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/templates/1" && init?.method === "PUT",
      ) as [RequestInfo | URL, RequestInit] | undefined;
      expect(put).toBeDefined();
      expect(JSON.parse(String(put![1].body))).toEqual({
        name: "Шаблон системных требований [СТ] (MTSLIVE)",
        description: "для доработок",
        title_marker: "СТ",
        sections: [
          { level: 1, text: "Введение", required: true, aliases: [] },
          { level: 2, text: "Общая информация", required: true, aliases: [] },
          {
            level: 1,
            text: "Общее описание",
            required: true,
            aliases: ["Цель документа", "Назначение системы"],
          },
        ],
      });
    });
    expect(await screen.findByText(/Шаблон сохранён — версия №2/)).toBeInTheDocument();
  });

  it("показывает ошибку бэкенда при 422 (дубликаты разделов)", async () => {
    mockFetch(
      { "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS },
      {
        put: () => ({
          status: 422,
          payload: { detail: "Раздел «Риски» повторяется на одном уровне — переименуйте" },
        }),
      },
    );
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getAllByRole("button", { name: "Сохранить шаблон" })[0]);

    expect(await screen.findByText(/повторяется на одном уровне/)).toBeInTheDocument();
  });

  it("drag & drop: вложение «Общее описание» в «Введение» через середину строки", async () => {
    mockFetch({ "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      top: 100,
      bottom: 140,
      height: 40,
      left: 0,
      right: 400,
      width: 400,
      x: 0,
      y: 100,
      toJSON: () => ({}),
    } as DOMRect);

    renderPage();
    await screen.findByDisplayValue("Введение");

    const rows = screen
      .getAllByPlaceholderText("Название раздела")
      .map((input) => input.closest(".section-row") as HTMLElement);

    fireEvent.dragStart(rows[2]); // «Общее описание»
    fireEvent.dragOver(rows[0], { clientY: 120 });
    expect(rows[0].className).toContain("nest-target");

    fireEvent.drop(rows[0], { clientY: 120 });

    const selects = screen
      .getAllByLabelText(/Уровень раздела/)
      .map((el) => el as HTMLSelectElement);
    expect(selects.map((s) => s.value)).toEqual(["1", "2", "2"]);
    const preview = screen.getByText(/1\.1\.1/).parentElement!;
    expect(preview.textContent).toContain("1.1.✱ Общая информация");
    expect(preview.textContent).toContain("1.2.✱ Общее описание");
  });

  it("сброс перечитывает шаблон с сервера", async () => {
    let reloads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input).split("?")[0];
      if (path === "/api/templates/1") {
        reloads += 1;
        return new Response(JSON.stringify(TEMPLATE), { status: 200 });
      }
      if (path === "/api/templates/1/versions") {
        return new Response(JSON.stringify(VERSIONS), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.change(screen.getByDisplayValue("Введение"), { target: { value: "Изменённое" } });
    fireEvent.click(screen.getByRole("button", { name: "Сбросить изменения" }));

    await waitFor(() => {
      expect(screen.getByDisplayValue("Введение")).toBeInTheDocument();
    });
    expect(reloads).toBeGreaterThanOrEqual(2);
  });

  it("«В архив» после подтверждения шлёт POST и уходит в список", async () => {
    const fetchMock = mockFetch(
      { "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS },
      { post: () => ({ status: 200, payload: {} }) },
    );
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getByRole("button", { name: "В архив" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input, init]) => String(input) === "/api/templates/1/archive" && init?.method === "POST")).toBe(true);
    });
    expect(await screen.findByText("список шаблонов")).toBeInTheDocument();
  });

  it("«В архив» без подтверждения ничего не отправляет", async () => {
    const fetchMock = mockFetch(
      { "/api/templates/1": TEMPLATE, "/api/templates/1/versions": VERSIONS },
      { post: () => ({ status: 200, payload: {} }) },
    );
    vi.stubGlobal("confirm", vi.fn(() => false));
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getByRole("button", { name: "В архив" }));

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});

describe("TemplatePage: создание", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("пустая форма, кнопка «Создать шаблон», POST с первым содержимым", async () => {
    const fetchMock = mockFetch(
      {},
      {
        post: () => ({
          status: 201,
          payload: { id: 7, name: "Новый шаблон", is_default: false, is_archived: false, active_version_id: 9, active_version_created_at: null, section_count: 1, title_marker: "СТ", description: null },
        }),
      },
    );
    renderPage("/templates/new");

    expect(await screen.findByText("Новый шаблон требований")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "В архив" })).toBeNull();
    // без названия создание недоступно
    expect(screen.getAllByRole("button", { name: "Создать шаблон" })[0]).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Название \(видно в диалоге проверки\)/), {
      target: { value: "Новый шаблон" },
    });
    fireEvent.change(screen.getByPlaceholderText("например, СТ"), { target: { value: "ИНТ" } });
    fireEvent.click(screen.getByText("+ Добавить раздел"));

    expect(screen.getAllByRole("button", { name: "Создать шаблон" })[0]).toBeEnabled();
    fireEvent.click(screen.getAllByRole("button", { name: "Создать шаблон" })[0]);

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/templates" && init?.method === "POST",
      ) as [RequestInfo | URL, RequestInit] | undefined;
      expect(post).toBeDefined();
      expect(JSON.parse(String(post![1].body))).toEqual({
        name: "Новый шаблон",
        description: null,
        title_marker: "ИНТ",
        sections: [{ level: 1, text: "Новый раздел", required: false, aliases: [] }],
      });
    });
    // после создания открывается редактор созданного шаблона
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input) === "/api/templates/7")).toBe(true);
    });
  });
});
