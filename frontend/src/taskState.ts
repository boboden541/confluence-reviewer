import { on, type BulkEvent, type SyncEvent, type ValidationEvent } from "./events";

/** Единое состояние фоновых задач для индикаторов на сущностях.
 *  Подписка одна (startEvents уже открыт), слушатели уведомляются при
 *  каждом изменении: sync running + текущий аналитик, bulk прогресс,
 *  множество проверяемых документов. */

export interface SyncCurrent {
  analyst_id: number;
  analyst_name: string;
  index: number;
  total: number;
}

export interface TaskStateSnapshot {
  syncRunning: boolean;
  syncCurrent: SyncCurrent | null;
  bulkRunning: boolean;
  bulkDone: number;
  bulkTotal: number;
  /** Документы, чья проверка прямо сейчас идёт (status=running) */
  validatingDocIds: number[];
}

let syncRunning = false;
let syncCurrent: SyncCurrent | null = null;
let bulkRunning = false;
let bulkDone = 0;
let bulkTotal = 0;
const validating = new Set<number>();

const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((fn) => fn());
}

/** Подписка на изменения состояния задач. Возвращает функцию отписки. */
export function onTaskState(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getTaskState(): TaskStateSnapshot {
  return {
    syncRunning,
    syncCurrent,
    bulkRunning,
    bulkDone,
    bulkTotal,
    validatingDocIds: [...validating],
  };
}

/** Вызывается один раз из App (рядом со startEvents). */
export function bindTaskState(): () => void {
  const offs = [
    on("sync", (e: SyncEvent) => {
      syncRunning = e.running;
      const current = (e as { current?: SyncCurrent | null }).current ?? null;
      syncCurrent = e.running ? current : null;
      notify();
    }),
    on("bulk", (e: BulkEvent) => {
      bulkRunning = e.running;
      bulkDone = e.done;
      bulkTotal = e.total;
      notify();
    }),
    on("validation", (e: ValidationEvent) => {
      if (e.status === "running") {
        validating.add(e.document_id);
      } else {
        validating.delete(e.document_id);
      }
      notify();
    }),
  ];
  return () => {
    offs.forEach((off) => off());
    validating.clear();
  };
}
