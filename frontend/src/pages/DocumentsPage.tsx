import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Analyst,
  type BulkValidationStatus,
  type DocumentListItem,
  type DocumentPage,
  type ValidationStatus,
} from "../api";
import StatusBadge from "../StatusBadge";
import DocumentReport from "../DocumentReport";
import ValidationDialog from "../ValidationDialog";
import { on } from "../events";
import { Breadcrumbs } from "../Breadcrumbs";

const PAGE_SIZE = 20;
const SEMANTIC_MIN = 3; // минимум символов для запроса к ИИ
const SEMANTIC_DEBOUNCE_MS = 800; // не дёргаем ИИ на каждое нажатие
const BADGE_HOLD_MS = 4000; // сколько после финала висят лозенги прогона

// Ширина панели просмотра: тянется за ручку на левом краю, запоминается
const DRAWER_DEFAULT_W = 640;
const DRAWER_MIN_W = 380;
const clampDrawerW = (w: number) =>
  Math.min(Math.max(w, DRAWER_MIN_W), Math.max(DRAWER_MIN_W, window.innerWidth - 80));

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** Дата+время последней синхронизации для подзаголовка: «31.08, 10:15».
 * Бэкенд хранит наивный UTC — без суффикса Z браузер спарсит его как
 * локальное время и сдвинет на часовой пояс пользователя. */
