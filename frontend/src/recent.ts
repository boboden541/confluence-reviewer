/** «Недавние» для главной: локальный журнал посещений (localStorage, без бэкенда).
 *  Дедуп по ключу типа+id: повторный визит поднимает запись наверх. */

export type RecentKind = "document" | "analyst" | "cluster";

export interface RecentEntry {
  kind: RecentKind;
  id: number;
  title: string;
  at: string;
}

const STORAGE_KEY = "cr-recent";
const MAX_ENTRIES = 8;

export function listRecent(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as RecentEntry[]) : [];
    return Array.isArray(parsed) ? parsed.slice(0, MAX_ENTRIES) : [];
  } catch {
    return [];
  }
}

export function pushRecent(kind: RecentKind, id: number, title: string): void {
  const entry: RecentEntry = { kind, id, title, at: new Date().toISOString() };
  const rest = listRecent().filter((e) => !(e.kind === kind && e.id === id));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([entry, ...rest].slice(0, MAX_ENTRIES)));
  } catch {
    // localStorage недоступен (приватный режим) — недавние просто не копятся
  }
}
