"""HTTP-клиент поискового контура на стандартной библиотеке.

Требования ТЗ-01 §5, ТЗ-05 §13, Прил. А §12:
  * уважение robots.txt и ToS, стоп-лист доменов;
  * кэш ответов (метаданные — надолго, статусы/новости — TTL);
  * Retry-After и экспоненциальный backoff;
  * контроль исходящих запросов (SSRF: только http/https, запрет приватных адресов);
  * журнал всех обращений с HTTP-кодом, длительностью и объёмом;
  * маскирование секретов в журналах.
"""
from __future__ import annotations

import gzip
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Any

from ..config import SETTINGS
from .. import telemetry
from ..contracts import CoreError, iso_now, new_id
from ..storage import db
from ..storage.secrets import mask
from . import quota

_ROBOTS: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
STOP_CACHE: list[dict] | None = None


def _stoplist() -> list[dict]:
    global STOP_CACHE
    if STOP_CACHE is None:
        STOP_CACHE = db.query("SELECT code, pattern, reason, action FROM registry_stoplist")
    return STOP_CACHE


def check_url_allowed(url: str, *, automated: bool = True) -> None:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise CoreError("E_POLICY", f"Запрещённая схема URL: {p.scheme}", url=url)
    host = (p.hostname or "").lower()
    if not host:
        raise CoreError("E_VALIDATION", "Пустой хост", url=url)
    # SSRF: запрет приватных/loopback/link-local адресов
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise CoreError("E_POLICY", "Запрещён доступ к внутренним адресам (SSRF)", host=host)
    except socket.gaierror:
        pass
    for rule in _stoplist():
        if re.search(rule["pattern"], url, re.I):
            if rule["action"] == "downgrade":
                continue
            if rule["action"] == "block_automation" and not automated:
                continue
            raise CoreError("E_POLICY", f'{rule["code"]}: {rule["reason"]}', url=url, rule=rule["code"])


def robots_allowed(url: str) -> bool:
    if not SETTINGS.respect_robots:
        return True
    p = urllib.parse.urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    entry = _ROBOTS.get(base)
    now = time.time()
    if entry is None or now - entry[0] > 3600:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": SETTINGS.user_agent})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read(200_000).decode("utf-8", "replace")
            rp.parse(raw.splitlines())
        except Exception:
            rp = None      # недоступен robots.txt — не запрещаем, но фиксируем
        _ROBOTS[base] = (now, rp)
        entry = _ROBOTS[base]
    rp = entry[1]
    if rp is None:
        return True
    return rp.can_fetch(SETTINGS.user_agent, url)


def _cache_path(key: str) -> str:
    SETTINGS.ensure_dirs()
    return os.path.join(SETTINGS.cache_dir, key + ".json")


