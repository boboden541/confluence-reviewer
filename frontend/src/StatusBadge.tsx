// Лузендж статуса проверки в стиле Confluence (Atlassian Design System).
import type { ValidationStatus } from "./api";

export const STATUS_LABELS: Record<ValidationStatus, string> = {
  not_checked: "не проверено",
  in_progress: "проверяется",
  passed: "пройдено",
  failed: "не пройдено",
  error: "ошибка",
};

// вид лузенджа: success/error — мягкие, moved — плотный красный (технический сбой)
const LOZENGE_KINDS: Record<ValidationStatus, string> = {
  not_checked: "default",
  in_progress: "inprogress",
  passed: "success",
  failed: "error",
  error: "moved",
};

export default function StatusBadge({ status }: { status: ValidationStatus }) {
  return <span className={`lozenge ${LOZENGE_KINDS[status]}`}>{STATUS_LABELS[status]}</span>;
}
