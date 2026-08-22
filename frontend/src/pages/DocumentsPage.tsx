import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Analyst,
  type BulkValidationStatus,
  type DocumentListItem,
  type DocumentPage,
} from "../api";

const STATUS_LABELS: Record<string, string> = {
  not_checked: "не проверено",
  in_progress: "проверяется",
  passed: "пройдено",
  failed: "не пройдено",
  error: "ошибка",
};

const PAGE_SIZE = 20;
const SEMANTIC_MIN = 3; // минимум символов для запроса к ИИ
const SEMANTIC_DEBOUNCE_MS = 800; // не дёргаем ИИ на каждое нажатие

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default function DocumentsPage() {
  const { analystId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [items, setItems] = useState<DocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  // фильтры живут в адресе (?q=…&url=…): вернувшись кнопкой «Назад»,
  // пользователь попадает в тот же результат поиска
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [urlFilter, setUrlFilter] = useState(() => searchParams.get("url") ?? "");
  const [semantic, setSemantic] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bulk, setBulk] = useState<BulkValidationStatus | null>(null);
  const bulkTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // защита от устаревших ответов: сменили режим/фильтр — старый ответ
  // не должен затирать новое состояние списка
  const loadSeq = useRef(0);

  // targetPage > 1 — догружаем к уже показанным, иначе заменяем список
  // (фильтр/поиск сменились — начинаем с первой страницы).
  const load = useCallback(
    async (targetPage: number, append: boolean) => {
      if (!analystId) return;
      const seq = ++loadSeq.current;
      setLoading(true);
      try {
        const trimmed = query.trim();
        let data: DocumentPage;
        let more = false;
        if (semantic) {
          // поиск по смыслу: одна выдача от ИИ, догрузки страниц нет
          const params = new URLSearchParams({ query: trimmed, limit: String(PAGE_SIZE) });
          data = await api<DocumentPage>(
            `/api/analysts/${analystId}/documents/semantic?${params}`,
          );
        } else {
          const params = new URLSearchParams({
            page: String(targetPage),
            page_size: String(PAGE_SIZE),
          });
          if (trimmed) params.set("query", trimmed);
          if (urlFilter.trim()) params.set("url", urlFilter.trim());
          data = await api<DocumentPage>(`/api/analysts/${analystId}/documents?${params}`);
          more = targetPage * data.page_size < data.total;
        }
        if (seq !== loadSeq.current) return; // ответ уже неактуален
        setItems((prev) => (append && !semantic ? [...prev, ...data.items] : data.items));
        setTotal(data.total);
        setHasMore(more);
        setPage(targetPage);
        setLoaded(true);
        setError("");
      } catch (exc) {
        if (seq === loadSeq.current) {
          setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить документы");
        }
      } finally {
        if (seq === loadSeq.current) setLoading(false);
      }
    },
    [analystId, query, urlFilter, semantic],
  );

  // Смена фильтров/аналитика — перезагрузка с первой страницы.
  // Семантический поиск стоит денег: ждём паузу в наборе и 3+ символа.
  useEffect(() => {
    if (!semantic) {
      load(1, false);
      return;
    }
    if (query.trim().length < SEMANTIC_MIN) {
      loadSeq.current += 1; // летящие ответы обычного поиска больше неактуальны
      setItems([]);
      setTotal(0);
      setLoaded(true);
      setHasMore(false);
      setLoading(false);
      return;
    }
    const timer = setTimeout(() => load(1, false), SEMANTIC_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [load, semantic]);

  useEffect(() => {
    if (!analystId) return;
    api<Analyst>(`/api/analysts/${analystId}`)
      .then(setAnalyst)
      .catch(() => setAnalyst(null));
  }, [analystId]);

  useEffect(() => {
    return () => {
      if (bulkTimer.current) clearInterval(bulkTimer.current);
    };
  }, []);

  const loadMore = useCallback(() => {
    if (!loading && hasMore) {
      load(page + 1, true);
    }
  }, [loading, hasMore, page, load]);

  // Актуальный loadMore — в ref: observer создаётся один раз.
  const loadMoreRef = useRef(loadMore);
  useEffect(() => {
    loadMoreRef.current = loadMore;
  }, [loadMore]);

  // Сентинел появляется только после первой загрузки — подписываемся
  // callback-ref'ом, а не эффектом на монтировании.
  const observerRef = useRef<IntersectionObserver | null>(null);
  const attachSentinel = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    sentinelRef.current = el;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          loadMoreRef.current();
        }
      },
      { rootMargin: "200px" }, // начинаем догрузку до конца списка
    );
    observer.observe(el);
    observerRef.current = observer;
  }, []);

  // Ручная проверка одного документа: запускаем и переходим к отчёту.
  const validateOne = async (documentId: number) => {
    setError("");
    try {
      await api(`/api/documents/${documentId}/validate`, { method: "POST" });
      navigate(`/documents/${documentId}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить проверку");
    }
  };

  // Массовая проверка всех документов аналитика (в фоне, с прогрессом).
  const validateAll = async () => {
    if (!analystId) return;
    setError("");
    try {
      await api(`/api/analysts/${analystId}/validate-all`, { method: "POST" });
      if (bulkTimer.current) clearInterval(bulkTimer.current);
      bulkTimer.current = setInterval(async () => {
        try {
          const status = await api<BulkValidationStatus>("/api/sync/bulk-validation");
          setBulk(status);
          if (!status.running) {
            if (bulkTimer.current) clearInterval(bulkTimer.current);
            bulkTimer.current = null;
            await load(1, false);
          }
        } catch {
          // статус недоступен — продолжаем опрос
        }
      }, 1000);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить проверку");
    }
  };

  // Смена фильтра: обновляем стейт и адрес (replace — история не засоряется).
  const applyFilters = (nextQuery: string, nextUrl: string) => {
    setQuery(nextQuery);
    setUrlFilter(nextUrl);
    const params = new URLSearchParams();
    if (nextQuery.trim()) params.set("q", nextQuery.trim());
    if (nextUrl.trim()) params.set("url", nextUrl.trim());
    setSearchParams(params, { replace: true });
  };

  return (
    <section>
      <div className="page-head">
        <div>
          <div className="muted">
            <Link to="/">← Аналитики</Link>
          </div>
          <h1>{analyst ? analyst.full_name : "Документы аналитика"}</h1>
        </div>
        <div className="actions">
          {bulk?.running ? (
            <span className="muted">
              Проверка {bulk.done} из {bulk.total}…
            </span>
          ) : (
            <button onClick={validateAll} disabled={loaded && total === 0}>
              Проверить все
            </button>
          )}
          <span className="muted">{loaded ? `Всего документов: ${total}` : ""}</span>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="search">
        <input
          placeholder="Поиск по названию…"
          value={query}
          onChange={(e) => applyFilters(e.target.value, urlFilter)}
        />
        <input
          placeholder="Поиск по ссылке…"
          value={urlFilter}
          disabled={semantic}
          title={semantic ? "Недоступно в режиме поиска по смыслу" : undefined}
          onChange={(e) => applyFilters(query, e.target.value)}
        />
        <label className="muted toggle" title="GLM ищет по смыслу, а не по словам">
          <input
            type="checkbox"
            checked={semantic}
            onChange={(e) => setSemantic(e.target.checked)}
          />
          по смыслу (ИИ)
        </label>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Название</th>
            <th>Статус проверки</th>
            <th>Создан</th>
            <th>Изменён</th>
            <th>Проверен</th>
            <th title="Заметка руководителя">📝</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((doc) => (
            <tr key={doc.id}>
              <td>
                <Link to={`/documents/${doc.id}`}>{doc.title}</Link>
                {doc.score != null && (
                  <span className="muted" title="Релевантность по мнению ИИ">
                    {" "}
                    {Math.round(doc.score * 100)}%
                  </span>
                )}
              </td>
              <td>
                <span className={`badge ${doc.validation_status}`}>
                  {STATUS_LABELS[doc.validation_status] ?? doc.validation_status}
                </span>
              </td>
              <td>{formatDate(doc.created_in_confluence_at)}</td>
              <td>{formatDate(doc.last_modified_in_confluence_at)}</td>
              <td>{formatDate(doc.last_validated_at)}</td>
              <td
                className="muted"
                title={doc.has_note ? "Есть заметка руководителя" : "Заметки нет"}
              >
                {doc.has_note ? "📝" : "—"}
              </td>
              <td>
                <button
                  className="secondary"
                  disabled={bulk?.running || doc.validation_status === "in_progress"}
                  onClick={() => validateOne(doc.id)}
                >
                  {doc.validation_status === "not_checked" ? "Проверить" : "Актуализировать"}
                </button>
              </td>
            </tr>
          ))}
          {!loading && loaded && items.length === 0 && (
            <tr>
              <td colSpan={7} className="empty">
                {semantic && query.trim().length < SEMANTIC_MIN
                  ? `Введите минимум ${SEMANTIC_MIN} символа — поиск по смыслу через ИИ`
                  : "Документы не найдены"}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {!loading && hasMore && <div ref={attachSentinel} className="empty" />}

      <div className="pagination">
        {loading && <span>Загрузка…</span>}
        {!loading && loaded && items.length > 0 && (
          <span>
            Показано {items.length} из {total}
          </span>
        )}
      </div>
    </section>
  );
}
