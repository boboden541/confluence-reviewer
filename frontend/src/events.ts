// Живые события backend (SSE /api/events): запуск и завершение фоновых
// задач (синхронизация, проверки документов) приходят на открытую страницу
// сами — перезагружать интерфейс не нужно.
//
// Подключение — fetch-стримом, а не EventSource: тому нельзя задать
// Authorization-заголовок, а basic-учётка SPA живёт в localStorage.

import { authHeaders, UNAUTHORIZED_EVENT, type BulkValidationStatus, type SyncStatus } from "./api";

/** Момент публикации; у снимков подключения (синхронный статус при открытии
 *  стрима) at нет — страницы отличают по нему настоящее событие от снимка. */
interface Published {
  at?: string;
}

/** Сменился статус проверки документа (running → done | error | not_found). */
export interface ValidationEvent extends Published {
  type: "validation";
  document_id: number;
  status: "running" | "done" | "error" | "not_found";
  report_id?: number;
  error?: string | null;
}

/** Состояние массовой проверки (прогресс и завершение прогона). */
export type BulkEvent = BulkValidationStatus & Published & { type: "bulk" };

/** Запуск/завершение синхронизации (включая плановую по расписанию). */
export type SyncEvent = SyncStatus & Published & { type: "sync" };

interface Events {
  validation: ValidationEvent;
  bulk: BulkEvent;
  sync: SyncEvent;
  /** Опубликован комментарий на страницу Confluence */
  comment: { type: "comment"; document_id: number; actor_id?: number; actor_name?: string; at?: string };

  /** Стрим (пере)подключился — хороший момент освежить данные на странице. */
  connected: { type: "connected" };
}

type Handler<K extends keyof Events> = (event: Events[K]) => void;
type AnyHandler = (event: Events[keyof Events]) => void;

const listeners = new Map<keyof Events, Set<AnyHandler>>();

/** Подписка на событие; возвращённая функция отписывает (cleanup в useEffect). */
export function on<K extends keyof Events>(type: K, handler: Handler<K>): () => void {
  let set = listeners.get(type);
  if (!set) {
    set = new Set();
    listeners.set(type, set);
  }
  const wrapped = handler as AnyHandler;
  set.add(wrapped);
  return () => {
    set?.delete(wrapped);
  };
}

/** Deliver событие подписчикам. Вызывается парсером стрима и тестами. */
export function emitServerEvent<K extends keyof Events>(type: K, event: Events[K]): void {
  listeners.get(type)?.forEach((handler) => handler(event));
}

// --- подключение к стриму ---

const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 15000;
// сервер шлёт keepalive каждые 20 c: дольше 45 c тишины — соединение мертво
const STALE_MS = 45_000;

let started = false;
let stopped = false;
let connecting = false;
let streamAlive = false;
let retryMs = RETRY_BASE_MS;
let lastMessageAt = 0;
let controller: AbortController | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

/** Подключиться к событиям (идемпотентно). Звать после входа в сервис. */
export function startEvents(): void {
  if (started) return;
  started = true;
  stopped = false;
  retryMs = RETRY_BASE_MS;
  void connect();
}

/** Отключиться (выход из сервиса): рвёт стрим и останавливает переподключения. */
export function stopEvents(): void {
  stopped = true;
  started = false;
  streamAlive = false;
  controller?.abort();
  controller = null;
  // запланированное переподключение тоже отменяем — иначе оно сработает
  // позже, когда стрим уже никому не нужен
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

async function connect(): Promise<void> {
  if (stopped || connecting || streamAlive) return;
  connecting = true;
  try {
    controller = new AbortController();
    const resp = await fetch("/api/events", {
      headers: { ...authHeaders(), Accept: "text/event-stream" },
      signal: controller.signal,
    });
    if (resp.status === 401) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
      throw new Error("SSE: требуется авторизация"); // в общий путь — с паузой
    }
    if (!resp.ok || !resp.body) throw new Error(`SSE: HTTP ${resp.status}`);

    retryMs = RETRY_BASE_MS; // успешное подключение сбрасывает паузу переподключения
    streamAlive = true;
    lastMessageAt = Date.now();
    emitServerEvent("connected", { type: "connected" });
    await readStream(resp.body);
  } catch {
    // сеть пропала или стрим оборвался — переподключимся по расписанию ниже
  } finally {
    connecting = false;
    streamAlive = false;
    controller = null;
  }
  if (!stopped) {
    // проверка на момент срабатывания: stopEvents может прийти после планирования
    retryTimer = setTimeout(() => {
      retryTimer = null;
      if (!stopped) void connect();
    }, retryMs);
    retryMs = Math.min(retryMs * 2, RETRY_MAX_MS);
  }
}

async function readStream(body: ReadableStream<Uint8Array>): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    lastMessageAt = Date.now();
    buffer += decoder.decode(value, { stream: true });
    // кадры SSE разделяются пустой строкой; разбирав остаток — в следующем чанке
    for (;;) {
      const boundary = buffer.indexOf("\n\n");
      if (boundary === -1) break;
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      dispatchFrame(frame);
    }
  }
}

function dispatchFrame(frame: string): void {
  let type = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!type || !data) return; // строки-комментарии (keepalive) игнорируем
  try {
    const parsed = JSON.parse(data) as { type?: string };
    // кадр валиден, если поле type совпадает с типом события SSE-кадра
    if (parsed.type === type) {
      emitServerEvent(type as keyof Events, parsed as Events[keyof Events]);
    }
  } catch {
    // повреждённый кадр — пропускаем, следующий исправит состояние
  }
}

// Вкладка снова видна, а стрим молчит дольше двух keepalive-интервалов
// (сон ноутбука, смена сети) — рвём соединение: reconnect подхватит свежее.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || !started || !streamAlive) return;
  if (Date.now() - lastMessageAt > STALE_MS) controller?.abort();
});
