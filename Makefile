# Confluence Reviewer — локальный запуск в docker.
# Основная команда: make up — поднимает весь стек (db + backend + frontend).
# Секреты живут только в локальном .env (в git не попадает), см. .env.example.

export DOCKER_CONFIG ?= /tmp/dcfg  # обход credsStore-кворка macOS; переопределяется: make up DOCKER_CONFIG=

# docker compose (v2) — это CLI-плагин: при подменённом DOCKER_CONFIG он не виден,
# зато автономный docker-compose работает всегда. Детект — с тем же DOCKER_CONFIG,
# с которым пойдут рецепты.
COMPOSE := $(shell DOCKER_CONFIG=$(DOCKER_CONFIG) docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

.DEFAULT_GOAL := help

.PHONY: help up down restart rebuild logs ps smoke test clean

help: ## список команд
	@echo "Confluence Reviewer — локальный запуск:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-9s %s\n", $$1, $$2}'

up: ## поднять сервис (первый раз создаст .env из .env.example и подскажет, что заполнить)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Файла .env не было — создан из .env.example."; \
		echo "Заполните его (как минимум POSTGRES_PASSWORD, CONFLUENCE_BASE_URL, CONFLUENCE_TOKEN, AI_API_KEY) и запустите make up снова."; \
		exit 1; \
	fi
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Сервис поднят: http://localhost:8080 (логин/пароль — APP_USERNAME/APP_PASSWORD из .env)"
	@echo "Логи: make logs · живость: make smoke · остановить: make down"

down: ## остановить сервис (данные БД в томе сохраняются)
	$(COMPOSE) down

restart: ## перезапустить контейнеры без пересборки
	$(COMPOSE) restart

rebuild: ## пересобрать образы и поднять стек
	$(COMPOSE) up -d --build

logs: ## логи (все сразу или один: make logs S=db)
	$(COMPOSE) logs -f --tail=200 $(S)

ps: ## статус контейнеров
	$(COMPOSE) ps

smoke: ## проверка живости: /api/health должен отвечать 200
	@code=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/health); \
	if [ "$$code" = "200" ]; then \
		echo "OK: /api/health → 200, сервис жив"; \
	else \
		echo "FAIL: /api/health → $$code (смотрите make logs)"; \
		exit 1; \
	fi

test: ## тесты: backend (pytest) + frontend (vitest)
	@if [ ! -x backend/.venv/bin/python ]; then \
		echo "Нет backend/.venv: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt"; \
		exit 1; \
	fi
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npx vitest run

clean: ## остановить и удалить контейнеры/сеть (том postgres_data с данными БД НЕ удаляется)
	$(COMPOSE) down
	@echo "Контейнеры и сеть удалены. Том postgres_data (данные БД) сохранён."
