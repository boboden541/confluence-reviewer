import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DocumentsPage from "./DocumentsPage";
import { AUTH_STORAGE_KEY } from "../api";

const DOC_DETAIL = {
  id: 11,
  confluence_page_id: "2380439645",
  title: "[СТ] GDS-15 Загрузка кино",
  url: "https://confluence.mts.ru/x/1",
  created_in_confluence_at: "2026-07-01T00:00:00",
  last_modified_in_confluence_at: "2026-08-10T00:00:00",
  validation_status: "failed",
  last_validated_at: "2026-08-11T00:00:00",
  has_note: true,
  content_html: "<h1>Введение</h1>",
  sync_error: null,
  analyst_id: 5,
  analyst_name: "Никулин Владислав",
  analyst_email: "nikulinva@mts.ru",
};

const DOC_REPORT = {
  id: 9,
  document_id: 11,
  triggered_by: "manual",
  created_at: "2026-08-11T12:00:00",
  template_passed: true,
  template_findings: "—",
  ai_passed: true,
  ai_findings: "✅ Замечаний к содержимому нет.",
  overall_passed: true,
  error_message: null,
  comment_sent_at: null,
};

const DOC_NOTE = { document_id: 11, content: "", created_at: null, updated_at: null };

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    const bare = path.split("?")[0];
    for (const [prefix, payload] of Object.entries(responses)) {
      // точное совпадение (с query-строкой) либо без неё
      if (path === prefix || bare === prefix) {
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
  full_name: "Никулин Владислав",
  email: "nikulinva@mts.ru",
  confluence_username: null,
  created_at: "2026-08-01T10:00:00",
  documents_count: 2,
  last_synced_at: null,
  sync_error: null,
};

const DOCUMENTS = {
  items: [
    {
      id: 11,
      confluence_page_id: "2380439645",
      title: "[СТ] GDS-15 Загрузка кино",
      url: "https://confluence.mts.ru/x/1",
      created_in_confluence_at: "2026-07-01T00:00:00",
      last_modified_in_confluence_at: "2026-08-10T00:00:00",
      validation_status: "failed",
      last_validated_at: "2026-08-11T00:00:00",
      has_note: true,
    },
    {
      id: 12,
      confluence_page_id: "2380439999",
      title: "[СТ] Вторая доработка",
      url: "https://confluence.mts.ru/x/2",
      created_in_confluence_at: "2026-07-05T00:00:00",
      last_modified_in_confluence_at: "2026-08-12T00:00:00",
      validation_status: "not_checked",
      last_validated_at: null,
      has_note: false,
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

const VALIDATION_CONFIG = {
  templates: [
    {
      id: 1,
      name: "Шаблон системных требований [СТ] (MTSLIVE)",
      description: "Восстановлен из шаблона Confluence",
      is_default: true,
      section_count: 24,
    },
  ],
  default_prompt: "Ты — опытный ведущий системный аналитик, ревьюер требований.",
};

const BULK_IDLE = {
  running: false,
  analyst_id: null,
  total: 0,
  done: 0,
  started_at: null,
  finished_at: null,
  error: null,
};

describe("DocumentsPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders analyst name and documents with status badges", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Никулин Владислав")).toBeInTheDocument();
    expect(await screen.findByText("[СТ] GDS-15 Загрузка кино")).toBeInTheDocument();
    expect(screen.getByText("не пройдено")).toBeInTheDocument();
    expect(screen.getByText("не проверено")).toBeInTheDocument();
    expect(screen.getByText("Всего документов: 2")).toBeInTheDocument();
    // у первого документа есть заметка — это видно в списке
    expect(screen.getByTitle("Есть заметка руководителя").textContent).toBe("📝");
  });

  it("passes search query to the API", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": { items: [], total: 0, page: 1, page_size: 20 },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText("Поиск по названию…");
    fireEvent.change(input, { target: { value: "GDS" } });

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) =>
        String(url).includes("query=GDS"),
      );
      expect(call).toBeDefined();
    });
  });

  it("restores the search filter from the URL", async () => {
    // после «Назад» из документа адрес ?q=GDS снова ищет по слову
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5?q=GDS"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText("Поиск по названию…");
    expect((input as HTMLInputElement).value).toBe("GDS");
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("query=GDS")),
      ).toBe(true);
    });
  });

  it("shows empty state when no documents match", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": { items: [], total: 0, page: 1, page_size: 20 },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Документы не найдены")).toBeInTheDocument();
  });

  it("semantic search calls the AI endpoint after a pause and shows scores", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/analysts/5/documents/semantic": {
        items: [
          {
            id: 31,
            confluence_page_id: "2380477777",
            title: "Загрузка кинофонда в каталог",
            url: "https://confluence.mts.ru/x/31",
            created_in_confluence_at: "2026-07-01T00:00:00",
            last_modified_in_confluence_at: "2026-08-10T00:00:00",
            validation_status: "not_checked",
            last_validated_at: null,
            has_note: false,
            score: 0.87,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByLabelText(/по смыслу/));
    const input = screen.getByPlaceholderText("Поиск по названию…");
    fireEvent.change(input, { target: { value: "фильмы в каталог" } });
    await vi.advanceTimersByTimeAsync(900);
    vi.useRealTimers();

    expect(await screen.findByText("Загрузка кинофонда в каталог")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
    const semanticCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/documents/semantic"),
    );
    expect(semanticCalls).toHaveLength(1);
    expect(String(semanticCalls[0][0])).toContain("query=");
  });

  it("semantic search waits for at least 3 characters", async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/analysts/5/documents/semantic": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByLabelText(/по смыслу/));
    fireEvent.change(screen.getByPlaceholderText("Поиск по названию…"), {
      target: { value: "фи" },
    });
    await vi.advanceTimersByTimeAsync(2000);
    vi.useRealTimers();

    expect(
      screen.getByText("Введите минимум 3 символа — поиск по смыслу через ИИ"),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.every(([url]) => !String(url).includes("/documents/semantic")),
    ).toBe(true);
  });

  it("runs single validation from the row button through the settings dialog", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/sync/bulk-validation": BULK_IDLE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // doc 11 — failed → «Актуализировать», doc 12 — not_checked → «Проверить»
    const refresh = await screen.findByRole("button", { name: "Актуализировать" });
    fireEvent.click(refresh);

    // кнопка в строке открывает тот же диалог настроек, что и для партии
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Проверка документов")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: /Запустить проверку — 1 док\./ }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/validate-batch" && init?.method === "POST",
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String(call?.[1]?.body));
      expect(body.document_ids).toEqual([11]);
      expect(body.force).toBe(true); // «актуализировать» = перепроверить безусловно
    });
  });

  it("opens the document in a side panel on title click", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
          <Route path="/documents/:documentId" element={<div>Полная страница</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));

    // панель открылась, документ в ней загружен (отчёт и заметки на месте)
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Содержимое/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Проверить" })).toBeInTheDocument();
  });

  it("closes the side panel with Escape", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));
    await screen.findByRole("dialog");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("closes the side panel by clicking the backdrop", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    const { container } = render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));
    await screen.findByRole("dialog");

    fireEvent.click(container.querySelector(".drawer-backdrop")!);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("opens the full page from the side panel", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
          <Route path="/documents/:documentId" element={<div>Полная страница документа</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));
    const dialog = await screen.findByRole("dialog");
    // крошка с названием документа ведёт на полную страницу
    fireEvent.click(
      within(dialog).getByRole("link", { name: "[СТ] GDS-15 Загрузка кино" }),
    );

    expect(await screen.findByText("Полная страница документа")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("resizes the side panel with arrow keys and remembers the width", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.style.width).toBe("640px");

    const handle = within(dialog).getByRole("separator");
    fireEvent.keyDown(handle, { key: "ArrowLeft" }); // влево — шире
    expect(dialog.style.width).toBe("672px");
    fireEvent.keyDown(handle, { key: "ArrowRight" }); // вправо — уже
    expect(dialog.style.width).toBe("640px");

    // выбранная ширина переживает перезагрузку
    expect(localStorage.getItem("cr-drawer-w")).toBe("640");
  });

  it("resizes the side panel by dragging the left handle", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText("[СТ] GDS-15 Загрузка кино"));
    const dialog = await screen.findByRole("dialog");
    const handle = within(dialog).getByRole("separator");

    // jsdom без PointerEvent: fireEvent теряет clientX, собираем события сами.
    // Viewport 1024px; ручку тянут к clientX=224 → ширина 800.
    const pointer = (type: string, x: number) => {
      const Ctor = window.PointerEvent ?? window.MouseEvent;
      return new Ctor(type, {
        bubbles: true,
        cancelable: true,
        pointerId: 1,
        clientX: x,
      } as PointerEventInit);
    };
    fireEvent(handle, pointer("pointerdown", 384));
    fireEvent(handle, pointer("pointermove", 224));
    fireEvent(handle, pointer("pointerup", 224));

    expect(dialog.style.width).toBe("800px");
  });

  it("restores the open panel from the URL", async () => {
    // адрес с ?doc=11 (после F5) сразу открывает панель — состояние в адресе
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/documents/11": DOC_DETAIL,
      "/api/documents/11/report": DOC_REPORT,
      "/api/documents/11/note": DOC_NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5?doc=11"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Шаблон требований/)).toBeInTheDocument();
  });

  it("starts validation for the selected documents", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/sync/bulk-validation": BULK_IDLE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // без выбора кнопка неактивна
    const run = await screen.findByRole("button", { name: /Проверить выбранные/ });
    expect(run).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Выбрать документ: [СТ] GDS-15 Загрузка кино"));
    fireEvent.click(screen.getByLabelText("Выбрать документ: [СТ] Вторая доработка"));
    expect(screen.getByText("Выбрано: 2")).toBeInTheDocument();
    expect(run).toHaveTextContent("Проверить выбранные (2)");

    fireEvent.click(run);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: /Запустить проверку — 2 док\./ }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/validate-batch" && init?.method === "POST",
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String(call?.[1]?.body));
      expect(body.document_ids).toEqual([11, 12]);
      expect(body.force).toBe(false);
      expect(body.ai_prompt).toBeNull(); // промт не меняли — идём со стандартным
    });
  });

  it("selects all loaded documents from the header checkbox and clears selection", async () => {
    mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByLabelText("Выбрать все загруженные документы"));
    expect(screen.getByText("Выбрано: 2")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Проверить выбранные \(2\)/ }),
    ).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Снять выделение" }));
    expect(screen.queryByText("Выбрано: 2")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Проверить выбранные/ })).toBeDisabled();
  });

  it("prefills the standard prompt and sends the edited one", async () => {
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents": DOCUMENTS,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/sync/bulk-validation": BULK_IDLE,
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Проверить" }));

    const dialog = await screen.findByRole("dialog");
    const textarea = within(dialog).getByLabelText(
      "Промт ИИ-проверки",
    ) as HTMLTextAreaElement;
    // всегда предзаполнен стандартным промтом
    expect(textarea.value).toBe(VALIDATION_CONFIG.default_prompt);

    // правка подсвечивается и откатывается одной кнопкой
    fireEvent.change(textarea, { target: { value: "мой особый промт" } });
    expect(within(dialog).getByText(/промт изменён/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Вернуть стандартный промт/ }));
    expect(textarea.value).toBe(VALIDATION_CONFIG.default_prompt);

    // изменённый промт уходит в запуск, стандартный — нет
    fireEvent.change(textarea, { target: { value: "особый промт партии" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: /Запустить проверку — 1 док\./ }),
    );
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/validate-batch" && init?.method === "POST",
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String(call?.[1]?.body));
      expect(body.ai_prompt).toBe("особый промт партии");
      expect(body.document_ids).toEqual([12]); // кнопка «Проверить» — из строки doc 12
    });
  });

  it("appends the next page when the sentinel becomes visible", async () => {
    // Мок IntersectionObserver: колбэк можно дёрнуть вручную из теста.
    class MockIntersectionObserver {
      static instances: MockIntersectionObserver[] = [];
      callback: (entries: { isIntersecting: boolean }[]) => void;

      constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
        this.callback = callback;
        MockIntersectionObserver.instances.push(this);
      }

      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

    const doc = (id: number, title: string) => ({
      id,
      confluence_page_id: String(1000 + id),
      title,
      url: `https://confluence.mts.ru/x/${id}`,
      created_in_confluence_at: "2026-07-01T00:00:00",
      last_modified_in_confluence_at: "2026-08-10T00:00:00",
      validation_status: "not_checked",
      last_validated_at: null,
      has_note: false,
    });
    const fetchMock = mockFetch({
      "/api/analysts/5": ANALYST,
      "/api/analysts/5/documents?page=1&page_size=20": {
        items: [doc(1, "Первая страница — 1")],
        total: 25,
        page: 1,
        page_size: 20,
      },
      "/api/analysts/5/documents?page=2&page_size=20": {
        items: [doc(21, "Вторая страница — 21")],
        total: 25,
        page: 2,
        page_size: 20,
      },
    });

    render(
      <MemoryRouter initialEntries={["/analysts/5"]}>
        <Routes>
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Первая страница — 1")).toBeInTheDocument();
    expect(screen.getByText("Показано 1 из 25")).toBeInTheDocument();

    // скролл дошёл до сентинела — подгружается вторая страница
    MockIntersectionObserver.instances[0].callback([{ isIntersecting: true }]);

    expect(await screen.findByText("Вторая страница — 21")).toBeInTheDocument();
    expect(screen.getByText("Показано 2 из 25")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("page=2"))).toBe(
      true,
    );
  });
});
