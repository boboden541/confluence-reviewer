import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import {
  clearCredentials,
  hasCredentials,
  login,
  saveCredentials,
  UNAUTHORIZED_EVENT,
} from "./api";
import AnalystsPage from "./pages/AnalystsPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReportPage from "./pages/ReportPage";

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
      <h1>Confluence Reviewer</h1>
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
      <button type="submit" disabled={busy}>
        {busy ? "Проверка…" : "Войти"}
      </button>
    </form>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(hasCredentials());

  useEffect(() => {
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (!authed) {
    return <LoginGate />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          Confluence Reviewer
        </Link>
        <button
          className="link"
          onClick={() => {
            clearCredentials();
            setAuthed(false);
          }}
        >
          Выйти
        </button>
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<AnalystsPage />} />
          <Route path="/analysts/:analystId" element={<DocumentsPage />} />
          <Route path="/documents/:documentId" element={<ReportPage />} />
        </Routes>
      </main>
    </div>
  );
}
