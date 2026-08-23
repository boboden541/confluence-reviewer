import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

/** fetch-мок с точным сопоставлением пути (префиксы /api/template и /api/template/versions конфликтуют). */
function mockFetch(
  responses: Record<string, unknown>,
  handlers: {
    put?: (body: unknown) => { status: number; payload: unknown };
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    if (path === "/api/template" && init?.method === "PUT" && handlers.put) {
      const { status, payload } = handlers.put(JSON.parse(String(init.body)));
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

function renderPage() {
  render(
    <MemoryRouter>
      <TemplatePage />
    </MemoryRouter>,
  );
}

function rowInputs(): HTMLInputElement[] {
  return screen
    .getAllByPlaceholderText("Название раздела")
    .map((el) => el as HTMLInputElement);
}

describe("TemplatePage", () => {
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
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });

    renderPage();

    expect(await screen.findByDisplayValue("Введение")).toBeInTheDocument();
    expect((screen.getByDisplayValue("СТ") as HTMLInputElement).value).toBe("СТ");
    const preview = screen.getByText("Структура разделов (1 → 1.1 → 1.1.1):").parentElement!;
    expect(preview.textContent).toContain("1.✱ Введение");
    expect(preview.textContent).toContain("1.1.✱ Общая информация");
    expect(preview.textContent).toContain("2.✱ Общее описание");
    expect(screen.getByText(/версия №1/)).toBeInTheDocument();
  });

  it("маркер названия: чипы-примеры переключаются ok/bad", async () => {
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    const withMarker = screen.getByText("[СТ] GDS-15 Загрузка кино");
    const withoutMarker = screen.getByText("GDS-15 Загрузка кино");
    expect(withMarker.className).toContain("ok");
    expect(withoutMarker.className).toContain("bad");

    // поменяли маркер на GDS — первый пример перестаёт проходить отдельно-словной проверкой?
    // «[СТ] GDS-15…» содержит «GDS» отдельным словом → ok; «GDS-15 Загрузка кино» тоже ok
    fireEvent.change(screen.getByDisplayValue("СТ"), { target: { value: "GDS" } });
    expect(withoutMarker.className).toContain("ok");

    // маркер-вхождение внутри слова не считается
    fireEvent.change(screen.getByDisplayValue("GDS"), { target: { value: "за" } });
    expect(withoutMarker.className).toContain("bad"); // «Загрузка» не содержит «за» отдельным словом
  });

  it("переключение ✱ сразу видно в предпросмотре", async () => {
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getAllByTitle("Обязательный раздел")[0]);
    const preview = screen.getByText(/1\.1\.1/).parentElement!;
    expect(preview.textContent).toContain("1.○ Введение");
  });

  it("удаление убирает раздел вместе с подразделами", async () => {
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    // удаляем «Введение» — вместе с ним уходит «Общая информация» (Ур.2)
    fireEvent.click(screen.getAllByTitle("Удалить вместе с подразделами")[0]);
    const inputs = rowInputs();
    expect(inputs.map((i) => i.value)).toEqual(["Общее описание"]);
  });

  it("смена уровня пересчитывает нумерацию", async () => {
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    // «Общее описание» (Ур.1) делаем Ур.2 → нумерация 1 / 1.1 / 1.2
    fireEvent.change(screen.getAllByLabelText("Уровень раздела «Общее описание»")[0], {
      target: { value: "2" },
    });
    const preview = screen.getByText(/1\.1\.1/).parentElement!;
    expect(preview.textContent).toContain("1.2.✱ Общее описание");
  });

  it("добавляет новый раздел в конец", async () => {
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.click(screen.getByText("+ Добавить раздел"));
    const inputs = rowInputs();
    expect(inputs[inputs.length - 1].value).toBe("Новый раздел");
  });

  it("сохранение шлёт PUT с маркером и секциями, алиасы парсятся по запятой", async () => {
    const fetchMock = mockFetch(
      { "/api/template": TEMPLATE, "/api/template/versions": VERSIONS },
      {
        put: (body) => ({
          status: 200,
          payload: { ...TEMPLATE, id: 2, ...(body as object) },
        }),
      },
    );
    renderPage();
    await screen.findByDisplayValue("Введение");

    fireEvent.change(screen.getByDisplayValue("Цель документа"), {
      target: { value: "Цель документа, Назначение системы" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Сохранить шаблон" })[0]);

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/api/template" && init?.method === "PUT",
      ) as [RequestInfo | URL, RequestInit] | undefined;
      expect(put).toBeDefined();
      expect(JSON.parse(String(put![1].body))).toEqual({
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
      { "/api/template": TEMPLATE, "/api/template/versions": VERSIONS },
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
    mockFetch({ "/api/template": TEMPLATE, "/api/template/versions": VERSIONS });
    // jsdom без раскладки: подменяем геометрию всех строк на одинаковую
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
    // курсор в середине строки «Введение» (top=100, height=40) → зона nest
    fireEvent.dragOver(rows[0], { clientY: 120 });
    expect(rows[0].className).toContain("nest-target");

    fireEvent.drop(rows[0], { clientY: 120 });

    // «Общее описание» вложилось последним ребёнком «Введения»: Ур.2 после «Общей информации»
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
      if (path === "/api/template") {
        reloads += 1;
        return new Response(JSON.stringify(TEMPLATE), { status: 200 });
      }
      if (path === "/api/template/versions") {
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
});
