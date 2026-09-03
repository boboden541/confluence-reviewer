import { useState } from "react";
import type { ClusterInput } from "./api";
import { CLUSTER_PALETTE } from "./orgUi";

/** Модалка создания/редактирования кластера: название, описание, цвет.
 *  Используется на карте кластеров (создание) и на экране кластера
 *  (редактирование). */
export function ClusterModal({
  title,
  initial,
  saving,
  onSave,
  onClose,
}: {
  title: string;
  initial: ClusterInput;
  saving: boolean;
  onSave: (form: ClusterInput) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<ClusterInput>(initial);

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-panel" role="dialog" aria-label="Кластер">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave({
              name: form.name.trim(),
              description: form.description?.trim() || null,
              color: form.color,
            });
          }}
        >
          <div className="modal-body">
            <span className="field">
              <label htmlFor="cluster-name">Название *</label>
              <input
                id="cluster-name"
                className="text-input"
                placeholder="Например: Билетный бизнес"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                autoFocus
              />
            </span>
            <span className="field">
              <label htmlFor="cluster-desc">Описание</label>
              <textarea
                id="cluster-desc"
                className="text-input"
                rows={3}
                placeholder="Для чего этот кластер, что в него входит"
                value={form.description ?? ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </span>
            <span className="field">
              <label>Цвет</label>
              <div className="swatches" role="radiogroup" aria-label="Цвет кластера">
                {CLUSTER_PALETTE.map((hex) => (
                  <button
                    key={hex}
                    type="button"
                    role="radio"
                    aria-label={hex}
                    aria-checked={form.color === hex}
                    className={`swatch${form.color === hex ? " active" : ""}`}
                    style={{ background: hex }}
                    onClick={() => setForm({ ...form, color: hex })}
                  />
                ))}
              </div>
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
