import { useEffect, useMemo, useRef, useState } from "react";
import Fuse from "fuse.js";
import { api, ApiError, type Analyst, type DocumentListItem, type ReminderInput } from "./api";
import { STATUS_LABELS } from "./StatusBadge";

/** Модалка создания напоминания: аналитик и документ — комбоксы с нечётким
 *  поиском (fuse.js, реальный fuzzy — опечатки и неполные слова находятся).
 *  Опции — кнопки: клик по ним выбирает значение, списки не закрываются
 *  раньше времени (закрытие — по выбору, клику вне или Esc).
 *  Дата «вернуться» необязательна — просроченные поднимаются на главной. */

export interface ReminderModalProps {
  prefill?: { analyst_id?: number; analyst_name?: string; document_id?: number; document_title?: string };
  onCreated: () => void;
  onClose: () => void;
}

function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p.charAt(0).toUpperCase()).join("") || "?";
}

export default function ReminderModal({ prefill, onCreated, onClose }: ReminderModalProps) {
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [analystId, setAnalystId] = useState<number | null>(prefill?.analyst_id ?? null);
  const [documentId, setDocumentId] = useState<number | null>(prefill?.document_id ?? null);
  const [text, setText] = useState("");
  const [date, setDate] = useState("");

  const [analystQuery, setAnalystQuery] = useState(prefill?.analyst_name ?? "");
  const [docQuery, setDocQuery] = useState(prefill?.document_title ?? "");
  const [analystListOpen, setAnalystListOpen] = useState(false);
  const [docListOpen, setDocListOpen] = useState(false);

  // сегодня по локальной зоне — ниже этой даты напоминание сразу «просрочено»
  const now = new Date();
  const todayStr = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
  const dateInPast = date !== "" && date < todayStr;
  const analystBoxRef = useRef<HTMLDivElement>(null);
  const docBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch(() => setAnalysts([]));
  }, []);

  // документы выбранного аналитика; ответ устаревшего запроса игнорируется
  useEffect(() => {
    if (analystId == null) {
      setDocs([]);
      return;
    }
    let stale = false;
    api<{ items: DocumentListItem[] }>(`/api/analysts/${analystId}/documents?page=1&page_size=100`)
      .then((page: { items: DocumentListItem[] }) => {
        if (!stale) setDocs(page.items);
      })
      .catch(() => {
        if (!stale) setDocs([]);
      });
    return () => {
      stale = true;
    };
  }, [analystId]);

  // Esc закрывает модалку — как во всех диалогах сервиса
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // клик вне комбобокса закрывает его список
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (analystBoxRef.current && !analystBoxRef.current.contains(target)) setAnalystListOpen(false);
      if (docBoxRef.current && !docBoxRef.current.contains(target)) setDocListOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectedAnalyst = useMemo(
    () => analysts.find((a) => a.id === analystId) ?? null,
    [analysts, analystId],
  );
  const selectedDoc = useMemo(
    () => docs.find((d) => d.id === documentId) ?? null,
    [docs, documentId],
  );

  // нечёткий поиск: fuse по ФИО/email и по названию документа
  const analystFuse = useMemo(
    () => new Fuse(analysts, { keys: ["full_name", "email"], threshold: 0.4, ignoreLocation: true }),
    [analysts],
  );
  const docFuse = useMemo(
    () => new Fuse(docs, { keys: ["title"], threshold: 0.4, ignoreLocation: true }),
    [docs],
  );

  const analystMatches = useMemo(() => {
    const needle = analystQuery.trim();
    if (!needle) return analysts.slice(0, 8);
    const fuzzy = analystFuse.search(needle).map((r) => r.item);
    const fallback = analysts.filter(
      (a) => a.full_name.toLowerCase().includes(needle.toLowerCase()) || a.email.toLowerCase().includes(needle.toLowerCase()),
    );
    return (fuzzy.length ? fuzzy : fallback).slice(0, 8);
  }, [analystQuery, analystFuse, analysts]);

  const docMatches = useMemo(() => {
    const needle = docQuery.trim();
    if (!needle) return docs.slice(0, 8);
    const fuzzy = docFuse.search(needle).map((r) => r.item);
    const fallback = docs.filter((d) => d.title.toLowerCase().includes(needle.toLowerCase()));
    return (fuzzy.length ? fuzzy : fallback).slice(0, 8);
  }, [docQuery, docFuse, docs]);

  const submit = async () => {
    if (analystId == null || !text.trim()) return;
    setSaving(true);
    setError("");
    const payload: ReminderInput = {
      analyst_id: analystId,
      document_id: documentId,
      text: text.trim(),
      remind_at: date ? new Date(`${date}T12:00:00Z`).toISOString() : null,
    };
    try {
      await api("/api/reminders", { method: "POST", body: JSON.stringify(payload) });
      onCreated();
      onClose();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось создать напоминание");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-panel" role="dialog" aria-label="Новое напоминание">
        <div className="modal-head">
          <h2>⏰ Новое напоминание</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="modal-body">
            {error && <div className="alert error">{error}</div>}

            <span className="field">
              <label htmlFor="rem-analyst">Аналитик *</label>
              <div className="combo" ref={analystBoxRef}>
                <input
                  id="rem-analyst"
                  className="text-input"
                  placeholder="Поиск по ФИО — нечёткий"
                  value={selectedAnalyst ? selectedAnalyst.full_name : analystQuery}
                  onChange={(e) => {
                    setAnalystId(null);
                    setAnalystQuery(e.target.value);
                    setAnalystListOpen(true);
                  }}
                  onFocus={() => setAnalystListOpen(true)}
                  autoComplete="off"
                />
                {analystListOpen && !selectedAnalyst && (
                  <div className="combo-list found-list">
                    {analysts.length === 0 && <div className="combo-empty">аналитики не заведены</div>}
                    {analystMatches.length === 0 && analysts.length > 0 && (
                      <div className="combo-empty">никого не найдено</div>
                    )}
                    {analystMatches.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        className="found-row"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          setAnalystId(a.id);
                          setDocumentId(null);
                          setDocQuery("");
                          setAnalystQuery(a.full_name);
                          setAnalystListOpen(false);
                        }}
                      >
                        <span className="p-avatar small" style={{ background: "var(--blue, #0c66e4)" }} aria-hidden="true">
                          {initials(a.full_name)}
                        </span>
                        <span className="found-info">
                          <span className="found-name">{a.full_name}</span>
                          <span className="found-sub">{a.team_name ? `${a.team_name} · ` : ""}{a.email}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </span>

            <span className="field">
              <label htmlFor="rem-doc">Документ (необязательно)</label>
              <div className="combo" ref={docBoxRef}>
                <input
                  id="rem-doc"
                  className="text-input"
                  placeholder={analystId == null ? "Сначала выберите аналитика" : "Поиск по документам аналитика — нечёткий"}
                  value={selectedDoc ? selectedDoc.title : docQuery}
                  onChange={(e) => {
                    setDocumentId(null);
                    setDocQuery(e.target.value);
                    setDocListOpen(true);
                  }}
                  onFocus={() => {
                    if (analystId != null) setDocListOpen(true);
                  }}
                  autoComplete="off"
                />
                {docListOpen && analystId != null && !selectedDoc && (
                  <div className="combo-list found-list">
                    <button
                      type="button"
                      className="found-row"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setDocumentId(null);
                        setDocQuery("");
                        setDocListOpen(false);
                      }}
                    >
                      <span className="found-name">— без документа —</span>
                    </button>
                    {docMatches.map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        className="found-row"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          setDocumentId(d.id);
                          setDocQuery(d.title);
                          setDocListOpen(false);
                        }}
                      >
                        <span className="found-info">
                          <span className="found-name">{d.title}</span>
                          <span className="found-sub">проверка: {STATUS_LABELS[d.validation_status]}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {analystId == null && (
                  <div className="hint">Сначала выберите аналитика — появятся его документы.</div>
                )}
              </div>
            </span>

            <span className="field">
              <label htmlFor="rem-text">Что напомнить *</label>
              <textarea
                id="rem-text"
                className="text-input"
                rows={3}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Например: проверить, что учёл комментарии по разделу «Критерии приёмки»"
              />
            </span>

            <span className="field">
              <label htmlFor="rem-date">Вернуться (дата)</label>
              <input
                id="rem-date"
                className="text-input"
                type="date"
                min={todayStr}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
              {dateInPast && (
                <div className="alert error" style={{ marginTop: 6 }}>
                  Дата уже прошла — выберите сегодняшнюю или будущую.
                </div>
              )}
              {!dateInPast && (
                <div className="hint">Необязательно: напоминание с датой поднимется в группу «Вернуться» на главной.</div>
              )}
            </span>
          </div>
          <div className="modal-foot">
            <button className="btn subtle" type="button" onClick={onClose}>
              Отмена
            </button>
            <button className="btn primary" type="submit" disabled={saving || analystId == null || !text.trim() || dateInPast}>
              {saving ? "Создание…" : "Создать напоминание"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
