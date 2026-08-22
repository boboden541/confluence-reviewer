import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ReportPage from "./ReportPage";
import { AUTH_STORAGE_KEY } from "../api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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
  content_html: "<h1>Введение</h1>",
  sync_error: null,
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/documents/42"]}>
      <Routes>
        <Route path="/documents/:documentId" element={<ReportPage />} />
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

    expect(await screen.findByText("[СТ] GDS-15 Загрузка кино")).toBeInTheDocument();
    expect(
      screen.getByText(/Соответствие шаблону требований/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Качество содержимого \(ИИ\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Отсутствует раздел/)).toBeInTheDocument();
    expect(screen.getByText("не пройдено")).toBeInTheDocument();
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
});
