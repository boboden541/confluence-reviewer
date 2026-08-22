import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Analyst,
  type BulkValidationStatus,
  type DocumentPage,
} from "../api";

const STATUS_LABELS: Record<string, string> = {
  not_checked: "не проверено",
  in_progress: "проверяется",
  passed: "пройдено",
  failed: "не пройдено",
  error: "ошибка",
};

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
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [data, setData] = useState<DocumentPage | null>(null);
  const [query, setQuery] = useState("");
  const [urlFilter, setUrlFilter] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bulk, setBulk] = useState<BulkValidationStatus | null>(null);
  const bulkTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!analystId) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "20" });
      if (query.trim()) params.set("query", query.trim());
      if (urlFilter.trim()) params.set("url", urlFilter.trim());
      setData(
        await api<DocumentPage>(`/api/analysts/${analystId}/documents?${params}`),
      );
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить документы");
    } finally {
      setLoading(false);
    }
  }, [analystId, page, query, urlFilter]);

  useEffect(() => {
    load();
  }, [load]);

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
            await load();
          }
        } catch {
          // статус недоступен — продолжаем опрос
        }
      }, 1000);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось запустить проверку");
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

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
            <button onClick={validateAll} disabled={!data || data.total === 0}>
              Проверить все
            </button>
          )}
          <span className="muted">{data ? `Всего документов: ${data.total}` : ""}</span>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="search">
        <input
          placeholder="Поиск по названию…"
          value={query}
          onChange={(e) => {
            setPage(1);
            setQuery(e.target.value);
          }}
        />
        <input
          placeholder="Поиск по ссылке…"
          value={urlFilter}
          onChange={(e) => {
            setPage(1);
            setUrlFilter(e.target.value);
          }}
        />
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Название</th>
            <th>Статус проверки</th>
            <th>Создан</th>
            <th>Изменён</th>
            <th>Проверен</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(data?.items ?? []).map((doc) => (
            <tr key={doc.id}>
              <td>
                <Link to={`/documents/${doc.id}`}>{doc.title}</Link>
              </td>
              <td>
                <span className={`badge ${doc.validation_status}`}>
                  {STATUS_LABELS[doc.validation_status] ?? doc.validation_status}
                </span>
              </td>
              <td>{formatDate(doc.created_in_confluence_at)}</td>
              <td>{formatDate(doc.last_modified_in_confluence_at)}</td>
              <td>{formatDate(doc.last_validated_at)}</td>
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
          {!loading && data?.items.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                Документы не найдены
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {totalPages > 1 && (
        <div className="pagination">
          <button
            className="secondary"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            ← Назад
          </button>
          <span>
            Страница {page} из {totalPages}
          </span>
          <button
            className="secondary"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Вперёд →
          </button>
        </div>
      )}
    </section>
  );
}
