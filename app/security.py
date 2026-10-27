"""Хеширование паролей, сессионные токены, ограничение попыток входа."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Tuple

PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


class PasswordPolicyError(ValueError):
    pass


def validate_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise PasswordPolicyError(
            "Логин: 3–32 символа, латинские буквы, цифры, точка, дефис или подчёркивание."
        )
    return username


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise PasswordPolicyError("Пароль должен содержать не менее 8 символов.")
    if len(password) > 256:
        raise PasswordPolicyError("Пароль слишком длинный (максимум 256 символов).")
    if password.strip() != password:
        raise PasswordPolicyError("Пароль не должен начинаться или заканчиваться пробелом.")
    if password.isalpha() or password.isdigit():
        raise PasswordPolicyError("Пароль должен содержать буквы и цифры.")
    return password


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = (stored or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def expires_at(hours: int) -> str:
    moment = utc_now() + timedelta(hours=max(1, int(hours)))
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LoginThrottle:
    """Простое ограничение попыток входа: 10 неудач за 10 минут на пару логин+IP."""

    def __init__(self, limit: int = 10, window_seconds: int = 600) -> None:
        self.limit = limit
        self.window = window_seconds
        self._failures: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def _key(self, username: str, ip: str) -> Tuple[str, str]:
        return ((username or "").strip().lower(), ip or "")

    def is_blocked(self, username: str, ip: str) -> bool:
        key = self._key(username, ip)
        events = self._failures.get(key)
        if not events:
            return False
        cutoff = time.monotonic() - self.window
        while events and events[0] < cutoff:
            events.popleft()
        return len(events) >= self.limit

    def register_failure(self, username: str, ip: str) -> None:
        self._failures[self._key(username, ip)].append(time.monotonic())

    def reset(self, username: str, ip: str) -> None:
        self._failures.pop(self._key(username, ip), None)

    def retry_after(self, username: str, ip: str) -> int:
        key = self._key(username, ip)
        events = self._failures.get(key)
        if not events:
            return 0
        return max(1, int(self.window - (time.monotonic() - events[0])))


login_throttle = LoginThrottle()
