"""FastAPI-зависимости: сессия БД и basic-авторизация.

Фасад для импорта в роутерах: `from app.dependencies import get_db, require_basic_auth`.
"""

from app.dependencies.auth import (
    AuthRequiredError,
    add_catch_all,
    install_auth,
    require_basic_auth,
)
from app.dependencies.db import get_db

__all__ = [
    "AuthRequiredError",
    "add_catch_all",
    "get_db",
    "install_auth",
    "require_basic_auth",
]
