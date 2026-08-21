"""Общие фикстуры тестов: приложение на временной sqlite-БД, без авторизации."""

from __future__ import annotations

import os
import tempfile

import pytest

# Должно быть настроено ДО импорта приложения: Settings читает env при создании.
_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["AUTH_ENABLED"] = "false"
os.environ["CONFLUENCE_BASE_URL"] = "https://confluence.test"
os.environ["CONFLUENCE_TOKEN"] = "test-token"
os.environ["AI_API_KEY"] = "test-ai-key"

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
