import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  ApiError,
  type AiConnectionConfig,
  type Analyst,
  type BulkValidationStatus,
  type Cluster,
  type DashboardOut,
  type DashboardSection,
  type FeedEvent,
  type SyncStatus,
  type TemplateCard,
  type AiCriterion,
} from "../api";
import { clusterColor, clusterColorBg } from "../orgUi";
import { listRecent, RecentEntry, RecentKind } from "../recent";
import { on } from "../events";
import RemindersPanel from "../RemindersPanel";
import type { Me } from "../auth";
import { useUser } from "../userContext";

/** Главная страница — пульт руководителя (согласованный макет home-mock):
 *  очередь внимания (что требует реакции), «сейчас» и живая лента (что
 *  происходит), недавние, свёрнутая структура и точки входа в разделы. */

const HOUR = 3_600_000;

const SECTION_STYLE: Record<
  DashboardSection["type"],
  { ico: string; bg: string; fg: string }
> = {
  failed: { ico: "❌", bg: "#FFEBE6", fg: "#AE2E24" },
  stale: { ico: "⟳", bg: "#FFF7D6", fg: "#7A5D00" },
  ratings: { ico: "⭐", bg: "#E9F2FF", fg: "#0C66E4" },
  no_team: { ico: "👤", bg: "#F3F0FF", fg: "#6E5DC6" },
  references: { ico: "⚙️", bg: "#F1F2F4", fg: "#44546F" },
};

