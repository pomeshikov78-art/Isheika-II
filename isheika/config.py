"""Конфигурация и профили развёртывания DEV / PILOT / PROD (ТЗ-05 §12.4).

Все секреты — только на сервере. В браузер не попадают ни ключи, ни их длины.
Значения квот/лимитов не «зашиваются»: они приходят из реестра и фактических
ответов API; неизвестное значение остаётся None и отображается как «неизвестно».
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("ISHEIKA_DATA", os.path.join(ROOT, "var"))
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry", "seed")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def configure_console() -> None:
    """Кириллица в консоли Windows: legacy-кодировка (cp1252/cp866) не должна
    приводить к падению сервера при выводе сообщения о запуске.

    Вызывается идемпотентно из точки входа и из api.server.main.
    """
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            if (getattr(stream, "encoding", "") or "").lower().replace("-", "") not in ("utf8",):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@dataclass
class Settings:
    profile: str = "DEV"                       # DEV | PILOT | PROD
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = field(default_factory=lambda: os.path.join(DATA_DIR, "isheika.db"))
    cache_dir: str = field(default_factory=lambda: os.path.join(DATA_DIR, "cache"))
    files_dir: str = field(default_factory=lambda: os.path.join(DATA_DIR, "files"))
    secrets_path: str = field(default_factory=lambda: os.path.join(DATA_DIR, "secrets.enc"))
    # --- политика ИИ (ТЗ-02 §1, §5)
    allow_paid_ai: bool = False                # платные вызовы выключены по умолчанию
    allow_external_ai: bool = True             # передача данных внешним провайдерам
    privacy_class_max: str = "public"          # public | internal | restricted
    ai_mode: str = "auto"                      # auto | simulation | live
    # --- политика сети (ТЗ-01 §5)
    network_enabled: bool = True
    respect_robots: bool = True
    http_timeout: float = 20.0
    max_parallel_fetch: int = 8
    user_agent: str = "IsheikaNTR-AI/0.1 (open scientific and technical intelligence; contact: unset)"
    contact_email: str = ""                    # для polite pool Crossref / Unpaywall
    # --- лимиты исследования
    max_docs_per_source: int = 25
    max_docs_per_research: int = 400
    relevance_direct: float = 0.80
    relevance_adjacent: float = 0.60
    methodology_version: str = "M-1.0.0"
    # --- API v1.1 (ИД-04): единый каталог маршрутов, срок совместимости старых путей
    api_legacy_compat: bool = False
    api_legacy_sunset: str = "2027-05-24"

    @staticmethod
    def load() -> "Settings":
        s = Settings()
        cfg = os.path.join(DATA_DIR, "config.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        if hasattr(s, k):
                            setattr(s, k, v)
            except Exception:
                pass
        for k in ("profile", "port", "ai_mode", "network_enabled", "allow_paid_ai", "contact_email"):
            env = os.environ.get("ISHEIKA_" + k.upper())
            if env is not None:
                cur = getattr(s, k)
                if isinstance(cur, bool):
                    setattr(s, k, env.lower() in ("1", "true", "yes", "on"))
                elif isinstance(cur, int):
                    setattr(s, k, int(env))
                else:
                    setattr(s, k, env)
        if s.profile == "DEV":
            # DEV: имитационные адаптеры разрешены, платные вызовы запрещены
            s.allow_paid_ai = False
        return s

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, "config.json"), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)

    def ensure_dirs(self) -> None:
        for d in (DATA_DIR, self.cache_dir, self.files_dir):
            os.makedirs(d, exist_ok=True)

    def public_dict(self) -> dict:
        """То, что можно отдать в UI. Пути к секретам не раскрываются."""
        d = asdict(self)
        for k in ("secrets_path", "db_path"):
            d.pop(k, None)
        d["secrets_configured"] = os.path.exists(self.secrets_path)
        return d


SETTINGS = Settings.load()
