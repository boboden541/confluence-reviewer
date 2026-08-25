import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ValidationDialog from "./ValidationDialog";

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

const CONFIG = {
  templates: [
    { id: 1, name: "Шаблон СТ", description: null, is_default: true, section_count: 9 },
  ],
  default_prompt: "стандартный промт ревьюера",
};

function renderDialog() {
  return render(
    <ValidationDialog documentIds={[11]} onClose={vi.fn()} onLaunched={vi.fn()} />,
  );
}

/** Тело последнего POST /api/documents/validate-batch. */
function sentBody(fetchMock: ReturnType<typeof mockFetch>) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === "/api/documents/validate-batch" && init?.method === "POST",
  );
  expect(call).toBeDefined();
  return JSON.parse(String(call?.[1]?.body));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ValidationDialog: выбор критериев проверки", () => {
  it("оба критерия включены по умолчанию и уходят в payload", async () => {
    const fetchMock = mockFetch({
      "/api/validation-config": CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });
    renderDialog();

    // галочки: «Соответствие шаблону» и «Наполнение (ИИ)»
    const tpl = await screen.findByRole("checkbox", { name: /Соответствие шаблону/ });
    const ai = screen.getByRole("checkbox", { name: /Наполнение/ });
    expect((tpl as HTMLInputElement).checked).toBe(true);
    expect((ai as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));

    await waitFor(() => {
      expect(sentBody(fetchMock)).toEqual({
        document_ids: [11],
        force: false,
        checks: ["template", "ai"],
        template_id: 1,
        ai_prompt: null, // стандартный промт не отправляем
      });
    });
    // зоны настроек не погашены (диалог в portal — ищем по всему документу)
    expect(document.querySelector(".zone-off")).toBeNull();
  });

  it("обе галочки сняты — запуск заблокирован, видна подсказка", async () => {
    mockFetch({ "/api/validation-config": CONFIG });
    renderDialog();

    fireEvent.click(await screen.findByRole("checkbox", { name: /Соответствие шаблону/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Наполнение/ }));

    expect(
      await screen.findByText("Выберите хотя бы один критерий проверки"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }),
    ).toBeDisabled();
  });

  it("снятие ИИ гасит зону промта и не отправляет его настройки", async () => {
    const fetchMock = mockFetch({
      "/api/validation-config": CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });
    renderDialog();

    fireEvent.click(await screen.findByRole("checkbox", { name: /Наполнение/ }));

    const prompt = screen.getByRole("textbox", { name: "Промт ИИ-проверки" });
    expect(prompt.closest(".zone-off")).not.toBeNull(); // зона погашена
    // ввод в погашенной зоне недоступен, промт остаётся стандартным
    expect((prompt as HTMLTextAreaElement).value).toBe(CONFIG.default_prompt);

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));

    await waitFor(() => {
      expect(sentBody(fetchMock)).toEqual({
        document_ids: [11],
        force: false,
        checks: ["template"],
        template_id: 1,
        ai_prompt: null,
      });
    });
  });

  it("снятие шаблона гасит зону выбора версии и не отправляет template_id", async () => {
    const fetchMock = mockFetch({
      "/api/validation-config": CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });
    renderDialog();

    fireEvent.click(await screen.findByRole("checkbox", { name: /Соответствие шаблону/ }));

    // зона «Шаблон требований» (внутри погашенного контейнера) недоступна
    const zoneLabel = document.querySelector(".zone-off .zone-label");
    expect(zoneLabel?.textContent).toBe("Шаблон требований");

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));

    await waitFor(() => {
      expect(sentBody(fetchMock)).toEqual({
        document_ids: [11],
        force: false,
        checks: ["ai"],
        template_id: null,
        ai_prompt: null,
      });
    });
  });

  it("шаблона нет в системе: с критерием шаблона запуск заблокирован, без него — доступен", async () => {
    mockFetch({ "/api/validation-config": { ...CONFIG, templates: [] } });
    renderDialog();

    const run = await screen.findByRole("button", { name: /Запустить проверку — 1 док\./ });
    expect(run).toBeDisabled(); // шаблон выбран, но не настроен
    expect(screen.getByText("Шаблон требований не настроен — проверка невозможна"));

    fireEvent.click(screen.getByRole("checkbox", { name: /Соответствие шаблону/ }));
    expect(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ })).toBeEnabled();
  });
});
