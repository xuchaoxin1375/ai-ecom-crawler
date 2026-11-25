"""Access-policy helpers shared by the CLI and the local web app."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MIN_ACCESS_TOKEN_LENGTH = 1
MAX_ACCESS_TOKEN_LENGTH = 256
SESSION_COOKIE_NAME = "ecom_session"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
AUTH_FAILURE_LIMIT = 5
AUTH_FAILURE_WINDOW_SECONDS = 60.0
AUTH_LOCKOUT_SECONDS = 30.0

SETTING_LAN_ENABLED = "serve_lan_enabled"
SETTING_TOKEN = "serve_token"


def hostname_only(host_header: str) -> str:
    value = host_header.strip().lower()
    if value.startswith("["):
        closing = value.find("]")
        return value[1:closing] if closing >= 0 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def normalize_host_name(host_header: str) -> str:
    """Return a bare, lower-case host name without brackets, port, or trailing dot."""
    return hostname_only(host_header).rstrip(".")


def is_loopback_host(host_header: str) -> bool:
    return normalize_host_name(host_header) in LOOPBACK_HOSTS


def is_loopback_bind(host: str) -> bool:
    text = str(host).strip().lower()
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def hash_token(token: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.sha256(salt + token.encode("utf-8")).hexdigest()


def verify_token(
    token: str | None,
    salt_hex: str | None,
    digest_hex: str | None,
) -> bool:
    if not token or not salt_hex or not digest_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.sha256(salt + token.encode("utf-8")).digest()
    return hmac.compare_digest(actual, expected)


def new_token() -> tuple[str, str, str]:
    """Return ``(token, salt_hex, digest_hex)``; only the plaintext is shown once."""
    token = secrets.token_urlsafe(24)
    salt = secrets.token_hex(16)
    return token, salt, hash_token(token, salt)


def validate_access_token(token: str) -> str:
    """Normalize a user-supplied access key; complexity is intentionally not enforced."""
    text = str(token).strip()
    if not text:
        raise ValueError("access key must not be empty")
    if len(text) > MAX_ACCESS_TOKEN_LENGTH:
        raise ValueError(
            f"access key must be at most {MAX_ACCESS_TOKEN_LENGTH} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError("access key must not contain control characters")
    return text


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _session_signature(token_hash: str, payload: bytes) -> bytes:
    key = bytes.fromhex(token_hash)
    return hmac.new(key, b"ecom-session\0" + payload, hashlib.sha256).digest()


def create_session(token_hash: str, now: float | None = None) -> str:
    """Create a stateless session value bound to the current token hash."""
    issued = time.time() if now is None else float(now)
    payload = json.dumps(
        {
            "exp": int(issued + SESSION_TTL_SECONDS),
            "iat": int(issued),
            "v": token_hash[:16],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = _session_signature(token_hash, payload)
    return f"{_base64url_encode(payload)}.{_base64url_encode(signature)}"


def verify_session(
    value: str | None,
    token_hash: str | None,
    now: float | None = None,
) -> bool:
    """Verify a session cookie signature, expiry, and current token fingerprint."""
    if not value or not token_hash:
        return False
    try:
        payload_part, signature_part = value.split(".", 1)
        payload = _base64url_decode(payload_part)
        signature = _base64url_decode(signature_part)
        expected = _session_signature(token_hash, payload)
    except (ValueError, binascii.Error):
        return False
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or data.get("v") != token_hash[:16]:
        return False
    try:
        expires = float(data.get("exp", 0))
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else float(now)
    return expires > current


class LoginRateLimiter:
    """In-memory failed-attempt limiter shared by login and Basic authentication."""

    def __init__(
        self,
        *,
        limit: int = AUTH_FAILURE_LIMIT,
        window_seconds: float = AUTH_FAILURE_WINDOW_SECONDS,
        lockout_seconds: float = AUTH_LOCKOUT_SECONDS,
    ) -> None:
        self._limit = max(1, int(limit))
        self._window = max(0.0, float(window_seconds))
        self._lockout = max(0.0, float(lockout_seconds))
        self._failures: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, now: float | None = None) -> int | None:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            blocked_until = self._blocked.get(key)
            if blocked_until is None:
                return None
            if blocked_until <= moment:
                self._blocked.pop(key, None)
                return None
            return max(1, int(blocked_until - moment + 0.999))

    def failure(self, key: str, now: float | None = None) -> int | None:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            blocked_until = self._blocked.get(key)
            if blocked_until is not None and blocked_until > moment:
                return max(1, int(blocked_until - moment + 0.999))
            failures = [
                stamp
                for stamp in self._failures.get(key, ())
                if moment - stamp <= self._window
            ]
            failures.append(moment)
            if len(failures) >= self._limit:
                until = moment + self._lockout
                self._blocked[key] = until
                self._failures.pop(key, None)
                return max(1, int(self._lockout))
            self._failures[key] = failures
            self._prune(moment)
            return None

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._blocked.pop(key, None)

    def _prune(self, now: float) -> None:
        self._failures = {
            key: [stamp for stamp in stamps if now - stamp <= self._window]
            for key, stamps in self._failures.items()
        }
        self._failures = {
            key: stamps for key, stamps in self._failures.items() if stamps
        }
        self._blocked = {
            key: until for key, until in self._blocked.items() if until > now
        }


def token_setting(salt_hex: str, digest_hex: str, updated_at: str) -> str:
    return json.dumps(
        {"salt": salt_hex, "hash": digest_hex, "updated_at": updated_at},
        ensure_ascii=False,
        sort_keys=True,
    )


def reset_token_setting(
    db_path: str | Path,
    token: str,
    *,
    updated_at: str,
) -> tuple[str, str, str]:
    """Persist a new token hash in an existing ledger; stop the server first."""
    value = validate_access_token(token)
    path = Path(db_path)
    if not path.is_file():
        raise ValueError(f"task ledger not found: {path}")
    salt = secrets.token_hex(16)
    digest = hash_token(value, salt)
    try:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO app_settings (key, value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (SETTING_TOKEN, token_setting(salt, digest, updated_at), updated_at),
            )
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValueError(f"cannot reset access key: {exc}") from exc
    return salt, digest, updated_at


def parse_token_setting(value: str | None) -> tuple[str, str, str | None] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    salt = str(data.get("salt") or "")
    digest = str(data.get("hash") or "")
    if not salt or not digest:
        return None
    updated = data.get("updated_at")
    return salt, digest, str(updated) if updated else None


def stored_token_available(db_path: str | Path) -> bool:
    """Check for a persisted token hash without creating or writing the ledger."""
    path = Path(db_path)
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (SETTING_TOKEN,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return parse_token_setting(str(row[0]) if row else None) is not None
