// Логика drag & drop редактора шаблона: чистые функции, легко тестируются
// (в jsdom нет раскладки — раскладку мокаем, логику проверяем напрямую).

import type { TemplateSection } from "./api";

export type DropZone = "before" | "after" | "nest";

/** Диапазон строк поддерева: строка index + все разделы глубже её уровня. */
export function blockRange(sections: TemplateSection[], index: number): [number, number] {
  const root = sections[index];
  let end = index;
  if (!root) return [index, index];
  while (end + 1 < sections.length && sections[end + 1].level > root.level) {
    end += 1;
  }
  return [index, end];
}

/**
 * Куда встанет перетаскиваемый блок. Возвращает новый массив секций
 * или null — если бросок невозможен (в своё поддерево, на Ур.3 при
 * вложении) или ничего не меняет (no-op).
 */
export function planDrop(
  sections: TemplateSection[],
  dragIndex: number,
  targetIndex: number,
  zone: DropZone,
): TemplateSection[] | null {
  const [start, end] = blockRange(sections, dragIndex);
  const target = sections[targetIndex];
  if (!target || (targetIndex >= start && targetIndex <= end)) return null;

  const oldRootLevel = sections[dragIndex].level;
  let newRootLevel = target.level;
  let insertAt: number;
  if (zone === "nest") {
    if (target.level >= 3) return null; // максимум 3 уровня
    newRootLevel = target.level + 1;
    insertAt = blockRange(sections, targetIndex)[1] + 1;
  } else if (zone === "before") {
    insertAt = targetIndex;
  } else {
    insertAt = blockRange(sections, targetIndex)[1] + 1;
  }

  // индекс вставки в массиве без перетаскиваемого блока
  const adjusted = insertAt > start ? insertAt - (end - start + 1) : insertAt;
  const levelDelta = newRootLevel - oldRootLevel;
  if (levelDelta === 0 && adjusted === start) return null; // уже на месте

  const rest = sections.filter((_, i) => i < start || i > end);
  // поддерево переезжает целиком, уровни сдвигаются на delta (в пределах 1..3)
  const moved = sections.slice(start, end + 1).map((section) => ({
    ...section,
    level: Math.min(3, Math.max(1, section.level + levelDelta)),
  }));
  return [...rest.slice(0, adjusted), ...moved, ...rest.slice(adjusted)];
}

export interface OutlineItem {
  num: string;
  /** Эффективный уровень без «дыр» — как нормализует бэкенд при сохранении */
  level: number;
}

/**
 * Иерархическая нумерация предпросмотра: 1 → 1.1 → 1.1.1. Те же правила,
 * что и в normalize_sections бэкенда: после Ур.1 раздел Ур.3 считается Ур.2.
 */
export function outlineNumbers(sections: TemplateSection[]): OutlineItem[] {
  const counters = [0, 0, 0];
  let prevLevel = 0;
  const items: OutlineItem[] = [];
  for (const section of sections) {
    const level = Math.min(Math.max(section.level, 1), Math.min(3, prevLevel + 1));
    prevLevel = level;
    counters[level - 1] += 1;
    for (let i = level; i < 3; i += 1) counters[i] = 0;
    items.push({ num: counters.slice(0, level).join("."), level });
  }
  return items;
}
