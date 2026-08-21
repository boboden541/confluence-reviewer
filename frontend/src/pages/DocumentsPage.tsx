import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Analyst, type DocumentPage } from "../api";

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
  const [analyst, setAnalyst] = useState<Analyst | null>(null);
  const [data, setData] = useState<DocumentPage | null>(null);
  const [query, setQuery] = useState("");
  const [urlFilter, setUrlFilter] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
        <div className="muted">
          {data ? `Всего документов: ${data.total}` : ""}
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
            </tr>
          ))}
          {!loading && data?.items.length === 0 && (
            <tr>
              <td colSpan={5} className="empty">
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
