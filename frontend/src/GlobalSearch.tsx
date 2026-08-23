import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SearchHit } from "./api";

const DEBOUNCE_MS = 300;
const MIN_QUERY = 2; // как на бэкенде: короче — пустой ответ

/** Поиск по документам всех аналитиков — строка поиска в шапке (стиль Confluence). */
export default function GlobalSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY) {
      setHits([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const found = await api<SearchHit[]>(
          `/api/documents/search?q=${encodeURIComponent(trimmed)}`,
        );
        setHits(found);
        setOpen(true);
      } catch {
        setHits([]); // поиск в шапке не должен ронять страницу
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  // клик мимо выпадашки — закрыть
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const go = (id: number) => {
    setOpen(false);
    navigate(`/documents/${id}`);
  };

  return (
    <div className="topbar-search" ref={boxRef}>
      <span className="icon">⌕</span>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => {
          if (hits.length) setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits[0]) go(hits[0].id);
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="Поиск документов…"
        aria-label="Поиск документов"
      />
      {open && query.trim().length >= MIN_QUERY && (
        <div className="search-dropdown">
          {hits.length === 0 && <div className="search-empty">Ничего не найдено</div>}
          {hits.map((hit) => (
            <button key={hit.id} type="button" className="search-hit" onClick={() => go(hit.id)}>
              <span className="search-hit-title">{hit.title}</span>
              <span className="search-hit-meta">{hit.analyst_name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
