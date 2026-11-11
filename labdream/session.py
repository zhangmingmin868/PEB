"""The logged-in user and audit logging helpers shared by all screens."""
from __future__ import annotations

from typing import Optional

from .security import Store, User

store: Optional[Store] = None
user: Optional[User] = None


def init(path: Optional[str] = None) -> Store:
    global store
    store = Store(path)
    return store


def name() -> str:
    return user.username if user else "?"


def can(perm: str) -> bool:
    return bool(user and user.can(perm))


def log(action: str, target: str = "", details=None):
    if store is not None:
        store.log(name(), action, target, details or {})
