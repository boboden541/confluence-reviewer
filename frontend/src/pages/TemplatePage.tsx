import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type TemplateCard,
  type TemplateInfo,
  type TemplateSection,
  type TemplateVersionInfo,
} from "../api";
import { blockRange, outlineNumbers, planDrop, type DropZone } from "../templateDnd";

// Примеры для живой демонстрации маркера названия
const TITLE_EXAMPLES = ["[СТ] GDS-15 Загрузка кино", "GDS-15 Загрузка кино"];

/** Та же семантика, что у бэкенда: маркер — отдельное слово, регистр не важен. */
function markerMatches(title: string, marker: string): boolean {
  const trimmed = marker.trim();
  if (!trimmed) return true; // маркер не задан — подходит любое название
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`(^|[^\\p{L}\\p{N}_])${escaped}(?=$|[^\\p{L}\\p{N}_])`, "u");
  return pattern.test(title);
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("ru-RU");
}

/** Зона бросания по положению курсора на строке: верх/низ — рядом, центр — вложить. */
function zoneFor(target: HTMLElement, clientY: number): DropZone {
  const rect = target.getBoundingClientRect();
  const ratio = rect.height > 0 ? (clientY - rect.top) / rect.height : 0.5;
  return ratio < 0.3 ? "before" : ratio > 0.7 ? "after" : "nest";
}

/**
 * Редактор шаблона: /templates/new — создание с нуля, /templates/:id —
 * очередная версия существующего. Название видно в диалоге проверки,
 * поэтому редактируется здесь; каждое сохранение — новая версия.
 */
