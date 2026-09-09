import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Analyst, type DocumentListItem, type ReminderInput } from "./api";

/** Модалка создания напоминания: аналитик и документ — комбоксы с нечётким
 *  поиском (fuse.js); документ подгружается по выбранному аналитику;
 *  дата «вернуться» необязательна — просроченные поднимаются на главной. */

export interface ReminderModalProps {
  prefill?: { analyst_id?: number; analyst_name?: string; document_id?: number; document_title?: string };
  onCreated: () => void;
  onClose: () => void;
}

export default function ReminderModal({ prefill, onCreated, onClose }: ReminderModalProps) {
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // выбранные значения (id); строки поиска — отдельно
  const [analystId, setAnalystId] = useState<number | null>(prefill?.analyst_id ?? null);
  const [documentId, setDocumentId] = useState<number | null>(prefill?.document_id ?? null);
  const [text, setText] = useState("");
  const [date, setDate] = useState("");

  const [analystQuery, setAnalystQuery] = useState(prefill?.analyst_name ?? "");
  const [docQuery, setDocQuery] = useState(prefill?.document_title ?? "");
  const [analystListOpen, setAnalystListOpen] = useState(false);
  const [docListOpen, setDocListOpen] = useState(false);

  useEffect(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch(() => setAnalysts([]));
  }, []);

  // документы выбранного аналитика
  useEffect(() => {
    if (analystId == null) {
      setDocs([]);
      return;
    }
    api<{ items: DocumentListItem[] }>(`/api/analysts/${analystId}/documents?page=1&page_size=100`)
      .then((page: { items: DocumentListItem[] }) => setDocs(page.items))
      .catch(() => setDocs([]));
  }, [analystId]);

  const selectedAnalyst = useMemo(
    () => analysts.find((a) => a.id === analystId) ?? null,
    [analysts, analystId],
  );
  const selectedDoc = useMemo(
    () => docs.find((d) => d.id === documentId) ?? null,
    [docs, documentId],
  );

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
                onBlur={() => window.setTimeout(() => setAnalystListOpen(false), 150)}
                autoComplete="off"
              />
              {analystListOpen && !selectedAnalyst && (
                <div className="combo-list open">
                  {analysts.length === 0 && <div className="combo-empty">аналитики не заведены</div>}
                  {analysts
                    .filter((a) => !analystQuery.trim() || a.full_name.toLowerCase().includes(analystQuery.trim().toLowerCase()))
                    .slice(0, 8)
                    .map((a) => (
                      <div
                        key={a.id}
                        className="combo-opt"
                        onClick={() => {
                          setAnalystId(a.id);
                          setDocumentId(null);
                          setDocQuery("");
                          setAnalystQuery(a.full_name);
                          setAnalystListOpen(false);
                        }}
                      >
                        <span>
                          <span className="combo-name">{a.full_name}</span>
                          <br />
                          <span className="combo-sub">{a.team_name ? `${a.team_name} · ` : ""}{a.email}</span>
                        </span>
                      </div>
                    ))}
                </div>
              )}
              {selectedAnalyst && <div className="hint">поиск снова откроется при правке поля</div>}
            </span>

            <span className="field">
              <label htmlFor="rem-doc">Документ (необязательно)</label>
              <input
                id="rem-doc"
                className="text-input"
                placeholder={analystId == null ? "сначала выберите аналитика" : "Поиск по документам аналитика — нечёткий"}
                disabled={analystId == null}
                value={selectedDoc ? selectedDoc.title : docQuery}
                onChange={(e) => {
                  setDocumentId(null);
                  setDocQuery(e.target.value);
                  setDocListOpen(true);
                }}
                onFocus={() => setDocListOpen(true)}
                onBlur={() => window.setTimeout(() => setDocListOpen(false), 150)}
                autoComplete="off"
              />
              {docListOpen && analystId != null && !selectedDoc && (
                <div className="combo-list open">
                  <div
                    className="combo-opt"
                    onClick={() => {
                      setDocumentId(null);
                      setDocQuery("");
                      setDocListOpen(false);
                    }}
                  >
                    <span className="combo-name">— без документа —</span>
                  </div>
                  {docs
                    .filter((d) => !docQuery.trim() || d.title.toLowerCase().includes(docQuery.trim().toLowerCase()))
                    .slice(0, 8)
                    .map((d) => (
                      <div
                        key={d.id}
                        className="combo-opt"
                        onClick={() => {
                          setDocumentId(d.id);
                          setDocQuery(d.title);
                          setDocListOpen(false);
                        }}
                      >
                        <span>
                          <span className="combo-name">{d.title}</span>
                          <br />
                          <span className="combo-sub">проверка: {d.validation_status === "failed" ? "не пройдена" : d.validation_status === "passed" ? "пройдена" : d.validation_status === "error" ? "ошибка" : "не проверялся"}</span>
                        </span>
                      </div>
                    ))}
                </div>
              )}
              <div className="hint">В карточке напоминания будет ссылка в отчёт документа.</div>
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
              <input id="rem-date" className="text-input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <div className="hint">Необязательно: просроченные напоминания поднимутся в верхнюю группу на главной.</div>
            </span>
          </div>
          <div className="modal-foot">
            <button className="btn subtle" type="button" onClick={onClose}>
              Отмена
            </button>
            <button className="btn primary" type="submit" disabled={saving || analystId == null || !text.trim()}>
              {saving ? "Создание…" : "Создать напоминание"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
