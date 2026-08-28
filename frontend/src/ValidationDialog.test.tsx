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

const CRITERIA = [
  { id: 1, code: "polnota_opisaniya", name: "Полнота описания", prompt: "описаны ли все сценарии" },
  { id: 2, code: "neprotivorechivost_trebovanii", name: "Непротиворечивость требований", prompt: "нет ли противоречий" },
  { id: 3, code: "odnoznachnost_formulirovok", name: "Однозначность формулировок", prompt: "сможет ли разработчик реализовать" },
];

const CONFIG = {
  templates: [
    { id: 1, name: "Шаблон СТ", description: null, is_default: true, section_count: 9 },
  ],
  default_prompt: "стандартный промт ревьюера",
  criteria: CRITERIA,
  prompt_head: "ГОЛОВА ПРОМТА\n\n",
  prompt_tail: "\nХВОСТ ПРОМТА",
};

/** Промт, который должен собрать диалог из всех трёх критериев. */
const ASSEMBLED =
  "ГОЛОВА ПРОМТА\n\n" +
  "1. «Полнота описания» — описаны ли все сценарии\n" +
  "2. «Непротиворечивость требований» — нет ли противоречий\n" +
  "3. «Однозначность формулировок» — сможет ли разработчик реализовать" +
  "\nХВОСТ ПРОМТА";

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

function promptArea(): HTMLTextAreaElement {
  return screen.getByRole("textbox", { name: "Промт ИИ-проверки" }) as HTMLTextAreaElement;
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
        ai_prompt: null, // промт собирает бэкенд из критериев
        criterion_ids: [1, 2, 3],
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

  it("снятие ИИ гасит зону критериев и промта и не отправляет их настройки", async () => {
    const fetchMock = mockFetch({
      "/api/validation-config": CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });
    renderDialog();

    fireEvent.click(await screen.findByRole("checkbox", { name: /Наполнение/ }));

    const prompt = promptArea();
    expect(prompt.closest(".zone-off")).not.toBeNull(); // зона погашена
    expect(prompt.value).toBe(ASSEMBLED); // под замком — собранное превью

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));

    await waitFor(() => {
      expect(sentBody(fetchMock)).toEqual({
        document_ids: [11],
        force: false,
        checks: ["template"],
        template_id: 1,
        ai_prompt: null,
        criterion_ids: null,
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
        criterion_ids: [1, 2, 3],
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

describe("ValidationDialog: ИИ-критерии и замок промта", () => {
  it("промт под замком собирается из отмеченных критериев и пересобирается живьём", async () => {
    mockFetch({ "/api/validation-config": CONFIG });
    renderDialog();

    const area = await waitFor(() => {
      const el = promptArea();
      expect(el.value).toBe(ASSEMBLED);
      return el;
    });
    expect(area.readOnly).toBe(true); // под замком — только чтение

    // сняли средний критерий: блок исчез, нумерация пересобралась
    fireEvent.click(screen.getByRole("checkbox", { name: /Непротиворечивость/ }));
    expect(area.value).toBe(
      "ГОЛОВА ПРОМТА\n\n" +
        "1. «Полнота описания» — описаны ли все сценарии\n" +
        "2. «Однозначность формулировок» — сможет ли разработчик реализовать" +
        "\nХВОСТ ПРОМТА",
    );
  });

  it("все ИИ-критерии сняты — запуск заблокирован с подсказкой", async () => {
    mockFetch({ "/api/validation-config": CONFIG });
    renderDialog();

    await screen.findByRole("checkbox", { name: /Полнота описания/ });
    for (const name of [/Полнота описания/, /Непротиворечивость/, /Однозначность/]) {
      fireEvent.click(screen.getByRole("checkbox", { name }));
    }

    expect(
      screen.getByText(
        "Отметьте хотя бы один ИИ-критерий — иначе проверке не по чему оценивать документ",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }),
    ).toBeDisabled();
  });

  it("активных критериев нет — подсказка, запуск только без наполнения", async () => {
    mockFetch({ "/api/validation-config": { ...CONFIG, criteria: [] } });
    renderDialog();

    expect(
      await screen.findByText(/Нет активных ИИ-критериев — добавьте их в разделе/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /Наполнение/ }));
    expect(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ })).toBeEnabled();
  });

  it("снятие замка замораживает промт: галочки его больше не меняют, уходит override", async () => {
    const fetchMock = mockFetch({
      "/api/validation-config": CONFIG,
      "/api/documents/validate-batch": { status: "started", total: 1 },
    });
    renderDialog();
    await waitFor(() => expect(promptArea().value).toBe(ASSEMBLED));

    // сняли замок: текст остаётся, но становится редактируемым
    fireEvent.click(screen.getByRole("button", { name: /Изменить промт/ }));
    const area = promptArea();
    expect(area.readOnly).toBe(false);
    expect(area.value).toBe(ASSEMBLED);

    // ручная правка + галочка критерия замороженный текст не пересобирает
    fireEvent.change(area, { target: { value: "мой особый промт прогона" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Однозначность/ }));
    expect(area.value).toBe("мой особый промт прогона");

    fireEvent.click(screen.getByRole("button", { name: /Запустить проверку — 1 док\./ }));
    await waitFor(() => {
      expect(sentBody(fetchMock)).toEqual({
        document_ids: [11],
        force: false,
        checks: ["template", "ai"],
        template_id: 1,
        ai_prompt: "мой особый промт прогона", // override только при снятом замке
        criterion_ids: [1, 2], // критерии запуска — по галочкам
      });
    });
  });

  it("«Вернуть собранный промт» возвращает замок и живую пересборку", async () => {
    mockFetch({ "/api/validation-config": CONFIG });
    renderDialog();
    await waitFor(() => expect(promptArea().value).toBe(ASSEMBLED));

    fireEvent.click(screen.getByRole("button", { name: /Изменить промт/ }));
    fireEvent.change(promptArea(), { target: { value: "чужой текст" } });

    fireEvent.click(screen.getByRole("button", { name: /Вернуть собранный промт/ }));
    const area = promptArea();
    expect(area.readOnly).toBe(true);
    expect(area.value).toBe(ASSEMBLED); // снова живое превью

    // и снова реагирует на галочки
    fireEvent.click(screen.getByRole("checkbox", { name: /Полнота описания/ }));
    expect(area.value).not.toContain("Полнота описания»");
  });
});
