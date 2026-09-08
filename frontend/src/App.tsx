import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  hasCredentials,
  login,
  UNAUTHORIZED_EVENT,
  api,
  type Analyst,
  type Cluster,
  type DocumentListItem,
  type DocumentPage,
  type SyncStatus,
  ORG_CHANGED_EVENT,
} from "./api";
import { clusterColor } from "./orgUi";
import ClustersPage from "./pages/ClustersPage";
import ClusterPage from "./pages/ClusterPage";
import TeamPage from "./pages/TeamPage";
import AnalystsPage from "./pages/AnalystsPage";
import AnalystProfilePage from "./pages/AnalystProfilePage";
import HomePage from "./pages/HomePage";
import RequestsPage from "./pages/RequestsPage";
import RolesPage from "./pages/RolesPage";
import AnalystStatsPage from "./pages/AnalystStatsPage";
import AiSettingsPage from "./pages/AiSettingsPage";
import CriteriaPage from "./pages/CriteriaPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReportPage from "./pages/ReportPage";
import TemplatePage from "./pages/TemplatePage";
import TemplatesPage from "./pages/TemplatesPage";
import GlobalSearch from "./GlobalSearch";
import { on, startEvents, stopEvents } from "./events";
import { fetchMe, loginWithToken, logout as authLogout, reapply, type Me } from "./auth";
import { UserContext, useCan, useMe } from "./userContext";

