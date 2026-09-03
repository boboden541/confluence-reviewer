import { useEffect, useState } from "react";
import type { TeamInput } from "./api";

/** Модалка создания/редактирования команды: название (уникально в кластере)
 *  и описание. */
export function TeamModal({
  title,
  initial,
  saving,
  onSave,
  onClose,
}: {
  title: string;
  initial: TeamInput;
  saving: boolean;
  onSave: (form: TeamInput) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<TeamInput>(initial);

  // Esc закрывает модалку, как и крестик
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-panel" role="dialog" aria-label="Команда">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave({ name: form.name.trim(), description: form.description?.trim() || null });
          }}
        >
          <div className="modal-body">
            <span className="field">
              <label htmlFor="team-name">Название *</label>
              <input
                id="team-name"
                className="text-input"
                placeholder="Например: Возвраты"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
              />
            </span>
            <span className="field">
              <label htmlFor="team-desc">Описание</label>
              <textarea
                id="team-desc"
                className="text-input"
                rows={3}
                placeholder="Чем команда занимается"
                value={form.description ?? ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </span>
          </div>
          <div className="modal-foot">
            <button className="btn subtle" type="button" onClick={onClose}>
              Отмена
            </button>
            <button className="btn primary" type="submit" disabled={saving || !form.name.trim()}>
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
