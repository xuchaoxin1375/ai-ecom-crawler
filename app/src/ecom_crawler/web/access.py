"""Access-policy helpers shared by the CLI and the local web app."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MIN_ACCESS_TOKEN_LENGTH = 16

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


def token_setting(salt_hex: str, digest_hex: str, updated_at: str) -> str:
    return json.dumps(
        {"salt": salt_hex, "hash": digest_hex, "updated_at": updated_at},
        ensure_ascii=False,
        sort_keys=True,
    )


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