export function LoginGate({
  onAuthenticated,
}: {
  onAuthenticated: (me: Me) => void;
}) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"password" | "token">("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [rejected, setRejected] = useState(false);
  const [busy, setBusy] = useState(false);

  const onPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      // Сначала проверяем учётку, потом сохраняем — иначе цикл перезагрузок.
      if (await login(username, password)) {
        const me = await fetchMe();
        onAuthenticated(me);
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

  const onTokenSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const outcome = await loginWithToken(token);
      if (outcome.kind === "session") {
        onAuthenticated(outcome.me);
        navigate(0);
      } else if (outcome.kind === "pending") {
        setPending(outcome.fullName);
      } else if (outcome.kind === "rejected") {
        setRejected(true);
      } else {
        setError(outcome.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const onReapply = async () => {
    setBusy(true);
    const ok = await reapply(token);
    setBusy(false);
    if (ok) {
      setRejected(false);
      setPending("заявка подана повторно");
    } else {
      setError("Не удалось подать заявку повторно");
    }
  };

  if (pending) {
    return (
      <div className="login">
        <span className="logo-mark big">РТ</span>
        <h1>Заявка отправлена</h1>
        <p>
          Мы проверили ваш токен в Confluence и передали заявку администратору
          сервиса{pending ? ` (${pending})` : ""}. Как только её одобрят — войдите тем же
          токеном.
        </p>
        <button type="button" className="btn primary" onClick={() => { setPending(null); setToken(""); }}>
          Вернуться ко входу
        </button>
      </div>
    );
  }

  if (rejected) {
    return (
      <div className="login">
        <span className="logo-mark big">РТ</span>
        <h1>Заявка отклонена</h1>
        <p>
          Если считаете, что доступ вам нужен, — свяжитесь с администратором
          сервиса и подайте заявку повторно.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
          <button type="button" className="btn primary" onClick={onReapply} disabled={busy}>
            Подать заявку повторно
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setRejected(false);
              setToken("");
            }}
          >
            Вернуться ко входу
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
    );
  }

  return (
    <form
      className="login"
      onSubmit={(e) => {
        e.preventDefault();
        if (mode === "password") void onPasswordSubmit(e);
        else void onTokenSubmit(e);
      }}
    >
      <span className="logo-mark big">РТ</span>
      <h1>Ревью требований</h1>
      <p>Вход в сервис</p>

      <div className="login-tabs">
        <button
          type="button"
          className={mode === "password" ? "active" : ""}
          onClick={() => setMode("password")}
        >
          Логин и пароль
        </button>
        <button
          type="button"
          className={mode === "token" ? "active" : ""}
          onClick={() => setMode("token")}
        >
          Токен Confluence
        </button>
      </div>

      {mode === "password" ? (
        <>
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
        </>
      ) : (
        <>
          <input
            placeholder="Персональный токен Confluence"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoFocus
          />
          <p className="login-hint">
            Токен создаётся в Confluence: Профиль → Настройки → Личные токены доступа.
            Мы прочитаем из него ваше имя, почту и логин и создадим заявку на доступ.
          </p>
        </>
      )}

      {error && <div className="error">{error}</div>}
      <button type="submit" className="btn primary" disabled={busy}>
        {busy ? "Проверка…" : mode === "password" ? "Войти" : "Продолжить"}
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

/** Ветка аналитика в дереве: строка с ФИО + лениво раскрываемые последние
 *  документы. Общая для команд и группы «Без команды». */
function AnalystBranch({
  analyst,
  isActive,
  isOpen,
  branch,
  activeDocId,
  onToggle,
  onClose,
}: {
  analyst: Analyst;
  isActive: boolean;
  isOpen: boolean;
  branch: DocBranch | undefined;
  activeDocId: number;
  onToggle: () => void;
  onClose: () => void;
}) {
  return (
    <div className="nav-branch">
      <div className="nav-row">
        <button
          type="button"
          className="disc"
          onClick={onToggle}
          aria-expanded={isOpen}
          aria-label={`Документы аналитика ${analyst.full_name}`}
        >
          {isOpen ? "▾" : "▸"}
        </button>
        <Link
          to={`/analysts/${analyst.id}`}
          className={`nav-item${isActive ? " active" : ""}`}
          aria-current={isActive ? "page" : undefined}
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
                <Link to={`/analysts/${analyst.id}/documents`} className="nav-more" onClick={onClose}>
                  Показать остальные документы · {branch.total - branch.docs.length}
                </Link>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
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

/** Сайдбар пространства: навигация + дерево структуры «Кластеры → команды →
 *  аналитики → последние 5 документов» (плюс ветка «Без команды»).
 *  Документы ветки грузятся лениво, при первом раскрытии. На узких экранах
 *  прячется off-canvas и открывается кнопкой «Меню». */
export function Sidebar({
  open,
  onClose,
  onLogout,
}: {
  open: boolean;
  onClose: () => void;
  onLogout: () => void;
}) {
  const location = useLocation();
  const me = useMe();
  const canUser = useCan();
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [structureOpen, setStructureOpen] = useState(true);
  const [openClusters, setOpenClusters] = useState<Set<number>>(new Set());
  const [openTeams, setOpenTeams] = useState<Set<number>>(new Set());
  const [noTeamOpen, setNoTeamOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [branches, setBranches] = useState<Record<number, DocBranch>>({});
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [structureError, setStructureError] = useState(false);
  // структура загружена хотя бы раз: эффекты автоподкрытия реагируют только
  // на первый приход данных, а не на каждый рефреш (иначе свёрнутое
  // пользователем раскрывается обратно после синхронизации)
  const [structureLoaded, setStructureLoaded] = useState(false);
  const [width, setWidth] = useState<number>(loadSidebarWidth);
  const [resizing, setResizing] = useState(false);
  const widthRef = useRef(width);
  // ветки, чьи документы уже грузятся/загружены: защита от повторных запросов
  const loadedRef = useRef<Set<number>>(new Set());

  const clustersRef = useRef<Cluster[]>([]);
  const analystsRef = useRef<Analyst[]>([]);
  const loadStructure = useCallback(() => {
    // ошибка структуры не глотается молча: без кластеров дерево пустое и
    // пользователи команд исчезают из навигации — показываем сбой явно
    Promise.all([api<Cluster[]>("/api/clusters"), api<Analyst[]>("/api/analysts")])
      .then(([clusterList, analystList]) => {
        clustersRef.current = clusterList;
        analystsRef.current = analystList;
        setClusters(clusterList);
        setAnalysts(analystList);
        setStructureError(false);
        setStructureLoaded(true);
      })
      .catch(() => setStructureError(true));
  }, []);

  useEffect(() => {
    loadStructure();
    api<SyncStatus>("/api/sync/status")
      .then(setSync)
      .catch(() => setSync(null));
  }, [loadStructure]);

  // мутации структуры (кластеры/команды/состав) со своих страниц обновляют
  // дерево через событие org-changed — без перезагрузки страницы
  useEffect(() => {
    window.addEventListener(ORG_CHANGED_EVENT, loadStructure);
    return () => window.removeEventListener(ORG_CHANGED_EVENT, loadStructure);
  }, [loadStructure]);

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
  // футере — всегда актуальный; дерево структуры обновляем по завершении
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
      loadStructure();
      // раскрытые ветки: перечитаем последние документы аналитиков
      const loaded = [...loadedRef.current];
      loadedRef.current.clear();
      loaded.forEach((id) => loadDocs(id));
    });
  }, [loadStructure, loadDocs]);

  const toggleBranch = (analystId: number) => {
    if (!expanded.has(analystId)) loadDocs(analystId);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(analystId)) next.delete(analystId);
      else next.add(analystId);
      return next;
    });
  };

  const toggleCluster = (clusterId: number) => {
    setOpenClusters((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) next.delete(clusterId);
      else next.add(clusterId);
      return next;
    });
  };

  const toggleTeam = (teamId: number) => {
    setOpenTeams((prev) => {
      const next = new Set(prev);
      if (next.has(teamId)) next.delete(teamId);
      else next.add(teamId);
      return next;
    });
  };

  const onHome = location.pathname === "/";
  const onClustersMap = location.pathname === "/clusters";
  const onAllAnalysts = location.pathname.startsWith("/analysts");
  const onTemplate = location.pathname.startsWith("/template");
  const onAiConnection = location.pathname.startsWith("/ai-connection");
  const onCriteria = location.pathname.startsWith("/criteria");
  const activeClusterId = Number(location.pathname.match(/^\/clusters\/(\d+)/)?.[1] ?? NaN);
  const activeTeamId = Number(location.pathname.match(/^\/teams\/(\d+)/)?.[1] ?? NaN);
  const activeAnalystId = Number(
    location.pathname.match(/^\/analysts\/(\d+)/)?.[1] ?? NaN,
  );
  const activeDocId = Number(
    location.pathname.match(/^\/documents\/(\d+)/)?.[1] ?? NaN,
  );
  // аналитики вне команд — ветка «Без команды» наравне с кластерами
  const freeAnalysts = useMemo(
    () => analysts.filter((a) => a.team_id === null),
    [analysts],
  );
  // участники команд: карта для дерева, чтобы не фильтровать всех аналитиков
  // на каждую команду в каждом рендере
  const membersByTeam = useMemo(() => {
    const map = new Map<number, Analyst[]>();
    analysts.forEach((a) => {
      if (a.team_id == null) return;
      const list = map.get(a.team_id);
      if (list) list.push(a);
      else map.set(a.team_id, [a]);
    });
    return map;
  }, [analysts]);
  // открыли страницу кластера/команды — раскрываем цепочку до неё; зависим
  // от факта первой загрузки, а не самих данных (рефресы после sync не
  // переоткрывают свёрнутое пользователем)
  useEffect(() => {
    if (!structureLoaded) return;
    if (Number.isNaN(activeClusterId) && Number.isNaN(activeTeamId)) return;
    setStructureOpen(true);
    if (!Number.isNaN(activeClusterId)) {
      setOpenClusters((prev) => new Set(prev).add(activeClusterId));
    }
    if (!Number.isNaN(activeTeamId)) {
      setOpenTeams((prev) => new Set(prev).add(activeTeamId));
      // кластер команды раскрываем по данным, уже пришедшим к этому моменту
      const owner = clustersRef.current.find((c) => c.teams.some((t) => t.id === activeTeamId));
      if (owner) setOpenClusters((prev) => new Set(prev).add(owner.id));
    }
  }, [activeClusterId, activeTeamId, structureLoaded]);

  // открыли страницу аналитика — раскрываем его кластер/команду (или «Без
  // команды») и ветку документов в дереве
  useEffect(() => {
    if (!structureLoaded) return;
    if (Number.isNaN(activeAnalystId)) return;
    setStructureOpen(true);
    const analyst = analystsRef.current.find((a) => a.id === activeAnalystId);
    if (analyst?.team_id != null) {
      setOpenTeams((prev) => new Set(prev).add(analyst.team_id as number));
      if (analyst.cluster_id != null) {
        setOpenClusters((prev) => new Set(prev).add(analyst.cluster_id as number));
      }
    } else if (analyst) {
      setNoTeamOpen(true);
    }
    setExpanded((prev) => {
      if (prev.has(activeAnalystId)) return prev;
      const next = new Set(prev);
      next.add(activeAnalystId);
      return next;
    });
    loadDocs(activeAnalystId);
  }, [activeAnalystId, structureLoaded, loadDocs]);

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
        <Link to="/" className="space-link" aria-label="На главную" onClick={onClose}>
          <span className="space-icon">РТ</span>
          <span className="space-name">Ревью требований</span>
        </Link>
      </div>

      <div className="nav-label">Обзор</div>
      <Link
        to="/"
        className={`nav-item${onHome ? " active" : ""}`}
        aria-current={onHome ? "page" : undefined}
        onClick={onClose}
      >
        <span className="ic">🏠</span> <span>Главная</span>
      </Link>

      <div className="nav-label">Структура</div>
      {/* группа: стрелка раскрывает дерево структуры, клик по названию —
          карта кластеров */}
      <div className="nav-row">
        <button
          type="button"
          className="disc"
          onClick={() => setStructureOpen((v) => !v)}
          aria-expanded={structureOpen}
          aria-label="Структура в дереве"
        >
          {structureOpen ? "▾" : "▸"}
        </button>
        <Link
          to="/clusters"
          className={`nav-item${onClustersMap ? " active" : ""}`}
          aria-current={onClustersMap ? "page" : undefined}
          onClick={onClose}
        >
          <span className="ic">🗂</span> <span>Кластеры</span>
        </Link>
      </div>
      {structureOpen && (
        <div className="nav-tree">
          {structureError && (
            <div className="nav-empty">не удалось загрузить структуру</div>
          )}
          {!structureError && clusters.length === 0 && analysts.length === 0 && (
            <div className="nav-empty">структура не заведена</div>
          )}
          {clusters.map((cluster) => {
            const clusterOpen = openClusters.has(cluster.id);
            return (
              <div className="nav-branch nav-cluster" key={cluster.id}>
                <div className="nav-row">
                  <button
                    type="button"
                    className="disc"
                    onClick={() => toggleCluster(cluster.id)}
                    aria-expanded={clusterOpen}
                    aria-label={`Команды кластера ${cluster.name}`}
                  >
                    {clusterOpen ? "▾" : "▸"}
                  </button>
                  <span
                    className="org-dot"
                    style={{ background: clusterColor(cluster.color, cluster.id) }}
                    aria-hidden="true"
                  />
                  <Link
                    to={`/clusters/${cluster.id}`}
                    className={`nav-item${cluster.id === activeClusterId ? " active" : ""}`}
                    aria-current={cluster.id === activeClusterId ? "page" : undefined}
                    onClick={onClose}
                  >
                    <span>{cluster.name}</span>
                  </Link>
                  <span className="nav-count">{cluster.teams_count}</span>
                </div>
                {clusterOpen && (
                  <div className="nav-tree">
                    {cluster.teams.length === 0 && <div className="nav-empty">нет команд</div>}
                    {cluster.teams.map((team) => {
                      const teamOpen = openTeams.has(team.id);
                      const members = membersByTeam.get(team.id) ?? [];
                      return (
                        <div className="nav-branch nav-team" key={team.id}>
                          <div className="nav-row">
                            <button
                              type="button"
                              className="disc"
                              onClick={() => toggleTeam(team.id)}
                              aria-expanded={teamOpen}
                              aria-label={`Аналитики команды ${team.name}`}
                            >
                              {teamOpen ? "▾" : "▸"}
                            </button>
                            <Link
                              to={`/teams/${team.id}`}
                              className={`nav-item${team.id === activeTeamId ? " active" : ""}`}
                              aria-current={team.id === activeTeamId ? "page" : undefined}
                              onClick={onClose}
                            >
                              <span>{team.name}</span>
                            </Link>
                            <span className="nav-count">{members.length}</span>
                          </div>
                          {teamOpen && (
                            <div className="nav-tree">
                              {members.length === 0 && (
                                <div className="nav-empty">нет аналитиков</div>
                              )}
                              {members.map((analyst) => (
                                <AnalystBranch
                                  key={analyst.id}
                                  analyst={analyst}
                                  isActive={analyst.id === activeAnalystId}
                                  isOpen={expanded.has(analyst.id)}
                                  branch={branches[analyst.id]}
                                  activeDocId={activeDocId}
                                  onToggle={() => toggleBranch(analyst.id)}
                                  onClose={onClose}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* аналитики вне структуры: ровно та же ветка аналитика */}
          <div className="nav-branch nav-cluster nav-no-team">
            <div className="nav-row">
              <button
                type="button"
                className="disc"
                onClick={() => setNoTeamOpen((v) => !v)}
                aria-expanded={noTeamOpen}
                aria-label="Аналитики без команды"
              >
                {noTeamOpen ? "▾" : "▸"}
              </button>
              <span className={`nav-item${onAllAnalysts ? "" : " nav-item-muted"}`}>
                Без команды
              </span>
              <span className="nav-count">{freeAnalysts.length}</span>
            </div>
            {noTeamOpen && (
              <div className="nav-tree">
                {freeAnalysts.length === 0 && (
                  <div className="nav-empty">все распределены</div>
                )}
                {freeAnalysts.map((analyst) => (
                  <AnalystBranch
                    key={analyst.id}
                    analyst={analyst}
                    isActive={analyst.id === activeAnalystId}
                    isOpen={expanded.has(analyst.id)}
                    branch={branches[analyst.id]}
                    activeDocId={activeDocId}
                    onToggle={() => toggleBranch(analyst.id)}
                    onClose={onClose}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* путь к реестру аналитиков доступен и при свёрнутом дереве */}
      <Link
        to="/analysts"
        className={`nav-item nav-all-analysts${onAllAnalysts ? " active" : ""}`}
        aria-current={onAllAnalysts ? "page" : undefined}
        onClick={onClose}
      >
        <span className="ic">👥</span> <span>Все аналитики</span>
      </Link>

      <div className="nav-label">Моё</div>
      <Link to="/ai-connection" className={`nav-item${onAiConnection ? " active" : ""}`} onClick={onClose}>
        <span className="ic">⚡</span> Мой доступ к ИИ
      </Link>

      {canUser("moderation") && (
        <>
          <div className="nav-label">Администрирование</div>
          <Link to="/requests" className={`nav-item${location.pathname.startsWith("/requests") ? " active" : ""}`} onClick={onClose}>
            <span className="ic">📥</span> Заявки на доступ
            {(me?.pending_requests ?? 0) > 0 && (
              <span className="nav-count nav-count-accent">{me?.pending_requests}</span>
            )}
          </Link>
        </>
      )}
      <Link to="/roles" className={`nav-item${location.pathname.startsWith("/roles") ? " active" : ""}`} onClick={onClose}>
        <span className="ic">🛡</span> Роли и права
        {!canUser("roles.manage") && <span className="nav-count">просмотр</span>}
      </Link>

      <div className="user-box">
        <span className="u-avatar" aria-hidden="true">
          {(me?.full_name ?? "Р").trim().charAt(0).toUpperCase()}
        </span>
        <span className="user-box-info">
          <span className="u-name">{me?.full_name ?? "…"}</span>
          <span className="u-role">
            <span className={`role-pill ${me?.is_god ? "role-god" : "role-lead"}`}>
              {(me?.role_name ?? "…").toUpperCase()}
            </span>
          </span>
        </span>
        <button
          type="button"
          className="u-logout"
          title="Выйти"
          aria-label="Выйти"
          onClick={onLogout}
        >
          ⎋
        </button>
      </div>
      <Link
        to="/templates"
        className={`nav-item${onTemplate ? " active" : ""}`}
        onClick={onClose}
      >
        <span className="ic">🧩</span> Шаблоны требований
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
  const [me, setMeState] = useState<Me | null>(null);
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

  // текущий пользователь: имя, роль, права (канвас кнопок), личный ИИ
  useEffect(() => {
    if (!authed) {
      setMeState(null);
      return;
    }
    fetchMe()
      .then(setMeState)
      .catch(() => setAuthed(false));
  }, [authed]);

  // SSE-стрим событий фоновых задач: итог проверок и синхронизаций
  // приходит на открытые страницы сам. Живёт, пока пользователь в сервисе.
  useEffect(() => {
    if (authed) startEvents();
    else stopEvents();
  }, [authed]);

  if (!authed) {
    return (
      <LoginGate
        onAuthenticated={(meFull) => {
          setMeState(meFull);
          setAuthed(true);
        }}
      />
    );
  }

  return (
    <UserContext.Provider value={me}>
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
          title={`${me?.full_name ?? ""} — выйти`}
          aria-label={`Выйти (${me?.full_name ?? "пользователь"})`}
          onClick={() => {
            authLogout();
            setAuthed(false);
          }}
        >
          {(me?.full_name ?? "Р").trim().charAt(0).toUpperCase()}
        </button>
      </header>
      <div className="layout">
        <Sidebar
          open={navOpen}
          onClose={() => setNavOpen(false)}
          onLogout={() => {
            authLogout();
            setMeState(null);
            setAuthed(false);
          }}
        />
        <div
          className={`sidebar-backdrop${navOpen ? " show" : ""}`}
          onClick={() => setNavOpen(false)}
        />
        <main className="content">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/clusters" element={<ClustersPage />} />
            <Route path="/analysts" element={<AnalystsPage />} />
            <Route path="/clusters/:clusterId" element={<ClusterPage />} />
            <Route path="/teams/:teamId" element={<TeamPage />} />
            <Route path="/analysts/:analystId" element={<AnalystProfilePage />} />
            <Route path="/analysts/:analystId/documents" element={<DocumentsPage />} />
            <Route path="/analysts/:analystId/stats" element={<AnalystStatsPage />} />
            <Route path="/documents/:documentId" element={<ReportPage />} />
            <Route path="/templates" element={<TemplatesPage />} />
            <Route path="/templates/new" element={<TemplatePage />} />
            <Route path="/templates/:templateId" element={<TemplatePage />} />
            {/* старый путь одного шаблона — ведём на список */}
            <Route path="/template" element={<Navigate to="/templates" replace />} />
            <Route path="/criteria" element={<CriteriaPage />} />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/roles" element={<RolesPage />} />
            <Route path="/ai-connection" element={<AiSettingsPage />} />
          </Routes>
        </main>
      </div>
    </UserContext.Provider>
  );
}
