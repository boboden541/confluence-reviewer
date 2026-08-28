import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  AUTH_STORAGE_KEY,
  clearCredentials,
  hasCredentials,
  login,
  saveCredentials,
  UNAUTHORIZED_EVENT,
  api,
  type Analyst,
  type DocumentListItem,
  type DocumentPage,
  type SyncStatus,
} from "./api";
import AnalystsPage from "./pages/AnalystsPage";
import AnalystProfilePage from "./pages/AnalystProfilePage";
import AnalystStatsPage from "./pages/AnalystStatsPage";
import AiSettingsPage from "./pages/AiSettingsPage";
import CriteriaPage from "./pages/CriteriaPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReportPage from "./pages/ReportPage";
import TemplatePage from "./pages/TemplatePage";
import GlobalSearch from "./GlobalSearch";
import { on, startEvents, stopEvents } from "./events";

export function LoginGate() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      // Сначала проверяем учётку, потом сохраняем — иначе цикл перезагрузок.
      if (await login(username, password)) {
        saveCredentials(username, password);
        navigate(0);
      } else {
        setError("Неверный логин или пароль");
      }
    } catch {
      setError("Сервис недоступен, попробуйте ещё раз");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login" onSubmit={onSubmit}>
      <span className="logo-mark big">РТ</span>
      <h1>Ревью требований</h1>
      <p>Введите учётные данные сервиса</p>
      <input
        placeholder="Логин"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        autoFocus
      />
      <input
        placeholder="Пароль"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error && <div className="error">{error}</div>}
      <button type="submit" className="btn primary" disabled={busy}>
        {busy ? "Проверка…" : "Войти"}
      </button>
    </form>
  );
}

/** Ветка документов аналитика в сайдбаре (кэш на монтирование). */
interface DocBranch {
  docs: DocumentListItem[];
  total: number;
  loading: boolean;
  error: boolean;
}

// ширина сайдбара: тянем правый край, запоминаем выбор
const SIDEBAR_W_KEY = "cr-sidebar-w";
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 480;
const SIDEBAR_DEFAULT = 256;

function loadSidebarWidth(): number {
  const saved = Number(localStorage.getItem(SIDEBAR_W_KEY));
  return saved >= SIDEBAR_MIN && saved <= SIDEBAR_MAX ? saved : SIDEBAR_DEFAULT;
}

/** Сайдбар пространства: навигация + дерево «Аналитики → аналитики → последние
 *  5 документов» (стиль Confluence). Документы ветки грузятся лениво, при первом
 *  раскрытии. На узких экранах прячется off-canvas и открывается кнопкой «Меню». */