function formatSyncedAt(value: string): string {
  const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(utc).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DocumentsPage() {
  const { analystId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [items, setItems] = useState<DocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  // фильтры живут в адресе (?q=…&url=…&created_from=…&created_to=…):
  // вернувшись кнопкой «Назад», пользователь попадает в тот же результат поиска
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [urlFilter, setUrlFilter] = useState(() => searchParams.get("url") ?? "");
  // период по дате создания в Confluence, границы включительны (YYYY-MM-DD)
  const [createdFrom, setCreatedFrom] = useState(() => searchParams.get("created_from") ?? "");
  const [createdTo, setCreatedTo] = useState(() => searchParams.get("created_to") ?? "");
  const [semantic, setSemantic] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bulk, setBulk] = useState<BulkValidationStatus | null>(null);
  // синхронизация аналитика из шапки: состояние прогона и его итог.
  // Итог живёт в собственных состояниях, а не в error: load() по успехе
  // чистит error, и сообщение о сбое синхронизации жило бы ровно один
  // запрос перезагрузки списка.
  const [syncing, setSyncing] = useState(false);
  // текущий проверяемый документ и прогресс bulk (для спиннера на строке)
  const [runningDocId, setRunningDocId] = useState<number | null>(null);
  const [, setBulkCurrent] = useState<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 });
  // очередь запущенного прогона и итоги по документам (из bulk-событий)
  const [bulkQueue, setBulkQueue] = useState<number[] | null>(null);
  const [bulkResults, setBulkResults] = useState<Record<number, { status: ValidationStatus | null; unchanged: boolean }>>({});
  const [info, setInfo] = useState("");
  const [syncError, setSyncError] = useState("");
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // защита от устаревших ответов: сменили режим/фильтр — старый ответ
  // не должен затирать новое состояние списка
  const loadSeq = useRef(0);
  // «наблюдали запуск прогона»: флаги в ref, а не в замыкании эффекта —
  // подписка пересоздаётся на каждый символ в поиске (load меняет
  // идентичность), и замыкание начиналось бы заново, теряя запуск
  const sawBulkRunRef = useRef(false);
  const sawSyncRunRef = useRef(false);
  // лозенги прогона («в очереди», «без изменений») гаснут через пару секунд
  // после его финала: для мгновенных идемпотентных проверок это единственная
  // видимая индикация, но вечно висеть на строках они не должны
  const badgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (badgeTimerRef.current) clearTimeout(badgeTimerRef.current);
  }, []);

  // Выбранные для проверки документы (чекбоксы в таблице). Выделение
  // живёт до запуска проверки или смены фильтра/аналитика.
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  // «Актуализировать» из строки — перевалидировать безусловно (force)
  const [dialogForce, setDialogForce] = useState(false);

  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllLoaded = (on: boolean) => {
    setSelected((on ? new Set(items.map((doc) => doc.id)) : new Set()));
  };

  // смена фильтра или аналитика — выделение больше не относится к списку
  useEffect(() => {
    setSelected(new Set());
  }, [analystId, query, urlFilter, createdFrom, createdTo]);

  const allLoadedSelected = items.length > 0 && items.every((doc) => selected.has(doc.id));
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selected.size > 0 && !allLoadedSelected;
    }
  }, [selected, allLoadedSelected]);

  // Быстрый просмотр документа в панели справа: ?doc=<id> в адресе —
  // панель переживает F5, а кнопка «назад» браузера её закрывает.
  const docParam = searchParams.get("doc");
  const drawerDocId = docParam && /^\d+$/.test(docParam) ? Number(docParam) : null;

  const openDoc = (id: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("doc", String(id));
    setSearchParams(params);
  };

  const closeDrawer = () => {
    const params = new URLSearchParams(searchParams);
    params.delete("doc");
    setSearchParams(params, { replace: true });
  };

  // ширина панели: сохранённая пользователем или стандартная, подогнанная под экран
  const [drawerW, setDrawerW] = useState(() => {
    const saved = Number(localStorage.getItem("cr-drawer-w"));
    return Number.isFinite(saved) && saved >= DRAWER_MIN_W ? clampDrawerW(saved) : DRAWER_DEFAULT_W;
  });
  const [resizing, setResizing] = useState(false);

  // во время перетаскивания не выделяется текст страницы под панелью
  useEffect(() => {
    if (!resizing) return;
    document.body.classList.add("drawer-resizing");
    return () => document.body.classList.remove("drawer-resizing");
  }, [resizing]);

  // окно стало уже — панель не должна вылезать за экран
  useEffect(() => {
    const clamp = () => setDrawerW((w) => clampDrawerW(w));
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, []);

  // выбранная ширина переживает перезагрузку
  useEffect(() => {
    localStorage.setItem("cr-drawer-w", String(drawerW));
  }, [drawerW]);

  // Esc закрывает панель; если поверх открыт модальный диалог (настройки
  // проверки из панели) — Esc закрывает его, а не панель под ним
  useEffect(() => {
    if (drawerDocId == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.querySelector(".overlay")) return;
      closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerDocId, searchParams]);

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
          if (createdFrom) params.set("created_from", createdFrom);
          if (createdTo) params.set("created_to", createdTo);
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
    [analystId, query, urlFilter, createdFrom, createdTo, semantic],
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

  const loadAnalyst = useCallback(async () => {
    if (!analystId) return;
    try {
      setAnalyst(await api<Analyst>(`/api/analysts/${analystId}`));
    } catch {
      setAnalyst(null);
    }
  }, [analystId]);

  useEffect(() => {
    loadAnalyst();
  }, [loadAnalyst]);

  // сменили аналитика — итоги его прошлой синхронизации неактуальны
  useEffect(() => {
    setInfo("");
    setSyncError("");
  }, [analystId]);

  // Прогресс и завершение проверки приходят событиями (SSE): строка «k из N…»
  // живёт на событиях bulk, список обновляется по финалу наблюдаемого прогона.
  // Синхронизация (кнопкой из шапки, из другой вкладки или плановая) тоже
  // меняет список — обновляем список, карточку аналитика и показываем итог.
  useEffect(() => {
    const offBulk = on("bulk", (e) => {
      setBulk(e.running ? e : null);
      setBulkCurrent({ running: e.running, done: e.done, total: e.total });
      // текущий документ прогона и итог по завершённому
      const cd = e.current_document;
      setRunningDocId(e.running && cd ? cd.document_id : null);
      const ld = e.last_document ?? null;
      if (ld) {
        setBulkResults((prev) => ({
          ...prev,
          [ld.document_id]: { status: ld.status, unchanged: ld.unchanged },
        }));
      }
      if (e.running) {
        // застали прогон с начала — итоги прошлого неактуальны
        if (e.done === 0) setBulkResults({});
        sawBulkRunRef.current = true;
        return;
      }
      if (sawBulkRunRef.current) {
        sawBulkRunRef.current = false;
        void load(1, false);
        if (badgeTimerRef.current) clearTimeout(badgeTimerRef.current);
        badgeTimerRef.current = setTimeout(() => {
          setBulkQueue(null);
          setBulkResults({});
        }, BADGE_HOLD_MS);
      }
    });
    // какой документ проверяется прямо сейчас — спиннер на его строке
    const offValidation = on("validation", (e) => {
      setRunningDocId(e.status === "running" ? e.document_id : null);
    });
    const offSync = on("sync", (e) => {
      if (e.running) {
        sawSyncRunRef.current = true;
        setSyncing(true);
        return;
      }
      setSyncing(false);
      if (!sawSyncRunRef.current) return;
      sawSyncRunRef.current = false;
      void load(1, false);
      void loadAnalyst(); // обновить дату последней синхронизации
      // итог — только по этому аналитику: массовый прогон трогает и других
      const mine = (e.last_results ?? []).find((r) => r.analyst_id === Number(analystId));
      if (!mine) return;
      if (mine.error) {
        setSyncError(`Синхронизация завершилась с ошибкой: ${mine.error}`);
        setInfo("");
      } else {
        setSyncError("");
        setInfo(`Синхронизация завершена: новых ${mine.created}, обновлено ${mine.updated}`);
      }
    });
    return () => {
      offBulk();
      offValidation();
      offSync();
    };
  }, [load, loadAnalyst, analystId]);

  const syncAnalyst = async () => {
    if (!analystId || syncing) return;
    // busy сразу: повторный клик до ответа 202 не запустит второй прогон
    // (бэкенд ответил бы 409), а финал SSE не «воскресит» занятость
    setSyncing(true);
    setInfo("");
    setSyncError("");
    try {
      await api(`/api/analysts/${analystId}/sync`, { method: "POST" });
    } catch (exc) {
      setSyncing(false);
      setSyncError(
        exc instanceof ApiError ? exc.message : "Не удалось запустить синхронизацию",
      );
    }
  };

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

  // Ручка на левом краю панели: влево — шире, вправо — уже.
  // Pointer capture держит события на ручке, даже если курсор ушёл дальше.
  const onResizeStart = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setResizing(true);
  };

  const onResizeMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (resizing) setDrawerW(clampDrawerW(window.innerWidth - e.clientX));
  };

  const onResizeEnd = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizing) return;
    setResizing(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  const onResizeKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      setDrawerW((w) => clampDrawerW(w + 32));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      setDrawerW((w) => clampDrawerW(w - 32));
    }
  };

  // Проверка выбранных документов: сначала диалог настроек (шаблон + промт ИИ).
  const openBulkDialog = () => {
    setDialogForce(false);
    setDialogOpen(true);
  };

  // Кнопка в строке документа: тот же диалог на один документ.
  // Уже проверенный документ «актуализируем» — запускаем с force.
  const openSingleDialog = (doc: DocumentListItem) => {
    setSelected(new Set([doc.id]));
    setDialogForce(doc.validation_status !== "not_checked");
    setDialogOpen(true);
  };

  // Диалог отработал: проверка ушла в фон (итог придёт событием bulk),
  // выделение больше не нужно
  const handleLaunched = () => {
    setDialogOpen(false);
    // таймер прошлого прогона не должен погасить лозенги только что
    // запущенного (перезапуск сразу после финала предыдущего)
    if (badgeTimerRef.current) clearTimeout(badgeTimerRef.current);
    // очередь прогона — для статусов «в очереди/проверяется» на строках
    setBulkQueue([...selected]);
    setSelected(new Set());
  };

  // Смена фильтра: обновляем стейт и адрес (replace — история не засоряется).
  // Открытую панель просмотра (doc=) сохраняем.
  const applyFilters = (
    nextQuery: string,
    nextUrl: string,
    nextCreatedFrom: string,
    nextCreatedTo: string,
  ) => {
    setQuery(nextQuery);
    setUrlFilter(nextUrl);
    setCreatedFrom(nextCreatedFrom);
    setCreatedTo(nextCreatedTo);
    const params = new URLSearchParams();
    if (nextQuery.trim()) params.set("q", nextQuery.trim());
    if (nextUrl.trim()) params.set("url", nextUrl.trim());
    if (nextCreatedFrom) params.set("created_from", nextCreatedFrom);
    if (nextCreatedTo) params.set("created_to", nextCreatedTo);
    if (docParam) params.set("doc", docParam);
    setSearchParams(params, { replace: true });
  };

  return (
    <section className="page">
      <Breadcrumbs
        items={[
          { label: "Кластеры", to: "/clusters" },
          ...(analyst?.cluster_name
            ? [{ label: analyst.cluster_name, to: `/clusters/${analyst.cluster_id}` }]
            : analyst
              ? [{ label: "Без команды" }]
              : []),
          ...(analyst?.team_name
            ? [{ label: analyst.team_name, to: `/teams/${analyst.team_id}` }]
            : []),
          ...(analyst
            ? [{ label: analyst.full_name, to: `/analysts/${analyst.id}` }]
            : []),
          { label: "вид: документы" },
        ]}
      />
      <div className="page-head">
        <div>
          <h1 className="page-title">
            <span className="title-icon">📄</span>
            {analyst ? analyst.full_name : "Документы аналитика"}
          </h1>
          <div className="page-meta">
            <span className="muted">
              {loaded ? `Всего документов: ${total}` : ""}
              {loaded && analyst?.last_synced_at
                ? ` · Синхронизировано: ${formatSyncedAt(analyst.last_synced_at)}`
                : ""}
            </span>
          </div>
        </div>
        <div className="head-actions">
          <button
            className="btn subtle"
            onClick={syncAnalyst}
            disabled={syncing}
            title="Подтянуть новые и изменённые страницы аналитика из Confluence"
          >
            <span aria-hidden="true">⟳</span> {syncing ? "Синхронизация…" : "Синхронизировать"}
          </button>
          <button
            className="btn primary"
            onClick={openBulkDialog}
            disabled={syncing || selected.size === 0}
            title="Отметьте документы чекбоксами — настройки проверки спросят шаблон и промт ИИ"
          >
            <span aria-hidden="true">▶</span> Проверить выбранные
            {selected.size > 0 ? ` (${selected.size})` : ""}
          </button>
        </div>
      </div>

      {selected.size > 0 && (
        <div className="selection-bar">
          <span className="count">Выбрано: {selected.size}</span>
          <button className="btn ghost" onClick={() => selectAllLoaded(true)}>
            Выбрать все загруженные
          </button>
          <button className="btn ghost" onClick={() => setSelected(new Set())}>
            Снять выделение
          </button>
        </div>
      )}

      {error && <div className="alert error">{error}</div>}
      {syncError && <div className="alert error">{syncError}</div>}
      {info && <div className="alert ok">{info}</div>}

      {bulk?.running && (
        <div className="progress-line">
          <span>
            Проверка {bulk.done} из {bulk.total}…
          </span>
          <div className="progress-bar">
            <div style={{ width: `${bulk.total ? Math.round((bulk.done / bulk.total) * 100) : 0}%` }} />
          </div>
        </div>
      )}

      <div className="form-row">
        <span className="field">
          <label htmlFor="doc-title-search">Название</label>
          <input
            id="doc-title-search"
            className="text-input"
            placeholder="Поиск по названию…"
            style={{ width: "260px" }}
            value={query}
            onChange={(e) => applyFilters(e.target.value, urlFilter, createdFrom, createdTo)}
          />
        </span>
        <span className="field">
          <label htmlFor="doc-url-search">Ссылка</label>
          <input
            id="doc-url-search"
            className="text-input"
            placeholder="Поиск по ссылке…"
            style={{ width: "220px" }}
            value={urlFilter}
            disabled={semantic}
            title={semantic ? "Недоступно в режиме поиска по смыслу" : undefined}
            onChange={(e) => applyFilters(query, e.target.value, createdFrom, createdTo)}
          />
        </span>
        <span className="field">
          <label htmlFor="doc-created-from-search">Создан с</label>
          <input
            id="doc-created-from-search"
            type="date"
            className="text-input"
            style={{ width: "150px" }}
            value={createdFrom}
            max={createdTo || undefined}
            disabled={semantic}
            title={semantic ? "Недоступно в режиме поиска по смыслу" : undefined}
            onChange={(e) => applyFilters(query, urlFilter, e.target.value, createdTo)}
          />
        </span>
        <span className="field">
          <label htmlFor="doc-created-to-search">по</label>
          <input
            id="doc-created-to-search"
            type="date"
            className="text-input"
            style={{ width: "150px" }}
            value={createdTo}
            min={createdFrom || undefined}
            disabled={semantic}
            title={semantic ? "Недоступно в режиме поиска по смыслу" : undefined}
            onChange={(e) => applyFilters(query, urlFilter, createdFrom, e.target.value)}
          />
        </span>
        <label
          className="checkbox-label"
          style={{ marginBottom: "6px" }}
          title="GLM ищет по смыслу, а не по словам"
        >
          <input
            type="checkbox"
            checked={semantic}
            onChange={(e) => setSemantic(e.target.checked)}
          />
          по смыслу <span className="lozenge new">ИИ</span>
        </label>
      </div>

      <div className="table-wrap">
      <table className="cf">
        <thead>
          <tr>
            <th className="cb-cell">
              <input
                ref={selectAllRef}
                type="checkbox"
                className="cb"
                checked={allLoadedSelected}
                onChange={(e) => selectAllLoaded(e.target.checked)}
                aria-label="Выбрать все загруженные документы"
                title="Выбрать все загруженные по фильтру"
              />
            </th>
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
          {items.map((doc) => {
            // состояние строки в текущем прогоне: итог > проверяется > в очереди
            const runState = bulkResults[doc.id]
              ? "done"
              : runningDocId === doc.id
                ? "processing"
                : bulkQueue?.includes(doc.id)
                  ? "queued"
                  : null;
            return (
            <tr
              key={doc.id}
              className={
                runState === "processing" ? "processing" : runState === "queued" ? "queued" : undefined
              }
            >
              <td className="cb-cell">
                <input
                  type="checkbox"
                  className="cb"
                  checked={selected.has(doc.id)}
                  onChange={() => toggleSelected(doc.id)}
                  aria-label={`Выбрать документ: ${doc.title}`}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="link doc-link"
                  title="Открыть панель просмотра"
                  onClick={() => openDoc(doc.id)}
                >
                  {doc.title}
                </button>
                {doc.score != null && (
                  <span className="muted" title="Релевантность по мнению ИИ">
                    {" "}
                    {Math.round(doc.score * 100)}%
                  </span>
                )}
              </td>
              <td>
                {runState === "processing" ? (
                  // проверяемый прямо сейчас — канонический статус прогона
                  <StatusBadge status="in_progress" />
                ) : runState === "queued" ? (
                  // ожидает своего хода — вместо статуса прошлой проверки
                  <span className="lozenge default">в очереди</span>
                ) : runState === "done" ? (
                  // свой ход прошёл: один итог — свежий статус из bulk-события
                  bulkResults[doc.id].unchanged ? (
                    <span className="lozenge default">без изменений</span>
                  ) : (
                    <StatusBadge
                      status={bulkResults[doc.id].status ?? doc.validation_status}
                    />
                  )
                ) : (
                  <StatusBadge status={doc.validation_status} />
                )}
              </td>
              <td className="cell-subtle">{formatDate(doc.created_in_confluence_at)}</td>
              <td className="cell-subtle">{formatDate(doc.last_modified_in_confluence_at)}</td>
              <td className="cell-subtle">{formatDate(doc.last_validated_at)}</td>
              <td
                title={doc.has_note ? "Есть заметка руководителя" : "Заметки нет"}
              >
                {doc.has_note ? "📝" : "—"}
              </td>
              <td className="actions-cell">
                {runState === "processing" || doc.validation_status === "in_progress" ? (
                  <span className="spinner" title="Проверяется…" />
                ) : (
                  <button
                    className="btn small subtle"
                    onClick={() => openSingleDialog(doc)}
                  >
                    {doc.validation_status === "not_checked" ? (
                      <>
                        <span aria-hidden="true">▶</span> Проверить
                      </>
                    ) : (
                      <>
                        <span aria-hidden="true">⟳</span> Актуализировать
                      </>
                    )}
                  </button>
                )}
              </td>
            </tr>
            );
          })}
          {!loading && loaded && items.length === 0 && (
            <tr>
              <td colSpan={8} className="table-empty">
                {semantic && query.trim().length < SEMANTIC_MIN
                  ? `Введите минимум ${SEMANTIC_MIN} символа — поиск по смыслу через ИИ`
                  : // вину на период возлагаем, только если других фильтров нет:
                    // пустота может быть из-за опечатки в «Названии»/«Ссылке»
                    !semantic && (createdFrom || createdTo) && !query.trim() && !urlFilter.trim()
                    ? "За выбранный период документов нет"
                    : "Документы не найдены"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>

      {!loading && hasMore && <div ref={attachSentinel} className="sentinel" />}

      <div className="pagination">
        {loading && <span className="muted">Загрузка…</span>}
        {!loading && loaded && items.length > 0 && (
          <span className="muted">
            Показано {items.length} из {total}
          </span>
        )}
      </div>

      {dialogOpen && selected.size > 0 && (
        <ValidationDialog
          documentIds={[...selected]}
          force={dialogForce}
          onClose={() => setDialogOpen(false)}
          onLaunched={handleLaunched}
        />
      )}

      {drawerDocId != null && (
        <>
          <div className="drawer-backdrop show" onClick={closeDrawer} />
          <aside
            className={resizing ? "drawer resizing" : "drawer"}
            role="dialog"
            aria-label="Просмотр документа"
            style={{ width: drawerW }}
          >
            {/* ручка на левом краю: панель можно сделать шире или уже */}
            <div
              className="drawer-resize"
              role="separator"
              aria-orientation="vertical"
              aria-label="Изменить ширину панели просмотра (стрелки ← →)"
              tabIndex={0}
              onPointerDown={onResizeStart}
              onPointerMove={onResizeMove}
              onPointerUp={onResizeEnd}
              onPointerCancel={onResizeEnd}
              onKeyDown={onResizeKey}
              onDoubleClick={() => setDrawerW(clampDrawerW(DRAWER_DEFAULT_W))}
            />
            <div className="drawer-body">
              <DocumentReport documentId={drawerDocId} embedded onClose={closeDrawer} />
            </div>
          </aside>
        </>
      )}
    </section>
  );
}