export default function TemplatePage() {
  const { templateId } = useParams();
  const navigate = useNavigate();
  const isNew = templateId === undefined;
  const [template, setTemplate] = useState<TemplateInfo | null>(null);
  const [versions, setVersions] = useState<TemplateVersionInfo[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [marker, setMarker] = useState("");
  const [sections, setSections] = useState<TemplateSection[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // перетаскиваемое поддерево (диапазон строк) и текущая подсказка зоны
  const [dragRange, setDragRange] = useState<[number, number] | null>(null);
  const [dropHint, setDropHint] = useState<{ index: number; zone: DropZone } | null>(null);
  const badgeRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (isNew || !templateId) return;
    setLoading(true);
    setError("");
    try {
      const [tpl, vers] = await Promise.all([
        api<TemplateInfo>(`/api/templates/${templateId}`),
        api<TemplateVersionInfo[]>(`/api/templates/${templateId}/versions`),
      ]);
      setTemplate(tpl);
      setName(tpl.name);
      setDescription(tpl.description ?? "");
      setMarker(tpl.title_marker);
      setSections(tpl.sections);
      setVersions(vers);
      setDirty(false);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить шаблон");
    } finally {
      setLoading(false);
    }
  }, [isNew, templateId]);

  useEffect(() => {
    load();
  }, [load]);

  // Несохранённая структура — предупреждаем при закрытии вкладки
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  // --- правки структуры ---

  const updateSection = (index: number, patch: Partial<TemplateSection>) => {
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
    setDirty(true);
  };

  const removeBlock = (index: number) => {
    setSections((prev) => {
      const [start, end] = blockRange(prev, index);
      return prev.filter((_, i) => i < start || i > end);
    });
    setDirty(true);
  };

  const addSection = () => {
    setSections((prev) => [
      ...prev,
      { level: 1, text: "Новый раздел", required: false, aliases: [] },
    ]);
    setDirty(true);
  };

  const setAliases = (index: number, raw: string) =>
    updateSection(index, {
      aliases: raw
        .split(",")
        .map((alias) => alias.trim())
        .filter(Boolean),
    });

  const save = async () => {
    setSaving(true);
    setError("");
    setInfo("");
    try {
      const body = JSON.stringify({
        name: name.trim(),
        description: description.trim() || null,
        title_marker: marker,
        sections,
      });
      if (isNew) {
        // создание: после первой версии открываем редактор уже с id шаблона
        const card = await api<TemplateCard>("/api/templates", { method: "POST", body });
        navigate(`/templates/${card.id}`, { replace: true });
        return;
      }
      const saved = await api<TemplateInfo>(`/api/templates/${templateId}`, {
        method: "PUT",
        body,
      });
      setTemplate(saved);
      setName(saved.name);
      setDescription(saved.description ?? "");
      setMarker(saved.title_marker);
      setSections(saved.sections); // уровни мог нормализовать бэкенд
      setDirty(false);
      setInfo(`Шаблон сохранён — версия №${saved.id}. Применится к следующим проверкам.`);
      setVersions(
        await api<TemplateVersionInfo[]>(`/api/templates/${templateId}/versions`),
      );
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить шаблон");
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    if (isNew || !templateId) return;
    if (!window.confirm(`Архивировать шаблон «${name}»? Он исчезнет из диалога проверки; карточка и история версий останутся.`)) {
      return;
    }
    setError("");
    try {
      await api(`/api/templates/${templateId}/archive`, { method: "POST" });
      navigate("/templates");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось архивировать шаблон");
    }
  };

  // --- drag & drop ---

  // тянуть можно только за ручку — иначе DnD мешает выделению текста в полях
  const enableDrag = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest(".handle")) {
      const row = target.closest<HTMLElement>(".section-row");
      if (row) row.draggable = true;
    }
  };

  const clearDraggable = () => {
    document.querySelectorAll<HTMLElement>(".section-row[draggable]").forEach((row) => {
      row.draggable = false;
    });
  };

  const moveBadge = (x: number, y: number, text: string) => {
    const badge = badgeRef.current;
    if (!badge) return;
    badge.textContent = text;
    badge.style.display = "block";
    badge.style.left = `${x + 14}px`;
    badge.style.top = `${y + 14}px`;
  };

  const hideBadge = () => {
    if (badgeRef.current) badgeRef.current.style.display = "none";
  };

  const badgeText = (index: number, zone: DropZone): string => {
    const target = sections[index];
    if (!target) return "";
    if (zone === "nest") {
      return target.level >= 3
        ? "Максимум 3 уровня — вложить нельзя"
        : `Вложить в «${target.text}» (Ур. ${target.level + 1})`;
    }
    return zone === "before"
      ? `Вставить до «${target.text}»`
      : `Вставить после «${target.text}»`;
  };

  const finishDrag = () => {
    setDragRange(null);
    setDropHint(null);
    hideBadge();
    clearDraggable();
  };

  const onDragStart = (index: number) => {
    setDragRange(blockRange(sections, index));
    setError("");
    setInfo("");
  };

  const onDragOver = (index: number, e: React.DragEvent) => {
    if (!dragRange) return;
    if (index >= dragRange[0] && index <= dragRange[1]) return; // на своё поддерево не бросаем
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    const zone = zoneFor(e.currentTarget as HTMLElement, e.clientY);
    setDropHint({ index, zone });
    moveBadge(e.clientX, e.clientY, badgeText(index, zone));
  };

  const onDrop = (index: number, e: React.DragEvent) => {
    if (!dragRange) return;
    e.preventDefault();
    if (index >= dragRange[0] && index <= dragRange[1]) {
      finishDrag();
      return;
    }
    const zone = zoneFor(e.currentTarget as HTMLElement, e.clientY);
    const next = planDrop(sections, dragRange[0], index, zone);
    if (next) {
      setSections(next);
      setDirty(true);
    }
    finishDrag();
  };

  const rowClass = (index: number, level: number): string => {
    const classes = ["section-row", `indent-${level}`];
    if (dragRange && index >= dragRange[0] && index <= dragRange[1]) classes.push("dragging");
    if (dropHint && dropHint.index === index) {
      if (dropHint.zone === "nest") classes.push("nest-target");
      else classes.push(dropHint.zone === "before" ? "drop-before" : "drop-after");
    }
    return classes.join(" ");
  };

  const outline = outlineNumbers(sections);

  if (loading && !isNew) {
    return (
      <section className="page">
        <p className="muted">Загрузка шаблона…</p>
      </section>
    );
  }

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <span>Ревью требований</span>
        <span className="sep">/</span>
        <Link to="/templates">Шаблоны требований</Link>
        <span className="sep">/</span>
        <span>{isNew ? "Новый шаблон" : name || "Шаблон"}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">🧩</span>
            {isNew ? "Новый шаблон требований" : name || "Шаблон требований"}
          </h1>
          <div className="page-meta">
            {template
              ? `версия №${template.id} от ${formatDate(template.created_at)}`
              : "появится в диалоге проверки после первого сохранения"}
          </div>
        </div>
        <div className="head-actions">
          {!isNew && (
            <button className="btn subtle" onClick={archive} disabled={saving}>
              В архив
            </button>
          )}
          <button className="btn primary" onClick={save} disabled={saving || (isNew && !name.trim())}>
            {saving ? "Сохранение…" : isNew ? "Создать шаблон" : "Сохранить шаблон"}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {info && <div className="alert ok">{info}</div>}

      <div className="panel">
        <h2>Шаблон</h2>
        <div className="form-row">
          <div className="field tpl-field">
            <label htmlFor="tpl-name">Название (видно в диалоге проверки)</label>
            <input
              id="tpl-name"
              className="text-input"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setDirty(true);
              }}
              placeholder="например, Шаблон требований к доработке"
              maxLength={255}
            />
          </div>
        </div>
        <div className="form-row">
          <div className="field tpl-field">
            <label htmlFor="tpl-description">Описание (необязательно)</label>
            <textarea
              id="tpl-description"
              className="text-input tpl-desc-input"
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setDirty(true);
              }}
              placeholder="для каких документов этот шаблон"
              rows={2}
              maxLength={2000}
            />
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Название документа</h2>
        <div className="marker-row">
          <span className="muted">Название должно содержать маркер</span>
          <input
            className="marker-input"
            value={marker}
            onChange={(e) => {
              setMarker(e.target.value);
              setDirty(true);
            }}
            placeholder="например, СТ"
          />
          <span className="muted">— регистр не важен, ищется отдельным словом</span>
        </div>
        <div className="demo-title">
          <span className="muted">Примеры:</span>
          {TITLE_EXAMPLES.map((example) => (
            <span key={example} className={`chip ${markerMatches(example, marker) ? "ok" : "bad"}`}>
              {example}
            </span>
          ))}
          {!marker.trim() && <span className="muted">маркер пуст: подходит любое название</span>}
        </div>
      </div>

      <div className="template-layout">
        <div className="panel">
          <h2>Структура разделов</h2>
          <p className="muted">
            Тяните за <span className="handle-demo">⋮⋮</span> — верх/низ строки: вставить рядом
            (линия показывает место), середина: вложить разделом уровнем ниже.{" "}
            <span className="req-star">✱</span> — обязателен (клик), ✕ — удалить вместе с
            подразделами. Порядок и уровни разделов у аналитиков могут отличаться от шаблона —
            это не замечание, проверяется наличие раздела.
          </p>
          <div className="template-rows" onMouseDown={enableDrag} onDragEnd={finishDrag}>
            {sections.map((section, index) => (
              <div key={index} className="section-block">
                <div
                  className={rowClass(index, section.level)}
                  onDragStart={() => onDragStart(index)}
                  onDragOver={(e) => onDragOver(index, e)}
                  onDrop={(e) => onDrop(index, e)}
                >
                  <span className="handle" title="Перетащить">
                    ⋮⋮
                  </span>
                  <select
                    className="level-select"
                    value={section.level}
                    onChange={(e) => updateSection(index, { level: Number(e.target.value) })}
                    aria-label={`Уровень раздела «${section.text}»`}
                  >
                    <option value={1}>Ур. 1</option>
                    <option value={2}>Ур. 2</option>
                    <option value={3}>Ур. 3</option>
                  </select>
                  <input
                    className="name"
                    value={section.text}
                    onChange={(e) => updateSection(index, { text: e.target.value })}
                    placeholder="Название раздела"
                  />
                  <button
                    type="button"
                    className={`req-toggle${section.required ? " on" : ""}`}
                    onClick={() => updateSection(index, { required: !section.required })}
                    title="Обязательный раздел"
                  >
                    ✱
                  </button>
                  <button
                    type="button"
                    className="row-x"
                    onClick={() => removeBlock(index)}
                    title="Удалить вместе с подразделами"
                  >
                    ✕
                  </button>
                </div>
                <div className="aliases" style={{ marginLeft: `${1.6 + section.level * 1.6}rem` }}>
                  доп. названия (через запятую):{" "}
                  <input
                    value={section.aliases.join(", ")}
                    onChange={(e) => setAliases(index, e.target.value)}
                    placeholder="например: Полезные ресурсы"
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="add-row">
            <button className="btn subtle small" onClick={addSection}>
              + Добавить раздел
            </button>
          </div>
        </div>

        <div className="template-side">
          <div className="panel">
            <h2>Как будет проверяться</h2>
            <div className="muted">Название документа:</div>
            <div className="preview-box">
              {marker.trim() ? (
                <>
                  должно содержать: <b>«{marker.trim()}»</b>
                </>
              ) : (
                "любое название (маркер не задан)"
              )}
            </div>
            <div className="muted" style={{ marginTop: "0.8rem" }}>
              Структура разделов (1 → 1.1 → 1.1.1):
            </div>
            <div className="preview-box">
              {outline.length === 0 && <span className="muted">разделы не заданы</span>}
              {outline.map((item, index) => (
                <div
                  key={index}
                  className="outline-item"
                  style={{ marginLeft: `${(item.level - 1) * 1.2}rem` }}
                >
                  <span className="outline-num">{item.num}.</span>
                  {sections[index].required ? (
                    <span className="req-star">✱ </span>
                  ) : (
                    <span className="opt-mark">○ </span>
                  )}
                  {sections[index].text || "(без названия)"}
                </div>
              ))}
            </div>
            <div className="muted" style={{ marginTop: "0.6rem" }}>
              Красные ✱ — обязательные, серые ○ — необязательные. Совпадение имён неточное
              («Общая информация о сервисе» ≈ «Общая информация»), порядок и уровни разделов
              не проверяются. Изменения сразу видны здесь.
            </div>
          </div>

          {versions.length > 0 && (
            <div className="panel">
              <h2>История версий</h2>
              <ul className="versions">
                {versions.slice(0, 5).map((version) => (
                  <li key={version.id} className={version.is_active ? "active" : ""}>
                    №{version.id} · {formatDate(version.created_at)} · {version.section_count} разд.
                    {version.is_active ? " · активна" : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="head-actions" style={{ marginTop: "16px" }}>
        <button className="btn primary" onClick={save} disabled={saving || (isNew && !name.trim())}>
          {saving ? "Сохранение…" : isNew ? "Создать шаблон" : "Сохранить шаблон"}
        </button>
        {isNew ? (
          <button className="btn subtle" onClick={() => navigate("/templates")} disabled={saving}>
            Отмена
          </button>
        ) : (
          <button
            className="btn subtle"
            onClick={() => {
              setInfo("");
              load();
            }}
            disabled={saving || !dirty}
          >
            Сбросить изменения
          </button>
        )}
        <span className="muted">
          Уже созданные отчёты не пересчитываются — шаблон применяется к следующим проверкам
        </span>
      </div>

      <div className="drop-badge" ref={badgeRef} />
    </section>
  );
}
