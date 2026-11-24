"""Серверное хранилище секретов (ТЗ-01 §8, ТЗ-02 §7).

Ключи хранятся только на сервере в зашифрованном виде, маскируются в логах,
никогда не попадают в HTML/JS/отчёты. Реализация DEV-профиля: потоковый шифр
на HMAC-SHA256 (keystream) + HMAC-аутентификация, мастер-ключ из файла с
правами 0600. Для PROD предусмотрен переход на AES-GCM/KMS — интерфейс
`SecretStore` не меняется.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets as pysecrets

from ..config import SETTINGS
from . import db


def _master_key() -> bytes:
    path = SETTINGS.secrets_path + ".master"
    env = os.environ.get("ISHEIKA_MASTER_KEY")
    if env:
        return hashlib.sha256(env.encode()).digest()
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    SETTINGS.ensure_dirs()
    key = pysecrets.token_bytes(32)
    with open(path, "wb") as f:
        f.write(key)
    os.chmod(path, 0o600)
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str) -> str:
    key = _master_key()
    nonce = pysecrets.token_bytes(16)
    data = plaintext.encode("utf-8")
    ks = _keystream(key, nonce, len(data))
    ct = bytes(a ^ b for a, b in zip(data, ks))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + ct + tag).decode()


def decrypt(blob: str) -> str:
    key = _master_key()
    raw = base64.urlsafe_b64decode(blob.encode())
    nonce, ct, tag = raw[:16], raw[16:-16], raw[-16:]
    expect = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expect):
        raise ValueError("Нарушена целостность секрета")
    ks = _keystream(key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks)).decode("utf-8")


# Маскируются пары «ключ=значение», заголовки Authorization и схемы Bearer/Basic:
# значение после префикса схемы тоже является секретом.
MASK_RE = re.compile(r"(?i)\b(api[_-]?key|apikey|token|secret|authorization|password|bearer)\b"
                     r"(\s*[:=]\s*|\s+)((?:bearer|basic)\s+)?[^\s,;\"\']+")


def mask(text: str) -> str:
    """Маскирование секретов в любых журналах и сообщениях об ошибках."""
    if not text:
        return text
    text = MASK_RE.sub(lambda m: m.group(1) + "=***", text)
    text = re.sub(r"\b(sk|pk|ghp|xoxb|AIza)[A-Za-z0-9_\-]{12,}\b", lambda m: m.group(1) + "***", text)
    return text


class SecretStore:
    @staticmethod
    def put(ref: str, kind: str, owner: str, value: str) -> None:
        from ..contracts import iso_now
        db.upsert("core_secrets", {
            "ref": ref, "kind": kind, "owner": owner,
            "ciphertext": encrypt(value), "hint": value[-4:] if len(value) > 8 else "****",
            "created_at": iso_now(), "updated_at": iso_now(),
        }, key="ref")

    @staticmethod
    def get(ref: str) -> str | None:
        row = db.one("SELECT ciphertext FROM core_secrets WHERE ref=?", (ref,))
        if not row:
            return None
        try:
            return decrypt(row["ciphertext"])
        except Exception:
            return None

    @staticmethod
    def delete(ref: str) -> None:
        db.execute("DELETE FROM core_secrets WHERE ref=?", (ref,))

    @staticmethod
    def list_public() -> list[dict]:
        """Только факт наличия ключа и последние 4 символа — не сам ключ."""
        return db.query("SELECT ref, kind, owner, hint, created_at, updated_at FROM core_secrets ORDER BY ref")

    @staticmethod
    def has(ref: str) -> bool:
        return db.one("SELECT 1 AS x FROM core_secrets WHERE ref=?", (ref,)) is not None
