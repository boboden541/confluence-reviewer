import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReminderModal from "./ReminderModal";
import type { Analyst, DocumentListItem } from "./api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const payload = responses[`${init?.method ?? "GET"} ${path}`] ?? responses[path];
    if (payload !== undefined) {
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ANALYSTS: Analyst[] = [
  {
    id: 7,
    full_name: "Никулин Владислав",
    email: "nikulin@company.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 3,
    last_synced_at: null,
    sync_error: null,
    team_id: 13,
    team_name: "Конверсия",
    cluster_id: 3,
    cluster_name: "Билетный бизнес",
    domains: [],
    lead_user_id: null,
    lead_name: null,
  },
  {
    id: 8,
    full_name: "Белышева Жанна",
    email: "belysheva@company.ru",
    confluence_username: null,
    created_at: "2026-01-01T00:00:00",
    documents_count: 1,
    last_synced_at: null,
    sync_error: null,
    team_id: 14,
    team_name: "Финтех",
    cluster_id: 3,
    cluster_name: "Билетный бизнес",
    domains: [],
    lead_user_id: null,
    lead_name: null,
  },
];

const DOCS: { items: DocumentListItem[] } = {
  items: [
    {
      id: 42,
      confluence_page_id: "1",
      title: "Системные требования СМЭ",
      url: "https://conf.test/42",
      created_in_confluence_at: null,
      last_modified_in_confluence_at: null,
      validation_status: "failed",
      last_validated_at: null,
      has_note: false,
    },
  ],
};

function renderModal(
  onCreated = vi.fn(),
  extra: Record<string, unknown> = {},
) {
  const fetchMock = mockFetch({
    "/api/analysts": ANALYSTS,
    "/api/analysts/7/documents": DOCS,
    "POST /api/reminders": { id: 1 },
    ...extra,
  });
  render(<ReminderModal onCreated={onCreated} onClose={vi.fn()} />);
  return { fetchMock, onCreated };
}

describe("ReminderModal", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("fuzzy analyst search finds by typo and picks by click", async () => {
    renderModal();

    const input = screen.getByPlaceholderText("Поиск по ФИО — нечёткий");
    fireEvent.focus(input);
    // опечатка и неполное слово — fuse находит
    fireEvent.change(input, { target: { value: "ниул" } });
    const opt = await screen.findByRole("button", { name: /Никулин Владислав/ });
    fireEvent.mouseDown(opt);
    fireEvent.click(opt);

    // поле показывает выбранное; список закрылся
    expect(input).toHaveValue("Никулин Владислав");
    expect(screen.queryByRole("button", { name: /Белышева Жанна/ })).not.toBeInTheDocument();
  });

  it("loads documents after analyst is picked and fuzzy-filters them", async () => {
    renderModal();

    const input = screen.getByPlaceholderText("Поиск по ФИО — нечёткий");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "Никулин" } });
    fireEvent.click(await screen.findByRole("button", { name: /Никулин Владислав/ }));

    // документы аналитика подгружены; нечёткий запрос находит
    const docInput = await screen.findByPlaceholderText(/Поиск по документам аналитика/);
    fireEvent.focus(docInput);
    fireEvent.change(docInput, { target: { value: "смэ" } });
    const docOpt = await screen.findByRole("button", { name: /Системные требования СМЭ/ });
    fireEvent.click(docOpt);

    expect(docInput).toHaveValue("Системные требования СМЭ");
  });

  it("submits the reminder with analyst, document and date", async () => {
    const { fetchMock, onCreated } = renderModal();

    fireEvent.change(screen.getByPlaceholderText("Поиск по ФИО — нечёткий"), {
      target: { value: "Никулин" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Никулин Владислав/ }));
    const docInput = await screen.findByPlaceholderText(/Поиск по документам аналитика/);
    fireEvent.focus(docInput);
    fireEvent.click(screen.getByRole("button", { name: /Системные требования СМЭ/ }));
    fireEvent.change(screen.getByLabelText("Что напомнить *"), {
      target: { value: "Проверить правки" },
    });
    fireEvent.change(screen.getByLabelText("Вернуться (дата)"), {
      target: { value: "2026-09-14" },
    });
    const form = document.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === "/api/reminders" && init?.method === "POST",
      );
      expect(post).toBeDefined();
      const body = JSON.parse(String(post?.[1]?.body));
      expect(body.analyst_id).toBe(7);
      expect(body.document_id).toBe(42);
      expect(body.text).toBe("Проверить правки");
      expect(body.remind_at).toContain("2026-09-14");
    });
    expect(onCreated).toHaveBeenCalled();
  });

  it("rejects whitespace-only text on submit", async () => {
    const fetchMock = mockFetch({ "/api/analysts": ANALYSTS, "/api/analysts/7/documents": DOCS });
    renderModal();

    fireEvent.change(screen.getByPlaceholderText("Поиск по ФИО — нечёткий"), {
      target: { value: "Никулин" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Никулин Владислав/ }));
    fireEvent.change(screen.getByLabelText("Что напомнить *"), { target: { value: "   " } });
    fireEvent.submit(document.querySelector("form") as HTMLFormElement);

    expect(
      fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/reminders" && init?.method === "POST"),
    ).toBe(false);
  });

  it("document picker explains itself when no analyst is picked yet", async () => {
    renderModal();

    fireEvent.focus(screen.getByPlaceholderText("Сначала выберите аналитика"));
    expect(await screen.findByText(/Сначала выберите аналитика/)).toBeInTheDocument();
  });
});
