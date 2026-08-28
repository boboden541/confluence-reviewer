import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ReportPage from "./ReportPage";
import { AUTH_STORAGE_KEY } from "../api";
import { emitServerEvent } from "../events";

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

const DOCUMENT = {
  id: 42,
  confluence_page_id: "2380439645",
  title: "[СТ] GDS-15 Загрузка кино",
  url: "https://confluence.mts.ru/x/1",
  created_in_confluence_at: "2026-07-01T00:00:00",
  last_modified_in_confluence_at: "2026-08-10T00:00:00",
  validation_status: "failed",
  last_validated_at: "2026-08-11T00:00:00",
  has_note: false,
  content_html: "<h1>Введение</h1>",
  sync_error: null,
  analyst_id: 5,
  analyst_name: "Иван Тестов",
  analyst_email: "t@mts.ru",
};

const REPORT = {
  id: 9,
  document_id: 42,
  triggered_by: "manual",
  created_at: "2026-08-11T12:00:00",
  template_passed: false,
  template_findings: "### ❌ Критичные замечания (1)\n- ❌ Отсутствует раздел «Требования к интерфейсам»",
  ai_passed: true,
  ai_findings: "✅ Замечаний к содержимому нет.",
  overall_passed: false,
  error_message: null,
  comment_sent_at: null,
  ai_model_used: "glm-4.5",
};

const NOTE = { document_id: 42, content: "", created_at: null, updated_at: null };

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
  criteria: [
    { id: 1, code: "polnota_opisaniya", name: "Полнота описания", prompt: "описаны ли все сценарии" },
    { id: 2, code: "odnoznachnost_formulirovok", name: "Однозначность формулировок", prompt: "сможет ли разработчик реализовать" },
  ],
  prompt_head: "КАРКАС ПРОМТА\n\n",
  prompt_tail: "\nХВОСТ ПРОМТА",
};

/** Промт, который диалог собирает из обоих критериев фикстуры. */
const ASSEMBLED_PROMPT = "КАРКАС ПРОМТА\n\n" +
      "1. «Полнота описания» — описаны ли все сценарии\n" +
      "2. «Однозначность формулировок» — сможет ли разработчик реализовать" +
      "\nХВОСТ ПРОМТА";

