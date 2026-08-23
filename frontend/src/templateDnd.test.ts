import { describe, expect, it } from "vitest";
import type { TemplateSection } from "./api";
import { blockRange, outlineNumbers, planDrop } from "./templateDnd";

// Введение(1) / Общая информация(2) / Общее описание(1) / Назначение(2) / Критерии(3)
const SECTIONS: TemplateSection[] = [
  { level: 1, text: "Введение", required: true, aliases: [] },
  { level: 2, text: "Общая информация", required: true, aliases: [] },
  { level: 1, text: "Общее описание", required: true, aliases: [] },
  { level: 2, text: "Назначение документа", required: true, aliases: [] },
  { level: 3, text: "Критерии приёмки", required: true, aliases: [] },
];

describe("blockRange", () => {
  it("возвращает строку вместе со всеми подразделами", () => {
    expect(blockRange(SECTIONS, 2)).toEqual([2, 4]); // Общее описание + 2 ребёнка
    expect(blockRange(SECTIONS, 0)).toEqual([0, 1]); // Введение + Общая информация
    expect(blockRange(SECTIONS, 4)).toEqual([4, 4]); // лист без детей
  });
});

describe("planDrop", () => {
  it("вставка до: блок переезжает перед целью с её уровнем", () => {
    const next = planDrop(SECTIONS, 2, 0, "before");
    expect(next?.map((s) => s.text)).toEqual([
      "Общее описание",
      "Назначение документа",
      "Критерии приёмки",
      "Введение",
      "Общая информация",
    ]);
    expect(next?.map((s) => s.level)).toEqual([1, 2, 3, 1, 2]); // уровни сохранены
  });

  it("вложение: блок становится дочерним, поддерево сдвигает уровни", () => {
    // «Общее описание» (с детьми) вкладываем в «Введение» → Ур.2, дети Ур.3/Ур.3
    const next = planDrop(SECTIONS, 2, 0, "nest");
    expect(next?.map((s) => s.text)).toEqual([
      "Введение",
      "Общая информация",
      "Общее описание",
      "Назначение документа",
      "Критерии приёмки",
    ]);
    expect(next?.map((s) => s.level)).toEqual([1, 2, 2, 3, 3]);
  });

  it("вложение в Ур.3 невозможно", () => {
    expect(planDrop(SECTIONS, 0, 4, "nest")).toBeNull();
  });

  it("уровни детей не выходят за 3", () => {
    // «Введение» (Ур.1, ребёнок Ур.2) вкладываем под «Назначение документа» (Ур.2)
    const next = planDrop(SECTIONS, 0, 3, "nest");
    expect(next).not.toBeNull();
    expect(next?.every((s) => s.level <= 3)).toBe(true);
  });

  it("бросок в своё поддерево — no-op", () => {
    expect(planDrop(SECTIONS, 2, 3, "before")).toBeNull();
    expect(planDrop(SECTIONS, 2, 4, "after")).toBeNull();
  });

  it("перемещение на текущее место — no-op", () => {
    // блок [2..4] уже стоит сразу после блока [0..1]: «после» с тем же уровнем
    expect(planDrop(SECTIONS, 2, 0, "after")).toBeNull();
  });
});

describe("outlineNumbers", () => {
  it("иерархическая нумерация со сбросом глубже лежащих счётчиков", () => {
    expect(outlineNumbers(SECTIONS).map((i) => i.num)).toEqual([
      "1",
      "1.1",
      "2",
      "2.1",
      "2.1.1",
    ]);
  });

  it("«дыры» в уровнях схлопываются как на бэкенде", () => {
    const holed: TemplateSection[] = [
      { level: 1, text: "А", required: false, aliases: [] },
      { level: 3, text: "В", required: false, aliases: [] }, // станет Ур.2
      { level: 1, text: "Г", required: false, aliases: [] },
    ];
    expect(outlineNumbers(holed).map((i) => i.num)).toEqual(["1", "1.1", "2"]);
  });

  it("пустой список", () => {
    expect(outlineNumbers([])).toEqual([]);
  });
});