function routeFor(section: DashboardSection, item: DashboardSection["items"][number]): string {
  if (item.document_id != null) return `/documents/${item.document_id}`;
  if (item.analyst_id != null) return `/analysts/${item.analyst_id}`;
  if (item.template_id != null) return `/templates/${item.template_id}`;
  if (section.type === "references") {
    if (item.section === "criteria") return "/criteria";
    if (item.section === "ai") return "/ai-connection";
    return "/templates";
  }
  return "/clusters";
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  if (diff >= 0 && diff < HOUR) {
    const minutes = Math.max(1, Math.round(diff / 60_000));
    return `${minutes} мин. назад`;
  }
  const sameDay = new Date().toDateString() === date.toDateString();
  return sameDay
    ? `сегодня в ${date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`
    : date.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function feedText(event: FeedEvent): { ico: string; bg: string; title: string; sub: string } {
  const p = event.payload as Record<string, unknown>;
  if (event.type === "validation") {
    const status = String(p.status ?? "");
    if (status === "done") {
      return {
        ico: "🧪",
        bg: "#E9F2FF",
        title: "Проверка завершена",
        sub: `документ #${String(p.document_id)} → открыть отчёт`,
      };
    }
    if (status === "running") {
      return {
        ico: "⏳",
        bg: "#E9F2FF",
        title: "Запущена проверка",
        sub: `документ #${String(p.document_id)}`,
      };
    }
    if (status === "not_found") {
      return { ico: "❌", bg: "#FFEBE6", title: "Проверка не запущена", sub: "документ не найден" };
    }
    return {
      ico: "❌",
      bg: "#FFEBE6",
      title: "Проверка не удалась",
      sub: String(p.error ?? ""),
    };
  }
  if (event.type === "sync") {
    const running = Boolean(p.running);
    if (running) {
      return { ico: "⟳", bg: "#E9F2FF", title: "Синхронизация запущена", sub: "" };
    }
    const results = Array.isArray(p.last_results) ? p.last_results : [];
    const created = results.reduce((acc, r) => acc + Number((r as Record<string, unknown>).created ?? 0), 0);
    const updated = results.reduce((acc, r) => acc + Number((r as Record<string, unknown>).updated ?? 0), 0);
    const error = String(p.error ?? "");
    if (error) {
      return { ico: "❌", bg: "#FFEBE6", title: "Синхронизация не удалась", sub: error };
    }
    return {
      ico: "⟳",
      bg: "#DCFFF1",
      title: "Синхронизация завершена",
      sub: `+${created} новых, ${updated} обновлено`,
    };
  }
  // bulk
  const running = Boolean(p.running);
  const done = Number(p.done ?? 0);
  const total = Number(p.total ?? 0);
  return running
    ? { ico: "🧪", bg: "#E9F2FF", title: "Массовая проверка", sub: `готово ${done} из ${total}` }
    : { ico: "✅", bg: "#DCFFF1", title: "Массовая проверка завершена", sub: `${total} ${plural(total, "документ", "документа", "документов")}` };
}

const RECENT_ICO: Record<RecentKind, string> = {
  document: "📄",
  analyst: "👤",
  cluster: "🗂",
};
const RECENT_ROUTE: Record<RecentKind, (id: number) => string> = {
  document: (id) => `/documents/${id}`,
  analyst: (id) => `/analysts/${id}`,
  cluster: (id) => `/clusters/${id}`,
};

export default function HomePage() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<DashboardOut | null>(null);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [analysts, setAnalysts] = useState<Analyst[]>([]);
  const [templates, setTemplates] = useState<TemplateCard[]>([]);
  const [criteria, setCriteria] = useState<AiCriterion[]>([]);
  const [ai, setAi] = useState<AiConnectionConfig | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [bulk, setBulk] = useState<BulkValidationStatus | null>(null);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [recent, setRecent] = useState<RecentEntry[]>(() => listRecent());
  const [myAnalysts, setMyAnalysts] = useState<DashboardOut["my_analysts"]>([]);
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["failed"]));
  const [error, setError] = useState("");
  const me = useUser();

  const load = useCallback(async () => {
    try {
      const [dash, clusterList, analystList] = await Promise.all([
        api<DashboardOut>("/api/dashboard"),
        api<Cluster[]>("/api/clusters"),
        api<Analyst[]>("/api/analysts"),
      ]);
      setDashboard(dash);
      setMyAnalysts(dash.my_analysts ?? []);
      setClusters(clusterList);
      setAnalysts(analystList);
      setError("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Не удалось загрузить главную");
    }
  }, []);

  useEffect(() => {
    void load();
    setRecent(listRecent()); // визиты других вкладок могли изменить список
    // служебные состояния и лента: разовый опрос + живые события поверх
    api<SyncStatus>("/api/sync/status").then(setSync).catch(() => setSync(null));
    api<BulkValidationStatus>("/api/sync/bulk-validation").then(setBulk).catch(() => setBulk(null));
    void (async () => {
      // «Моя активность»: события, где актор — текущий пользователь
      const meId = await api<Me>("/api/auth/me")
        .then((m) => m.id)
        .catch(() => null);
      api<FeedEvent[]>(`/api/dashboard/feed${meId ? `?actor_id=${meId}` : ""}`)
        .then(setFeed)
        .catch(() => setFeed([]));
    })();
    api<TemplateCard[]>("/api/templates").then(setTemplates).catch(() => setTemplates([]));
    api<AiCriterion[]>("/api/ai-criteria").then(setCriteria).catch(() => setCriteria([]));
    api<AiConnectionConfig>("/api/ai-settings")
      .then(setAi)
      .catch(() => setAi(null));
  }, [load]);

  // живая лента: события приходят сами, статус «сейчас» обновляется следом
  useEffect(() => {
    const asFeed = (type: FeedEvent["type"], payload: Record<string, unknown>): FeedEvent => ({
      type,
      at: new Date().toISOString(),
      payload,
    });
    // снимок подключения (синхронный статус, без at) — не событие: в ленту
    // не попадает, а состояния «сейчас» обновляет
    // перезагрузка очереди не чаще раза в 1.5 c: массовая проверка шлёт
    // событие на каждый документ, а агрегат пересчитывать надо один раз
    let reloadTimer: number | undefined;
    const scheduleReload = () => {
      window.clearTimeout(reloadTimer);
      reloadTimer = window.setTimeout(() => void load(), 1500);
    };
    const offs = [
      on("validation", (e) => {
        setFeed((prev) => [asFeed("validation", { ...e }), ...prev].slice(0, 30));
        if (e.status !== "running") scheduleReload();
      }),
      on("sync", (e) => {
        setSync(e);
        if (e.at === undefined) return;
        setFeed((prev) => [asFeed("sync", { ...e }), ...prev].slice(0, 30));
        scheduleReload();
      }),
      on("bulk", (e) => {
        setBulk(e);
        if (e.at === undefined) return;
        setFeed((prev) => [asFeed("bulk", { ...e }), ...prev].slice(0, 30));
      }),
    ];
    return () => {
      window.clearTimeout(reloadTimer);
      offs.forEach((off) => off());
    };
  }, [load]);

  const toggleSection = (type: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const attentionTotal = useMemo(
    () => dashboard?.sections.reduce((acc, s) => acc + s.total, 0) ?? 0,
    [dashboard],
  );
  const freeAnalysts = analysts.filter((a) => a.team_id === null);
  const activeTemplates = templates.filter((t) => !t.is_archived);
  const activeCriteria = criteria.filter((c) => !c.is_archived);
  const aiConfigured = Boolean(
    ai && (ai.base_url || ai.env.base_url) && (ai.api_key_masked || ai.env.api_key_set),
  );
  const aiModel = ai ? ai.model || ai.env.model || "" : "";

  return (
    <section className="page">
      <nav className="breadcrumbs">
        <span className="home-crumb">🏠 Главная</span>
      </nav>

      <div className="hello">
        <h1>{me ? `Добрый день, ${me.full_name.split(" ")[0]}!` : "Ревью требований"}</h1>
        <span className="hello-date">
          {new Date().toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" })}
        </span>
        <div className="hello-chips">
          {sync?.running ? (
            <span className="chip-status chip-busy">⟳ Синхронизация идёт…</span>
          ) : sync?.finished_at ? (
            <span className="chip-status chip-ok">⟳ Синхронизация: {formatTime(sync.finished_at)}</span>
          ) : (
            <span className="chip-status chip-warn">⟳ Синхронизация ещё не запускалась</span>
          )}
          {bulk?.running && (
            <span className="chip-status chip-busy">
              🧪 Массовая проверка: {bulk.done} из {bulk.total}
            </span>
          )}
          {me && !me.ai_configured ? (
            <Link className="chip-status chip-warn" to="/ai-connection" style={{ textDecoration: "none" }}>
              ⚡ ИИ не настроен — проверки заблокированы
            </Link>
          ) : aiConfigured ? (
            <span className="chip-status chip-ok">⚡ ИИ: {aiModel || "настроено"}</span>
          ) : (
            <Link className="chip-status chip-warn" to="/ai-connection" style={{ textDecoration: "none" }}>
              ⚡ Подключите ИИ
            </Link>
          )}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="home-grid">
        {/* ЛЕВАЯ КОЛОНКА: очередь внимания + структура */}
        <div className="col">
          <div className="panel grow">
            <div className="panel-head">
              <h2>🎯 Требует внимания</h2>
              {attentionTotal > 0 && <span className="count">{attentionTotal}</span>}
            </div>
            <div className="panel-body">
              {dashboard?.sections.map((section) => {
                const style = SECTION_STYLE[section.type];
                const open = openSections.has(section.type);
                return (
                  <div className="q-section" key={section.type}>
                    <button
                      className="q-head"
                      onClick={() => toggleSection(section.type)}
                      aria-expanded={open}
                    >
                      <span className="q-ico" style={{ background: style.bg, color: style.fg }} aria-hidden="true">
                        {style.ico}
                      </span>
                      <span className="q-title">{section.title}</span>
                      {section.total > 0 && <span className="q-count">{section.total}</span>}
                      <span className={`q-arrow${open ? " open" : ""}`} aria-hidden="true">▸</span>
                    </button>
                    {open && (
                      <div className="q-items open">
                        {section.items.map((item) => (
                          <a
                            key={item.key}
                            className="q-item"
                            href={routeFor(section, item)}
                            onClick={(e) => {
                              e.preventDefault();
                              navigate(routeFor(section, item));
                            }}
                          >
                            <span className="dot" style={{ background: style.fg }} aria-hidden="true" />
                            <span className="q-main">
                              <span className="q-name">{item.title}</span>
                              {item.subtitle && <span className="q-meta">{item.subtitle}</span>}
                            </span>
                            {item.at && <span className="q-time">{formatTime(item.at)}</span>}
                          </a>
                        ))}
                        {section.total > section.items.length && (
                          <div className="q-more">и ещё {section.total - section.items.length}…</div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {dashboard && attentionTotal === 0 && (
                <div className="q-empty">
                  <span className="big">🎉</span>Всё под контролем — ничего не требует внимания
                </div>
              )}
              {!dashboard && <div className="q-empty">Загрузка…</div>}
            </div>
          </div>

          {/* Свёрнутая структура */}
          <div className="panel">
            <div className="panel-head">
              <h2>🗂 Структура</h2>
              <span className="count">
                {clusters.length} {plural(clusters.length, "кластер", "кластера", "кластеров")} ·{" "}
                {clusters.reduce((acc, c) => acc + c.analysts_count, 0)} в командах ·{" "}
                {freeAnalysts.length} без команды
              </span>
            </div>
            <div className="mini-map">
              {clusters.map((cluster) => (
                <Link key={cluster.id} to={`/clusters/${cluster.id}`} className="mini-cluster" style={{ borderTopColor: clusterColor(cluster.color, cluster.id) }}>
                  <span className="nm">{cluster.name}</span>
                  <span className="ct">
                    {cluster.teams_count} {plural(cluster.teams_count, "команда", "команды", "команд")} ·{" "}
                    {cluster.analysts_count} {plural(cluster.analysts_count, "аналитик", "аналитика", "аналитиков")}
                  </span>
                  <span>
                    {cluster.teams.map((team) => (
                      <span
                        key={team.id}
                        className="mini-chip"
                        style={{ background: clusterColorBg(cluster.color, cluster.id), color: clusterColor(cluster.color, cluster.id) }}
                      >
                        {team.name}
                      </span>
                    ))}
                  </span>
                </Link>
              ))}
              <Link to="/clusters" className="mini-cluster" style={{ borderTopColor: "#D0D5DD" }}>
                <span className="nm" style={{ color: "var(--text-subtle)" }}>Без команды</span>
                <span className="ct">{freeAnalysts.length} {plural(freeAnalysts.length, "аналитик", "аналитика", "аналитиков")}</span>
              </Link>
            </div>
          </div>
        </div>

        {/* ПРАВАЯ КОЛОНКА: заявки (god) + мои аналитики + сейчас + лента + недавние */}
        <div className="col">
          {me?.is_god && (me.pending_requests ?? 0) > 0 && (
            <Link
              to="/requests"
              className="panel"
              style={{ padding: "12px 16px", textDecoration: "none", color: "var(--text)" }}
            >
              <strong>📥 Заявки на доступ</strong>{" "}
              <span className="badge badge-warn">{me.pending_requests} новых</span>
            </Link>
          )}
          {myAnalysts.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>👥 Мои аналитики</h2>
                <span className="count">{myAnalysts.length}</span>
              </div>
              <div className="panel-body">
                {myAnalysts.map((item) => (
                  <Link key={item.key} to={`/analysts/${item.analyst_id}`} className="recent-item">
                    <span className="doc-ico" aria-hidden="true">👤</span>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.name}
                      {item.team_name ? ` · ${item.team_name}` : ""}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
          <RemindersPanel showDoneToggle />

          <div className="panel">
            <div className="panel-head"><h2>⏳ Сейчас происходит</h2></div>
            <div className="now-row">
              <span aria-hidden="true">⟳</span>
              <span className="what">Синхронизация Confluence</span>
              <b>{sync?.running ? "идёт" : sync?.finished_at ? formatTime(sync.finished_at) : "не запускалась"}</b>
            </div>
            <div className="now-row">
              <span aria-hidden="true">🧪</span>
              <span className="what">Массовая проверка</span>
              <b>{bulk?.running ? `${bulk.done} из ${bulk.total}` : "не запущена"}</b>
            </div>
          </div>

          <div className="panel grow">
            <div className="panel-head">
              <h2>📡 Живая лента</h2>
              {feed.length > 0 && <span className="count">{feed.length}</span>}
            </div>
            <div className="panel-body">
              {feed.length === 0 && (
                <div className="q-empty">Событий пока нет — запустите синхронизацию или проверку</div>
              )}
              {feed.map((event, index) => {
                const look = feedText(event);
                const p = event.payload as Record<string, unknown>;
                const target =
                  event.type === "validation" && p.document_id != null
                    ? `/documents/${Number(p.document_id)}`
                    : null;
                return (
                  <button
                    key={`${event.at}-${event.type}-${index}`}
                    type="button"
                    className="feed-item"
                    onClick={() => {
                      if (target) navigate(target);
                    }}
                    disabled={!target}
                  >
                    <span className="feed-ico" style={{ background: look.bg }} aria-hidden="true">{look.ico}</span>
                    <span className="feed-main">
                      <span className="feed-text">{look.title}</span>
                      {look.sub && <span className="feed-sub">{look.sub}</span>}
                    </span>
                    <span className="feed-time">{formatTime(event.at)}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head"><h2>🕘 Недавние</h2></div>
            <div className="panel-body">
              {recent.length === 0 && (
                <div className="q-empty">Здесь появится то, что вы открывали</div>
              )}
              {recent.map((entry) => (
                <Link key={`${entry.kind}-${entry.id}`} to={RECENT_ROUTE[entry.kind](entry.id)} className="recent-item">
                  <span className="doc-ico" aria-hidden="true">{RECENT_ICO[entry.kind]}</span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entry.title}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Сервисные разделы */}
      <div className="bottom" style={{ marginTop: 16 }}>
        <div className="tiles">
          <Link className="svc" to="/templates">
            <span className="svc-ico" aria-hidden="true">🧩</span>
            <span>
              <span className="svc-name">Шаблоны требований</span>
              <span className="svc-sub" style={{ display: "block" }}>
                {activeTemplates.length} активных · {templates.length - activeTemplates.length} в архиве
              </span>
            </span>
          </Link>
          <Link className="svc" to="/criteria">
            <span className="svc-ico" aria-hidden="true">✅</span>
            <span>
              <span className="svc-name">Критерии ИИ</span>
              <span className="svc-sub" style={{ display: "block" }}>
                {activeCriteria.length} активных · {criteria.length - activeCriteria.length} архивных
              </span>
            </span>
          </Link>
          <Link className="svc" to="/ai-connection">
            <span className="svc-ico" aria-hidden="true">⚡</span>
            <span>
              <span className="svc-name">Подключение ИИ</span>
              <span className="svc-sub" style={{ display: "block" }}>
                {aiConfigured ? aiModel || "настроено" : "не настроено"}
              </span>
            </span>
          </Link>
          <Link className="svc" to="/analysts">
            <span className="svc-ico" aria-hidden="true">👥</span>
            <span>
              <span className="svc-name">Все аналитики</span>
              <span className="svc-sub" style={{ display: "block" }}>
                {analysts.length} {plural(analysts.length, "карточка", "карточки", "карточек")} ·{" "}
                {freeAnalysts.length} без команды
              </span>
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}
