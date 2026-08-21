# Confluence Reviewer

Сервис проверки работы системных аналитиков в Confluence: синхронизация созданных
ими страниц, валидация на соответствие шаблону требований (скриптовая) и на качество
наполнения (ИИ), отчёты с замечаниями в Markdown, заметки руководителя и быстрая
обратная связь через комментарии в Confluence.

- Бизнес-требования: [sa_documentation/bft/confluence-reviewer-bft.md](sa_documentation/bft/confluence-reviewer-bft.md)
- Стек: backend — Python (FastAPI), frontend — React (Vite), БД — PostgreSQL, запуск — Docker Compose.

Полная инструкция по установке и эксплуатации — в конце разработки (см. раздел «Запуск»).

## Запуск (кратко)

```bash
cp .env.example .env   # заполнить секреты
docker compose up -d --build
# UI: http://localhost:8080
```
