import { afterEach, describe, expect, it, vi } from "vitest";
import {
  emitServerEvent,
  on,
  startEvents,
  stopEvents,
  type BulkEvent,
  type ValidationEvent,
} from "./events";
import { AUTH_STORAGE_KEY, UNAUTHORIZED_EVENT } from "./api";

/** ReadableStream из строк — имитация тела SSE-ответа backend. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunks[i++]));
    },
  });
}

function mockStreamFetch(chunks: string[], status = 200) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(streamOf(chunks), {
      status,
      headers: { "Content-Type": "text/event-stream" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  stopEvents();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("events: шина подписок", () => {
  it("доставляет событие подписчикам, отписка прекращает доставку", () => {
    const got: ValidationEvent[] = [];
    const off = on("validation", (e) => got.push(e));

    emitServerEvent("validation", { type: "validation", document_id: 1, status: "running" });
    expect(got).toHaveLength(1);

    off();
    emitServerEvent("validation", { type: "validation", document_id: 1, status: "done" });
    expect(got).toHaveLength(1);
  });

  it("разные типы не пересекаются", () => {
    const bulk: BulkEvent[] = [];
    on("bulk", (e) => bulk.push(e));

    emitServerEvent("sync", {
      type: "sync", running: false, started_at: null, finished_at: null,
      error: null, last_results: [],
    });
    expect(bulk).toHaveLength(0);

    emitServerEvent("bulk", {
      type: "bulk", running: true, analyst_id: null, total: 3, done: 1,
      started_at: null, finished_at: null, error: null,
    });
    expect(bulk).toHaveLength(1);
    expect(bulk[0].done).toBe(1);
  });
});

describe("events: SSE-стрим через fetch", () => {
  it("парсит кадры, дроблёные по чанкам, и шлёт connected", async () => {
    mockStreamFetch([
      'event: sync\nda', // кадр разрезан посередине
      'ta: {"type":"sync","running":true}\n\n',
      ': keepalive\n\n', // комментарий — не событие
      'event: validation\ndata: {"type":"validation","document_id":9,"status":"done","report_id":5}\n\n',
    ]);

    const connected: unknown[] = [];
    on("connected", (e) => connected.push(e));
    const validations: ValidationEvent[] = [];
    on("validation", (e) => validations.push(e));
    const syncs: unknown[] = [];
    on("sync", (e) => syncs.push(e));

    startEvents();
    await vi.waitFor(() => {
      expect(validations).toHaveLength(1);
    });

    expect(validations[0]).toEqual({
      type: "validation", document_id: 9, status: "done", report_id: 5,
    });
    expect(syncs).toHaveLength(1);
    expect(connected).toHaveLength(1);
  });

  it("учётка уходит в заголовке Authorization", async () => {
    localStorage.setItem(AUTH_STORAGE_KEY, "dXNlcjpwYXNz");
    const fetchMock = mockStreamFetch([""]);

    startEvents();
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Basic dXNlcjpwYXNz");
    expect(headers.Accept).toBe("text/event-stream");
  });

  it("401 стрима поднимает событие unauthorized и переподключается", async () => {
    const fetchMock = vi.fn(async () => new Response("Требуется авторизация", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const unauthorized = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, unauthorized);

    startEvents();
    await vi.waitFor(() => {
      expect(unauthorized).toHaveBeenCalled();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // переподключение по расписанию (пауза 1 c)
    await new Promise((r) => setTimeout(r, 1100));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    window.removeEventListener(UNAUTHORIZED_EVENT, unauthorized);
  });

  it("stopEvents останавливает переподключения", async () => {
    const fetchMock = mockStreamFetch([""]); // стрим сразу закрывается
    startEvents();
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    stopEvents();
    await new Promise((r) => setTimeout(r, 1100));
    expect(fetchMock).toHaveBeenCalledTimes(1); // повторов нет
  });
});
