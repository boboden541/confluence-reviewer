import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RemindersPanel from "./RemindersPanel";
import { RemindersContext } from "./remindersContext";
import type { Reminder } from "./api";

function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const method = init?.method ?? "GET";
    if (method === "GET" || responses[`${method} ${path}`] !== undefined) {
      const payload = responses[`${method} ${path}`] ?? responses[path];
      if (payload !== undefined) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    if (path === `/api/reminders/${path.split("/").pop()}` && method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify({ detail: "не найдено" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const NOW = "2026-09-10T12:00:00";

function reminder(over: Partial<Reminder>): Reminder {
  return {
    id: 1,
    analyst_id: 7,
    analyst_name: "Алиев Рустам",
    document_id: null,
    document_title: null,
    text: "задача",
    remind_at: null,
    done_at: null,
    created_at: "2026-09-01T00:00:00",
    status: "open",
    group: "later",
    ...over,
  };
}

const OPEN: Reminder[] = [
  reminder({
    id: 1,
    text: "просроченная задача",
    remind_at: "2026-09-08T10:00:00",
  }),
  reminder({
    id: 2,
    text: "задача на сегодня",
    document_id: 42,
    document_title: "Системные требования СМЭ",
    remind_at: `2026-09-10T09:00:00`,
  }),
];

function renderPanel(contextOpen = vi.fn()) {
  return render(
    <MemoryRouter>
      <RemindersContext.Provider value={{ open: contextOpen }}>
        <RemindersPanel showDoneToggle />
      </RemindersContext.Provider>
    </MemoryRouter>,
  );
}

describe("RemindersPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date(`${NOW}Z`) });
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
    vi.unstubAllGlobals();
  });

  it("groups open reminders into overdue / today / later", async () => {
    mockFetch({
      "/api/reminders": [
        ...OPEN,
        reminder({ id: 3, text: "на потом", remind_at: "2026-09-20T10:00:00" }),
        reminder({ id: 4, text: "без даты", remind_at: null }),
        reminder({
          id: 5,
          text: "выполненная",
          status: "done",
          done_at: "2026-09-09T10:00:00",
        }),
      ],
    });
    renderPanel();

    expect(await screen.findByText("просроченная задача")).toBeInTheDocument();
    expect(screen.getByText("задача на сегодня")).toBeInTheDocument();
    // группа «дальше» видна; выполненные скрыты за свёрнутым блоком
    expect(screen.getByText("на потом")).toBeInTheDocument();
    expect(screen.getByText("без даты")).toBeInTheDocument();
    expect(screen.queryByText("выполненная")).not.toBeInTheDocument();
    // счётчик открытых
    expect(screen.getByText("4 открыт · 1 выполнено")).toBeInTheDocument();
  });

  it("checks a reminder to mark it done (POST)", async () => {
    vi.useRealTimers();
    const fetchMock = mockFetch({
      "/api/reminders": OPEN,
      "POST /api/reminders/1/done": { ...OPEN[0], status: "done", done_at: NOW },
    });
    renderPanel();

    await screen.findByText("просроченная задача");
    const checks = screen.getAllByRole("checkbox", { name: "Выполнить" });
    fireEvent.click(checks[0]);

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url) === "/api/reminders/1/done" && init?.method === "POST",
      );
      expect(post).toBeDefined();
    });
  });

  it("reopens a done reminder and deletes it with confirm", async () => {
    const fetchMock = mockFetch({
      "/api/reminders": [
        ...OPEN,
        reminder({ id: 5, text: "выполненная", status: "done", done_at: NOW }),
      ],
      "POST /api/reminders/5/reopen": OPEN[0],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();

    // раскрыть выполненные
    fireEvent.click(await screen.findByText(/Выполненные \(1\)/));
    const doneRow = await screen.findByText("выполненная");
    expect(doneRow).toBeInTheDocument();

    // вернуть в открытые
    fireEvent.click(screen.getByRole("checkbox", { name: "Вернуть в открытые" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url) === "/api/reminders/5/reopen" && init?.method === "POST",
        ),
      ).toBe(true);
    });

    // удалить (кнопка появляется у выполненных)
    fireEvent.click(screen.getByRole("button", { name: "🗑" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url) === "/api/reminders/5" && init?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });

  it("the plus button opens the creation modal via context", async () => {
    const contextOpen = vi.fn();
    mockFetch({ "/api/reminders": [] });
    render(
      <MemoryRouter>
        <RemindersContext.Provider value={{ open: contextOpen }}>
          <RemindersPanel />
        </RemindersContext.Provider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "＋" }));
    expect(contextOpen).toHaveBeenCalledWith({ analyst_id: undefined });
    expect(await screen.findByText(/Напоминаний нет/)).toBeInTheDocument();
  });

  it("shows document link when a reminder is bound to a document", async () => {
    mockFetch({ "/api/reminders": OPEN });
    renderPanel();

    const link = await screen.findByRole("link", { name: "Системные требования СМЭ" });
    expect(link).toHaveAttribute("href", "/documents/42");
  });
});