function renderPage(initialEntries: string[] = ["/documents/42"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/documents/:documentId" element={<ReportPage />} />
        <Route path="/" element={<div>Список аналитиков</div>} />
        <Route path="/analysts/:analystId" element={<div>Список документов</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportPage", () => {
  beforeEach(() => {
    localStorage.setItem(AUTH_STORAGE_KEY, btoa("u:p"));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("renders both checks and findings", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
    });

    renderPage();

    // название видно и в крошках, и в заголовке страницы
    expect(await screen.findAllByText("[СТ] GDS-15 Загрузка кино")).toHaveLength(2);
    // зоны «Проверки» и «Заметки» ориентируют в длинном содержимом
    expect(screen.getByText("Проверки")).toBeInTheDocument();
    expect(screen.getByText("Заметки руководителя")).toBeInTheDocument();
    expect(screen.getByText(/Шаблон требований/)).toBeInTheDocument();
    expect(screen.getByText(/Содержимое \(ИИ\)/)).toBeInTheDocument();
    expect(screen.getByText(/Отсутствует раздел/)).toBeInTheDocument();
    // «не пройдено»: бейдж документа + карточка шаблона
    expect(screen.getAllByText("не пройдено")).toHaveLength(2);
    // чем проверяли: модель ИИ видна в мете карточки «Содержимое (ИИ)»
    const meta = document.querySelector(".report-meta")?.textContent ?? "";
    expect(meta).toContain("модель: glm-4.5");
  });

  it("renders findings as formatted markdown", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": {
        ...REPORT,
        template_findings:
          "### ❌ Критичные замечания (1)\n\n- ❌ В разделе **Общее описание** нет контекста",
      },
      "/api/documents/42/note": NOTE,
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { level: 3, name: /Критичные замечания/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("listitem").textContent).toBe(
      "❌ В разделе Общее описание нет контекста",
    );
    expect(screen.getByText("Общее описание").tagName).toBe("STRONG");
    // разметка отрендерена, а не показана исходником
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
    expect(screen.queryByText(/###/)).not.toBeInTheDocument();
  });

  it("shows prompt to run first validation when no report", async () => {
    mockFetch({
      "/api/documents/42": { ...DOCUMENT, validation_status: "not_checked" },
      "/api/documents/42/note": NOTE,
    }); // report -> 404 (нет в моке)

    renderPage();

    expect(
      await screen.findByText(/Нажмите «Проверить»/),
    ).toBeInTheDocument();
  });

  it("shows technical error block for error report", async () => {
    mockFetch({
      "/api/documents/42": { ...DOCUMENT, validation_status: "error" },
      "/api/documents/42/report": { ...REPORT, error_message: "Нет связи с ИИ" },
      "/api/documents/42/note": NOTE,
    });

    renderPage();

    expect(await screen.findByText("Нет связи с ИИ")).toBeInTheDocument();
  });

  it("disables Confluence button after comment is sent", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": { ...REPORT, comment_sent_at: "2026-08-12T10:00:00" },
      "/api/documents/42/note": NOTE,
    });

    renderPage();

    const button = await screen.findByRole("button", {
      name: /Отправлено/,
    });
    expect(button).toBeDisabled();
  });

  it("renders note preview below the editor", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": {
        ...NOTE,
        content: "## Ревью\n- уточнить **критерии приёмки**",
      },
    });

    renderPage();

    // предпросмотр отрендерен как markdown, исходник остался в редакторе
    expect(
      await screen.findByRole("heading", { level: 2, name: "Ревью" }),
    ).toBeInTheDocument();
    expect(screen.getByText("критерии приёмки").tagName).toBe("STRONG");
    // исходник остаётся в редакторе
    const editor = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(editor.value).toBe("## Ревью\n- уточнить **критерии приёмки**");
  });

  it("deletes the note and clears the editor", async () => {
    const fetchMock = mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": { ...NOTE, content: "старая заметка" },
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Удалить заметку" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/42/note" && init?.method === "DELETE",
      );
      expect(call).toBeDefined();
    });
    expect(await screen.findByText("Заметка удалена")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("старая заметка")).not.toBeInTheDocument();
  });

  it("shows the document author with email", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
    });

    renderPage();

    // имя видно и в хлебных крошках, и в блоке автора под заголовком
    expect(await screen.findAllByText("Иван Тестов")).toHaveLength(2);
    expect(screen.getByText("t@mts.ru")).toBeInTheDocument();
  });

  it("breadcrumb leads to the analysts list", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
    });

    renderPage(["/documents/42"]);

    fireEvent.click(await screen.findByRole("link", { name: "Аналитики" }));
    expect(await screen.findByText("Список аналитиков")).toBeInTheDocument();
  });

  it("breadcrumb leads to the analyst's document list", async () => {
    mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
    });

    renderPage(["/documents/42"]);

    // имя автора — ссылка на его документы (крошка и блок автора)
    const links = await screen.findAllByRole("link", { name: "Иван Тестов" });
    fireEvent.click(links[0]);
    expect(await screen.findByText("Список документов")).toBeInTheDocument();
  });

  // Проверка и с детального просмотра идёт через диалог настроек —
  // как и в списке документов (шаблон + промт ИИ перед запуском)
  it("runs validation from the detail page through the settings dialog", async () => {
    const fetchMock = mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /Проверить заново/ }));

    // диалог предзаполнен собранным промтом и шаблоном по умолчанию
    const prompt = await screen.findByRole("textbox", {
      name: "Промт ИИ-проверки",
    }) as HTMLTextAreaElement;
    expect(prompt.value).toBe(ASSEMBLED_PROMPT);
    // зоны диалога (одноимённая карточка есть и в самом отчёте — ищем внутри диалога)
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Шаблон требований")).toBeInTheDocument();
    expect(within(dialog).getByText("ИИ-критерии и промт")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/validate-batch" && init?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({
        document_ids: [42],
        force: true, // «Проверить заново» — перевалидировать безусловно
        checks: ["template", "ai"], // оба критерия включены по умолчанию
        template_id: 1,
        ai_prompt: null, // собранный промт не отправляем
        criterion_ids: [1, 2], // оба ИИ-критерия фикстуры отмечены
      });
    });
    // диалог закрылся, страница ждёт завершения проверки
    expect(await screen.findByText("Проверка запущена…")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("plain Проверить from the detail page launches without force", async () => {
    const fetchMock = mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });

    renderPage();

    // главная кнопка «Проверить» (не «Проверить заново»)
    fireEvent.click(await screen.findByRole("button", { name: /^Проверить$/ }));

    fireEvent.click(
      await screen.findByRole("button", { name: /Запустить проверку — 1 док\./ }),
    );

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/documents/validate-batch" && init?.method === "POST",
      );
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        document_ids: [42],
        force: false,
      });
    });
  });

  it("событие завершения проверки обновляет отчёт без перезагрузки", async () => {
    const fetchMock = mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
      "/api/validation-config": VALIDATION_CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });

    render(
      <MemoryRouter initialEntries={["/documents/42"]}>
        <Routes>
          <Route path="/documents/:documentId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // запускаем проверку через диалог — отчёт уходит в фон
    fireEvent.click(await screen.findByRole("button", { name: /^Проверить$/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Запустить проверку — 1 док\./ }),
    );
    expect(await screen.findByText("Проверка запущена…")).toBeInTheDocument();

    const reportLoads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url) === "/api/documents/42/report")
        .length;
    const before = reportLoads();

    // backend закончил — страница сама перечитала документ и отчёт
    emitServerEvent("validation", {
      type: "validation", document_id: 42, status: "done", report_id: 9,
    });
    await waitFor(() => {
      expect(reportLoads()).toBeGreaterThan(before);
    });
    expect(screen.queryByText("Проверка запущена…")).not.toBeInTheDocument();
  });

  it("чужие документы не дёргают перезагрузку отчёта", async () => {
    const fetchMock = mockFetch({
      "/api/documents/42": DOCUMENT,
      "/api/documents/42/report": REPORT,
      "/api/documents/42/note": NOTE,
    });

    render(
      <MemoryRouter initialEntries={["/documents/42"]}>
        <Routes>
          <Route path="/documents/:documentId" element={<ReportPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Шаблон требований")).toBeInTheDocument();
    const reportLoads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url) === "/api/documents/42/report")
        .length;
    const before = reportLoads();

    emitServerEvent("validation", {
      type: "validation", document_id: 999, status: "done", report_id: 1,
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(reportLoads()).toBe(before);
  });
});
