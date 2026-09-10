import { createContext, useContext } from "react";

/** Контекст создания напоминаний: глобальная кнопка (FAB) открывает
 *  модалку без предзаполнения; экраны контекста (отчёт, профиль) —
 *  с подставленными аналитиком/документом. */
export interface ReminderPrefill {
  analyst_id?: number;
  analyst_name?: string;
  document_id?: number;
  document_title?: string;
}

export const RemindersContext = createContext<{ open: (prefill?: ReminderPrefill) => void }>({
  open: () => {},
});

export function useReminders() {
  return useContext(RemindersContext);
}
