import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** Единые хлебные крошки сервиса: корень всегда «🏠 Главная», дальше —
 *  место в структуре (а не история кликов). Тип объекта выносится в текст
 *  крошки («Команда GDS», «Отчёт: …»), чтобы «Билетный бизнес» не путался
 *  с командой-тёзкой. */

export interface Crumb {
  /** Текст крошки; последний сегмент — текущая страница (без ссылки) */
  label: ReactNode;
  /** Адрес перехода; без to сегмент некликабелен (например, «Без команды») */
  to?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="breadcrumbs">
      <Link to="/" className="home-crumb" aria-label="Главная">
        🏠 Главная
      </Link>
      {items.map((crumb, index) => {
        const last = index === items.length - 1;
        return (
          <span key={`${index}-${String(crumb.label)}`}>
            <span className="sep">/</span>
            {crumb.to && !last ? (
              <Link to={crumb.to}>{crumb.label}</Link>
            ) : (
              <span className={last ? "crumb-current" : undefined}>{crumb.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
