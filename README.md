# Confluence Reviewer

Сервис проверки работы системных аналитиков: находит страницы с требованиями
в Confluence, проверяет их на соответствие шаблону требований и качество
содержимого (ИИ), и позволяет руководителю оставить заметки и опубликовать
замечания комментарием прямо на страницу Confluence.

Полная постановка — в [`sa_documentation/bft/confluence-reviewer-bft.md`](sa_documentation/bft/confluence-reviewer-bft.md).

## Возможности

- **Карточки аналитиков**: ФИО + email, ручное переопределение username Confluence.
- **Синхронизация**: по кнопке и по расписанию (раз в N часов) сервис находит все
  страницы, созданные аналитиком (CQL `type=page AND creator=…`), и сохраняет их
  содержимое. Догрузка полного тела — только для новых/изменившихся страниц.
- **Проверка шаблона (скрипт)**: соответствие заголовка маске `[СТ]`, наличие
  обязательных разделов и подразделов, обязательные секции в каждом блоке
  доработки, порядок разделов (как предупреждение). Шаблон —
  `backend/app/templates/requirements_template.json`.
- **ИИ-проверка содержимого (GLM)**: модель оценивает полноту, непротиворечивость
  и однозначность требований через Anthropic-совместимый API (z.ai).
- **Отчёты и статусы**: `not_checked → in_progress → passed/failed/error`;
  идемпотентность — неизменённый документ не переводалидируется.
- **Комментарий в Confluence**: публикация замечаний отчёта одной кнопкой.
- **Заметки руководителя**: Markdown-заметка по каждому документу.
- **Безопасность**: basic-auth на весь сервис (кроме `/api/health`), секреты
  только через `.env`.

## Стек

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2 (SQLite для тестов / PostgreSQL
  в проде), APScheduler, httpx, Anthropic SDK (GLM), BeautifulSoup.
- **Frontend**: React 18 + TypeScript, Vite, react-router.
- **Инфраструктура**: Docker Compose (postgres + backend + nginx со SPA).

## Быстрый старт

```bash
cp .env.example .env
# заполните .env: токен Confluence, ключ ИИ, пароли (см. таблицу ниже)

docker compose up -d --build
docker compose exec backend python -m pytest tests/ -q   # тесты внутри контейнера
```

UI доступен на `http://localhost:8080` (логин/пароль — `APP_USERNAME`/`APP_PASSWORD` из `.env`).

## Локальная разработка

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000

# frontend (в отдельном терминале)
cd frontend
npm install
npm run dev                             # http://localhost:5173, /api → :8000

# тесты
cd backend && python -m pytest tests/ -q
cd frontend && npm test
```

## Переменные окружения (`.env`)

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | пароль БД (для docker compose) | — (обязательна) |
| `DATABASE_URL` | строка подключения SQLAlchemy | postgres в compose |
| `AUTH_ENABLED` | basic-auth сервиса | `true` |
| `APP_USERNAME` / `APP_PASSWORD` | учётка сервиса | `reviewer` / — |
| `CONFLUENCE_BASE_URL` | адрес Confluence DC | — |
| `CONFLUENCE_AUTH_TYPE` | `bearer` (PAT) или `basic` | `bearer` |
| `CONFLUENCE_TOKEN` | Personal Access Token | — |
| `CONFLUENCE_CREATOR_FIELD` | `email` \| `username` \| `auto` | `auto` |
| `SYNC_INTERVAL_HOURS` | период автосинхронизации | `24` |
| `AI_BASE_URL` | Anthropic-совместимый API | z.ai |
| `AI_API_KEY` | ключ ИИ | — |
| `AI_MODEL` | модель ИИ | `glm-4.5` |
| `SEED_ANALYSTS` | `ФИО:email;…` первичное наполнение | — |
| `FRONTEND_PORT` | внешний порт UI | `8080` |

Полный список с значениями по умолчанию — `backend/app/config.py` и `.env.example`.

## API (кратко)

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/health` | живость (без авторизации) |
| `GET/POST /api/analysts` | список / создание аналитиков |
| `POST /api/analysts/{id}/sync` | синхронизация одного (202, фон) |
| `POST /api/sync/all`, `GET /api/sync/status` | синхронизация всех / статус |
| `GET /api/analysts/{id}/documents` | документы: пагинация, `query`, `url` |
| `GET /api/documents/{id}` | карточка документа |
| `POST /api/documents/{id}/validate?force=` | запуск проверки (202, фон) |
| `GET /api/documents/{id}/report` | последний отчёт валидации |
| `POST /api/documents/{id}/comment` | опубликовать замечания в Confluence |
| `GET/PUT /api/documents/{id}/note` | заметка руководителя |

## Схема работы валидации

1. Синхронизация находит новые/изменившиеся страницы → автозапуск проверки.
2. Скриптовая проверка шаблона → ИИ-проверка содержимого → отчёт + статус.
3. При техническом сбое — статус `error` с текстом; повторный запуск повторит попытку.
4. Документ не менялся в Confluence → повторная проверка возвращает прежний отчёт
   без вызова ИИ (`force=true` обходит).

## Структура репозитория

```text
backend/            FastAPI-сервис (app/, tests/, Dockerfile)
frontend/           React SPA (Vite, nginx для раздачи)
sa_documentation/   БФТ и сопутствующая документация
docker-compose.yml  db + backend + frontend
```

## Безопасность

- Секреты не коммитятся: `.env` в `.gitignore`, шаблон — `.env.example`.
- Basic-auth покрывает все маршруты кроме `/api/health`.
- Токены в этой среде передавались через приватный канал; перед боевым
  использованием смените их в Confluence и z.ai.
