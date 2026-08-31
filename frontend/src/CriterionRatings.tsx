import { useState } from "react";
import { api, ApiError, type DocumentRatings } from "./api";

/** Кружки 1..10 и «—»: один выбранный балл, клик по выбранному — снять. */
function ScorePicker({
  label,
  score,
  onPick,
  disabled,
}: {
  label: string;
  score: number | null;
  onPick: (value: number | null) => void;
  disabled?: boolean;
}) {
  return (
    <span className="score-picker" role="radiogroup" aria-label={label}>
      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((value) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={score === value}
          className={`score-btn${score === value ? " on" : ""}`}
          disabled={disabled}
          onClick={() => onPick(score === value ? null : value)}
          title={score === value ? `Снять оценку ${value}` : `Оценить на ${value}`}
        >
          {value}
        </button>
      ))}
      <button
        type="button"
        role="radio"
        aria-checked={score == null}
        className={`score-btn dash${score == null ? " on" : ""}`}
        disabled={disabled}
        onClick={() => onPick(null)}
        title="Без оценки"
      >
        —
      </button>
    </span>
  );
}

/**
 * Блок «Оценка руководителя»: критерии последнего прогона документа,
 * по каждому — оценка 1..10 или «—» (клик по выбранному баллу тоже снимает).
 * Оценка сохраняется сразу; stale — документ перепроверен после оценки.
 */
export default function CriterionRatings({
  documentId,
  ratings,
  onChanged,
}: {
  documentId: number;
  ratings: DocumentRatings;
  onChanged: (next: DocumentRatings) => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const pick = async (criterionId: number, score: number | null) => {
    setBusyId(criterionId);
    setError("");
    try {
      const next = await api<DocumentRatings>(`/api/documents/${documentId}/ratings`, {
        method: "PUT",
        body: JSON.stringify({
          ratings: [{ criterion_id: criterionId, score }],
        }),
      });
      onChanged(next);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось сохранить оценку");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="ratings-zone">
      <p className="muted ratings-hint">
        Ваша экспертная оценка документа по каждому критерию: 1 — плохо, 10 — отлично.
        «—» — не оценивать. Сохраняется сразу.
      </p>
      {error && <div className="alert error">{error}</div>}
      {ratings.criteria.map((item) => (
        <div className="rate-item" key={item.criterion_id}>
          <div className="rate-name">
            {item.name}
            {item.is_archived && <span className="lozenge moved">в архиве</span>}
            {item.stale && (
              <span className="rate-stale" title="Оценка выставлена до последней проверки">
                ⚠ перепроверено после оценки
              </span>
            )}
          </div>
          <ScorePicker
            label={`Оценка «${item.name}»`}
            score={item.score}
            disabled={busyId === item.criterion_id}
            onPick={(value) => pick(item.criterion_id, value)}
          />
        </div>
      ))}
    </div>
  );
}
