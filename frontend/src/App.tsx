import { useEffect, useState } from "react";
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
  type SyncStatus,
} from "./api";
import AnalystsPage from "./pages/AnalystsPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReportPage from "./pages/ReportPage";
import TemplatePage from "./pages/TemplatePage";
import GlobalSearch from "./GlobalSearch";

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

/** Сайдбар пространства: навигация + дерево документов аналитиков (стиль Confluence). */
function Sidebar() {
  const location = useLocation();
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [docsOpen, setDocsOpen] = useState(false);
  const [sync, setSync] = useState<SyncStatus | null>(null);

  useEffect(() => {
    api<Analyst[]>("/api/analysts")
      .then(setAnalysts)
      .catch(() => setAnalysts([]));
    api<SyncStatus>("/api/sync/status")
      .then(setSync)
      .catch(() => setSync(null));
  }, []);

  const onAnalysts = location.pathname === "/";
  const onTemplate = location.pathname.startsWith("/template");
  const activeAnalystId = Number(
    location.pathname.match(/^\/analysts\/(\d+)/)?.[1] ?? NaN,
  );
  // раскрытое дерево документов: открыли аналитика — показываем его ветку
  useEffect(() => {
    if (!Number.isNaN(activeAnalystId)) setDocsOpen(true);
  }, [activeAnalystId]);

  return (
    <aside className="sidebar">
      <div className="space-head">
        <span className="space-icon">РТ</span>
        <span className="space-name">Ревью требований</span>
      </div>

      <div className="nav-label">Обзор</div>
      <Link to="/" className={`nav-item${onAnalysts ? " active" : ""}`}>
        <span className="ic">👥</span> Аналитики
      </Link>

      <button
        type="button"
        className="nav-item"
        onClick={() => setDocsOpen((v) => !v)}
        aria-expanded={docsOpen}
      >
        <span className="disclosure">{docsOpen ? "▾" : "▸"}</span>
        <span className="ic">📄</span> Документы
      </button>
      {docsOpen && (
        <div className="nav-tree">
          {analysts.length === 0 && <div className="nav-empty">аналитики не заведены</div>}
          {analysts.map((analyst) => (
            <Link
              key={analyst.id}
              to={`/analysts/${analyst.id}`}
              className={`nav-item${analyst.id === activeAnalystId ? " active" : ""}`}
            >
              {analyst.full_name}
            </Link>
          ))}
        </div>
      )}

      <div className="nav-label">Настройка</div>
      <Link to="/template" className={`nav-item${onTemplate ? " active" : ""}`}>
        <span className="ic">🧩</span> Шаблон требований
      </Link>

      <div className="sync-status">
        {sync?.running
          ? "⟳ Идёт синхронизация…"
          : sync?.finished_at
            ? `⟳ Синхронизация: ${new Date(sync.finished_at).toLocaleString("ru-RU")}`
            : "⟳ Синхронизация ещё не запускалась"}
      </div>
    </aside>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(hasCredentials());
  const [me, setMe] = useState("Р");

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

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
        <Link to="/" className="topbar-logo">
          <span className="logo-mark">РТ</span> Ревью требований
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
        <Sidebar />
        <main className="content">
          <Routes>
            <Route path="/" element={<AnalystsPage />} />
            <Route path="/analysts/:analystId" element={<DocumentsPage />} />
            <Route path="/documents/:documentId" element={<ReportPage />} />
            <Route path="/template" element={<TemplatePage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
