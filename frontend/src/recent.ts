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

const KINDS: RecentKind[] = ["document", "analyst", "cluster"];

export function listRecent(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as RecentEntry[]) : [];
    if (!Array.isArray(parsed)) return [];
    // localStorage может быть переписан чем угодно: битая запись не должна
    // ронять рендер главной
    return parsed
      .filter(
        (e): e is RecentEntry =>
          e != null &&
          typeof e.id === "number" &&
          typeof e.title === "string" &&
          KINDS.includes(e.kind),
      )
      .slice(0, MAX_ENTRIES);
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
