// Утилиты организационной структуры: палитра кластеров и инициалы.
// Палитра согласована с макетом (mockups/teams-mock.html): новый кластер
// без цвета получает следующий по кругу от id — дерево и карты остаются
// разноцветными даже когда цвет в БД не задан.

export const CLUSTER_PALETTE = [
  "#6E5DC6",
  "#0C66E4",
  "#216E4E",
  "#A54800",
  "#AE2E24",
] as const;

export const CLUSTER_PALETTE_BG = [
  "#F3F0FF",
  "#E9F2FF",
  "#DCFFF1",
  "#FFF7D6",
  "#FFEBE6",
] as const;

/** Цвет кластера: из БД или нейтральный из палитры по id. */
export function clusterColor(color: string | null, id: number): string {
  return color ?? CLUSTER_PALETTE[id % CLUSTER_PALETTE.length];
}

/** Подложка того же кластера (чипы команд, шапки): заданный цвет — прозрачной
 *  заливкой, иначе пастель из палитры по id. */
export function clusterColorBg(color: string | null, id: number): string {
  return color ? `${color}1F` : CLUSTER_PALETTE_BG[id % CLUSTER_PALETTE_BG.length];
}

/** Инициалы для аватара: «Иванов Иван» → «ИИ», одиночное слово — 1 буква. */
export function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
}