export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const location = useLocation();
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [groupOpen, setGroupOpen] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [branches, setBranches] = useState<Record<number, DocBranch>>({});
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [width, setWidth] = useState<number>(loadSidebarWidth);
  const [resizing, setResizing] = useState(false);
  const widthRef = useRef(width);
  // ветки, чьи документы уже грузятся/загружены: защита от повторных запросов
  const loadedRef = useRef<Set<number>>(new Set());

  const loadAnalysts = useCallback(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch(() => setAnalysts([]));
  }, []);

  useEffect(() => {
    loadAnalysts();
    api<SyncStatus>("/api/sync/status")
      .then(setSync)
      .catch(() => setSync(null));
  }, [loadAnalysts]);

  // документы ветки: грузим при первом раскрытии и кэшируем на монтирование;
  // после ошибки разрешаем повторить — id выкидываем из защиты
  const loadDocs = useCallback((analystId: number) => {
    if (loadedRef.current.has(analystId)) return;
    loadedRef.current.add(analystId);
    setBranches((prev) => ({
      ...prev,
      [analystId]: { docs: [], total: 0, loading: true, error: false },
    }));
    api<DocumentPage>(`/api/analysts/${analystId}/documents?page=1&page_size=5`)
      .then((page) =>
        setBranches((prev) => ({
          ...prev,
          [analystId]: { docs: page.items, total: page.total, loading: false, error: false },
        })),
      )
      .catch(() => {
        loadedRef.current.delete(analystId);
        setBranches((prev) => ({
          ...prev,
          [analystId]: { docs: [], total: 0, loading: false, error: true },
        }));
      });
  }, []);

  // живые события синхронизации (в т.ч. плановой по расписанию): статус в
  // футере — всегда актуальный; дерево аналитиков обновляем по завершении
  // реально наблюдаемого прогона (снимок при подключении — не повод
  // перезагружать ветки)
  useEffect(() => {
    let sawRun = false;
    return on("sync", (e) => {
      setSync(e);
      if (e.running) {
        sawRun = true;
        return;
      }
      if (!sawRun) return;
      sawRun = false;
      loadAnalysts();
      // раскрытые ветки: перечитаем последние документы аналитиков
      const loaded = [...loadedRef.current];
      loadedRef.current.clear();
      loaded.forEach((id) => loadDocs(id));
    });
  }, [loadAnalysts, loadDocs]);

  const toggleBranch = (analystId: number) => {
    if (!expanded.has(analystId)) loadDocs(analystId);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(analystId)) next.delete(analystId);
      else next.add(analystId);
      return next;
    });
  };

  const onAnalysts = location.pathname === "/";
  const onTemplate = location.pathname.startsWith("/template");
  const onAiConnection = location.pathname.startsWith("/ai-connection");
  const onCriteria = location.pathname.startsWith("/criteria");
  const activeAnalystId = Number(
    location.pathname.match(/^\/analysts\/(\d+)/)?.[1] ?? NaN,
  );
  const activeDocId = Number(
    location.pathname.match(/^\/documents\/(\d+)/)?.[1] ?? NaN,
  );
  // открыли страницу аналитика — раскрываем группу и его ветку в дереве
  useEffect(() => {
    if (Number.isNaN(activeAnalystId)) return;
    setGroupOpen(true);
    setExpanded((prev) => {
      if (prev.has(activeAnalystId)) return prev;
      const next = new Set(prev);
      next.add(activeAnalystId);
      return next;
    });
    loadDocs(activeAnalystId);
  }, [activeAnalystId, loadDocs]);

  // --- ресайз: тянем правый край сайдбара, ширина запоминается ---
  const applyWidth = (w: number) => {
    const clamped = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w));
    widthRef.current = clamped;
    setWidth(clamped);
  };
  const persistWidth = () => {
    localStorage.setItem(SIDEBAR_W_KEY, String(widthRef.current));
  };
  // Pointer capture держит события на ручке, даже если курсор ушёл дальше
  // (как у ресайзера панели просмотра), и заодно даёт тач-перетаскивание.
  const onResizeStart = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setResizing(true);
  };
  const onResizeMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (resizing) applyWidth(e.clientX);
  };
  const onResizeEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!resizing) return;
    setResizing(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    persistWidth();
  };
  // клавиатура: вправо — шире, влево — уже
  const onResizeKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      applyWidth(widthRef.current + 32);
      persistWidth();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      applyWidth(widthRef.current - 32);
      persistWidth();
    }
  };
  // во время перетаскивания не выделяем текст страницы
  useEffect(() => {
    document.body.classList.toggle("sidebar-resizing", resizing);
    return () => document.body.classList.remove("sidebar-resizing");
  }, [resizing]);

  return (
    <aside
      className={`sidebar${open ? " open" : ""}`}
      style={{ "--sidebar-w": `${width}px` } as React.CSSProperties}
    >
      <div className="space-head">
        <span className="space-icon">РТ</span>
        <span className="space-name">Ревью требований</span>
      </div>

      <div className="nav-label">Обзор</div>
      {/* группа: стрелка раскрывает дерево аналитиков, клик по названию —
          страница списка аналитиков */}
      <div className="nav-row">
        <button
          type="button"
          className="disc"
          onClick={() => setGroupOpen((v) => !v)}
          aria-expanded={groupOpen}
          aria-label="Список аналитиков в дереве"
        >
          {groupOpen ? "▾" : "▸"}
        </button>
        <Link
          to="/"
          className={`nav-item${onAnalysts ? " active" : ""}`}
          aria-current={onAnalysts ? "page" : undefined}
          onClick={onClose}
        >
          <span className="ic">👥</span> <span>Аналитики</span>
        </Link>
      </div>
      {groupOpen && (
        <div className="nav-tree">
          {analysts.length === 0 && <div className="nav-empty">аналитики не заведены</div>}
          {analysts.map((analyst) => {
            const branch = branches[analyst.id];
            const isOpen = expanded.has(analyst.id);
            return (
              <div className="nav-branch" key={analyst.id}>
                <div className="nav-row">
                  <button
                    type="button"
                    className="disc"
                    onClick={() => toggleBranch(analyst.id)}
                    aria-expanded={isOpen}
                    aria-label={`Документы аналитика ${analyst.full_name}`}
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                  <Link
                    to={`/analysts/${analyst.id}`}
                    className={`nav-item${analyst.id === activeAnalystId ? " active" : ""}`}
                    aria-current={analyst.id === activeAnalystId ? "page" : undefined}
                    onClick={onClose}
                  >
                    <span>{analyst.full_name}</span>
                  </Link>
                </div>
                {isOpen && (
                  <div className="nav-tree">
                    {!branch || branch.loading ? (
                      <div className="nav-empty">загрузка…</div>
                    ) : branch.error ? (
                      <div className="nav-empty">не удалось загрузить</div>
                    ) : branch.docs.length === 0 ? (
                      <div className="nav-empty">нет документов</div>
                    ) : (
                      <>
                        {branch.docs.map((doc) => (
                          <Link
                            key={doc.id}
                            to={`/documents/${doc.id}`}
                            className={`nav-doc${doc.id === activeDocId ? " active" : ""}`}
                            aria-current={doc.id === activeDocId ? "page" : undefined}
                            onClick={onClose}
                          >
                            {/* маркер-точка декоративный — из accessible name ссылки исключён */}
                            <span className="dot" aria-hidden="true">•</span>
                            <span className="t">{doc.title}</span>
                          </Link>
                        ))}
                        {branch.total > branch.docs.length && (
                          <Link
                            to={`/analysts/${analyst.id}/documents`}
                            className="nav-more"
                            onClick={onClose}
                          >
                            Показать остальные документы · {branch.total - branch.docs.length}
                          </Link>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="nav-label">Настройка</div>
      <Link
        to="/template"
        className={`nav-item${onTemplate ? " active" : ""}`}
        onClick={onClose}
      >
        <span className="ic">🧩</span> Шаблон требований
      </Link>
      <Link
        to="/criteria"
        className={`nav-item${onCriteria ? " active" : ""}`}
        onClick={onClose}
      >
        <span className="ic">✅</span> Критерии ИИ-проверок
      </Link>
      <Link
        to="/ai-connection"
        className={`nav-item${onAiConnection ? " active" : ""}`}
        onClick={onClose}
      >
        <span className="ic">⚙️</span> Подключение ИИ
      </Link>

      <div className="sync-status">
        {sync?.running
          ? "⟳ Идёт синхронизация…"
          : sync?.finished_at
            ? `⟳ Синхронизация: ${new Date(sync.finished_at).toLocaleString("ru-RU")}`
            : "⟳ Синхронизация ещё не запускалась"}
      </div>

      {/* правый край: тянуть — менять ширину, двойной клик — стандартная */}
      <div
        className="sidebar-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Изменить ширину сайдбара (стрелки ← →)"
        title="Потяните, чтобы изменить ширину; двойной клик — сброс"
        tabIndex={0}
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
        onKeyDown={onResizeKey}
        onDoubleClick={() => {
          applyWidth(SIDEBAR_DEFAULT);
          persistWidth();
        }}
      />
    </aside>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(hasCredentials());
  const [me, setMe] = useState("Р");
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();

  // переход по любой ссылке закрывает мобильное меню
  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  // SSE-стрим событий фоновых задач: итог проверок и синхронизаций
  // приходит на открытые страницы сам. Живёт, пока пользователь в сервисе.
  useEffect(() => {
    if (authed) startEvents();
    else stopEvents();
  }, [authed]);

  // буква аватара — первый символ логина
  useEffect(() => {
    try {
      const creds = localStorage.getItem(AUTH_STORAGE_KEY);
      if (creds) {
        const [user] = atob(creds).split(":");
        if (user) setMe(user[0].toUpperCase());
      }
    } catch {
      // повреждённые креды — останется буква по умолчанию
    }
  }, [authed]);

  if (!authed) {
    return <LoginGate />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <button
          type="button"
          className="topbar-burger"
          aria-label="Меню"
          aria-expanded={navOpen}
          onClick={() => setNavOpen((v) => !v)}
        >
          ☰
        </button>
        <Link to="/" className="topbar-logo">
          <span className="logo-mark">РТ</span>
          <span className="logo-text"> Ревью требований</span>
        </Link>
        <GlobalSearch />
        <button
          type="button"
          className="topbar-avatar"
          title="Выйти"
          aria-label="Выйти"
          onClick={() => {
            clearCredentials();
            setAuthed(false);
          }}
        >
          {me}
        </button>
      </header>
      <div className="layout">
        <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
        <div
          className={`sidebar-backdrop${navOpen ? " show" : ""}`}
          onClick={() => setNavOpen(false)}
        />
        <main className="content">
          <Routes>
            <Route path="/" element={<AnalystsPage />} />
            <Route path="/analysts/:analystId" element={<AnalystProfilePage />} />
            <Route path="/analysts/:analystId/documents" element={<DocumentsPage />} />
            <Route path="/analysts/:analystId/stats" element={<AnalystStatsPage />} />
            <Route path="/documents/:documentId" element={<ReportPage />} />
            <Route path="/template" element={<TemplatePage />} />
            <Route path="/criteria" element={<CriteriaPage />} />
            <Route path="/ai-connection" element={<AiSettingsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
