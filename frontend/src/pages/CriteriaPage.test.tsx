import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CriteriaPage from "./CriteriaPage";

/** Мок fetch с ключами "METHOD /path" — мутации отличаем от чтения. */
function mockFetch(responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).split("?")[0];
    const key = `${init?.method ?? "GET"} ${path}`;
    for (const [route, payload] of Object.entries(responses)) {
      if (key === route) {
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

const ITEMS = [
  {
    id: 1,
    code: "polnota_opisaniya",
    name: "Полнота описания",
    prompt: "описаны ли все сценарии использования доработки",
    is_archived: false,
    created_at: "2026-08-01T10:00:00",
    updated_at: "2026-08-01T10:00:00",
  },
  {
    id: 2,
    code: "audit_razdelov",
    name: "Аудит разделов",
    prompt: "промт архивного критерия, достаточно длинный",
    is_archived: true,
    created_at: "2026-08-02T10:00:00",
    updated_at: "2026-08-02T10:00:00",
  },
];

function sentJson(
  fetchMock: ReturnType<typeof mockFetch>,
  method: string,
  path: string,
): unknown {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url) === path && init?.method === method,
  );
  expect(call).toBeDefined();
  return JSON.parse(String(call?.[1]?.body ?? "null"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CriteriaPage: справочник ИИ-критериев", () => {
  it("показывает активные и архивные критерии с кодами", async () => {
    mockFetch({ "GET /api/ai-criteria": ITEMS });
    render(<MemoryRouter><CriteriaPage /></MemoryRouter>);

    expect(await screen.findByText("Полнота описания")).toBeInTheDocument();
    expect(screen.getByText("polnota_opisaniya")).toBeInTheDocument();
    expect(screen.getByText(/Активных критериев нет|активных/)).toBeInTheDocument();
    // архивный — отдельной секцией
    expect(screen.getByText("Архив (1)")).toBeInTheDocument();
    expect(screen.getByText("Аудит разделов")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Восстановить/ })).toBeInTheDocument();
  });

  it("добавляет критерий: POST с названием и промтом", async () => {
    const fetchMock = mockFetch({
      "GET /api/ai-criteria": ITEMS,
      "POST /api/ai-criteria": ITEMS[0],
    });
    render(<MemoryRouter><CriteriaPage /></MemoryRouter>);
    await screen.findByText("Полнота описания");
    fireEvent.click(screen.getByRole("button", { name: /Новый критерий/ }));
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByRole("textbox", { name: "Название" }), {
      target: { value: "Трассировка требований" },
    });
    fireEvent.change(await screen.findByRole("textbox", { name: "Промт-инструкция" }), {
      target: { value: "каждое требование связано с целью доработки" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Добавить критерий/ }));

    await waitFor(() => {
      expect(sentJson(fetchMock, "POST", "/api/ai-criteria")).toEqual({
        name: "Трассировка требований",
        prompt: "каждое требование связано с целью доработки",
      });
    });
    expect(
      await screen.findByText(/Критерий добавлен — попадёт в следующие запуски/),
    ).toBeInTheDocument();
  });

  it("правка критерия: предупреждение о переименовании, PUT с полями", async () => {
    const fetchMock = mockFetch({
      "GET /api/ai-criteria": ITEMS,
      "PUT /api/ai-criteria/1": ITEMS[0],
    });
    render(<MemoryRouter><CriteriaPage /></MemoryRouter>);
    await screen.findByText("Полнота описания");
    fireEvent.click(screen.getByRole("button", { name: /Править/ }));
    await screen.findByRole("dialog");

    // предупреждение видно до сохранения: прошлые оценки увидят новое название
    expect(screen.getByText(/Переименование увидят и прошлые оценки/)).toBeInTheDocument();

    const name = within(screen.getByRole("dialog")).getByRole("textbox", { name: "Название" });
    fireEvent.change(name, { target: { value: "Полнота сценариев" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(sentJson(fetchMock, "PUT", "/api/ai-criteria/1")).toEqual({
        name: "Полнота сценариев",
        prompt: ITEMS[0].prompt,
      });
    });
    expect(
      await screen.findByText(/Правка промта меняет собранный промт следующих запусков/),
    ).toBeInTheDocument();
  });

  it("архивирует и восстанавливает критерии", async () => {
    const fetchMock = mockFetch({
      "GET /api/ai-criteria": ITEMS,
      "DELETE /api/ai-criteria/1": ITEMS[0],
      "POST /api/ai-criteria/2/restore": ITEMS[1],
    });
    render(<MemoryRouter><CriteriaPage /></MemoryRouter>);
    await screen.findByText("Полнота описания");

    fireEvent.click(screen.getByRole("button", { name: /В архив/ }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url) === "/api/ai-criteria/1" && init?.method === "DELETE",
        ),
      ).toBe(true),
    );
    expect(screen.getByText(/«Полнота описания» в архиве/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Восстановить/ }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url) === "/api/ai-criteria/2/restore" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(screen.getByText(/«Аудит разделов» снова активен/)).toBeInTheDocument();
  });
});