def cache_get(url: str, ttl_s: int) -> dict | None:
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    if ttl_s >= 0 and time.time() - os.path.getmtime(path) > ttl_s:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_put(url: str, payload: dict) -> None:
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    with open(_cache_path(key), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def request(url: str, *, method: str = "GET", headers: dict | None = None, data: bytes | None = None,
            connector: dict | None = None, research_id: str | None = None,
            ttl_s: int = 7 * 86400, timeout: float | None = None,
            max_attempts: int = 3, heavy: bool = False) -> dict:
    """Выполнить запрос с политиками. Возвращает {status, body, headers, bytes, cached, duration_ms}."""
    check_url_allowed(url)
    # Политика robots: для документированных официальных API применяется
    # документация/ToS провайдера (robots.txt сайта адресован веб-краулерам).
    # Решение фиксируется в журнале обращений и в карточке коннектора.
    robots_policy = (connector or {}).get("robots_policy") or "respect"
    if robots_policy != "api_terms" and not robots_allowed(url):
        raise CoreError("E_ROBOTS", "robots.txt запрещает автоматический доступ", url=url)
    if not SETTINGS.network_enabled:
        raise CoreError("E_NETWORK", "Сетевой контур отключён (offline-профиль)", url=url)

    cache_key = url if method == "GET" else url + "|" + hashlib.sha256(data or b"").hexdigest()[:16]
    if method == "GET" and ttl_s >= 0:
        cached = cache_get(cache_key, ttl_s)
        if cached is not None:
            _log_api("http", (connector or {}).get("code", "http"), url, cached.get("status"),
                     cached.get("duration_ms", 0), cached.get("bytes", 0), True, research_id)
            return {**cached, "cached": True}

    conn = connector or {"code": "http", "limits": {}, "quota_policy": {}}
    if connector:
        quota.enforce_connector_policy(conn, heavy=heavy)
    domain = urllib.parse.urlparse(url).netloc
    rps = (conn.get("limits") or {}).get("rps")

    hdrs = {"User-Agent": SETTINGS.user_agent, "Accept-Encoding": "gzip"}
    hdrs.update(headers or {})
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        quota.wait_token(domain, rps)
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=hdrs, data=data, method=method)
            with urllib.request.urlopen(req, timeout=timeout or SETTINGS.http_timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                body = raw.decode("utf-8", "replace")
                dur = int((time.time() - t0) * 1000)
                rh = dict(resp.headers.items())
                payload = {"status": resp.status, "body": body, "headers": rh,
                           "bytes": len(raw), "duration_ms": dur}
                if method == "GET" and ttl_s >= 0:
                    cache_put(cache_key, payload)
                _log_api("http", conn["code"], url, resp.status, dur, len(raw), False, research_id)
                if connector:
                    try:
                        bj = json.loads(body) if body.strip().startswith(("{", "[")) else None
                    except Exception:
                        bj = None
                    quota.record_response(conn, bytes_read=len(raw), headers=rh,
                                          body_json=bj if isinstance(bj, dict) else None)
                return {**payload, "cached": False}
        except urllib.error.HTTPError as e:
            dur = int((time.time() - t0) * 1000)
            body = ""
            try:
                body = e.read(4000).decode("utf-8", "replace")
            except Exception:
                pass
            _log_api("http", conn["code"], url, e.code, dur, len(body), False, research_id,
                     error_code="E_PROVIDER" if e.code >= 500 else "E_RATE_LIMIT" if e.code == 429 else "E_NETWORK")
            if e.code in (401, 403):
                raise CoreError("E_POLICY" if e.code == 403 else "E_AUTH",
                                f"HTTP {e.code}: доступ запрещён или требуется ключ", retryable=False,
                                url=url, http_status=e.code, body=mask(body[:400]))
            if e.code == 429 or e.code >= 500:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                delay = float(retry_after) if (retry_after or "").isdigit() else min(30.0, 2.0 ** attempt)
                last_err = CoreError("E_RATE_LIMIT" if e.code == 429 else "E_PROVIDER",
                                     f"HTTP {e.code}", retryable=True, url=url, http_status=e.code)
                if attempt < max_attempts:
                    time.sleep(delay)
                    continue
                raise last_err
            raise CoreError("E_NETWORK", f"HTTP {e.code}", url=url, http_status=e.code,
                            body=mask(body[:400]))
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            dur = int((time.time() - t0) * 1000)
            _log_api("http", conn["code"], url, None, dur, 0, False, research_id, error_code="E_NETWORK")
            last_err = CoreError("E_NETWORK", mask(str(e))[:200], retryable=True, url=url)
            if attempt < max_attempts:
                time.sleep(min(20.0, 1.5 ** attempt))
                continue
            raise last_err
    raise last_err or CoreError("E_NETWORK", "Не удалось выполнить запрос", url=url)


def get_json(url: str, **kw: Any) -> Any:
    res = request(url, **kw)
    try:
        return json.loads(res["body"])
    except Exception as e:
        raise CoreError("E_SCHEMA", f"Ответ не является JSON: {e}", url=url)


def _log_api(kind: str, target: str, url: str, status: int | None, duration_ms: int,
             nbytes: int, cached: bool, research_id: str | None, error_code: str | None = None) -> None:
    try:
        db.insert("audit_api_calls", {
            "id": new_id("api-"), "kind": kind, "target": target,
            "url": _strip_secrets(url), "http_status": status, "duration_ms": duration_ms,
            "bytes": nbytes, "cached": 1 if cached else 0, "error_code": error_code,
            "research_id": research_id, "created_at": iso_now(),
            **{k: v for k, v in telemetry.current().items()}})
    except Exception:
        pass


SECRET_QS = re.compile(r"([?&](?:key|api_key|apikey|token|access_token|auth|password)=)[^&]+", re.I)


def _strip_secrets(url: str) -> str:
    return SECRET_QS.sub(lambda m: m.group(1) + "***", url)
