import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ReportPage from "./ReportPage";
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
};

const NOTE = { document_id: 42, content: "", created_at: null, updated_at: null };

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
});
