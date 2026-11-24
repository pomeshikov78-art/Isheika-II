"""Доверенные корневые сертификаты для исходящих HTTPS-запросов.

Зачем отдельный модуль
----------------------
Встраиваемый CPython в Windows-сборке берёт доверенные корни только из
хранилища Windows. Пока нужный корень туда не попал (автообновление корней
отключено, машина без сети, новый удостоверяющий центр), запрос к источнику падает
с «SSL: CERTIFICATE_VERIFY_FAILED … unable to get local issuer certificate»,
хотя в браузере тот же адрес открывается. Так на машине пользователя не
работал arXiv: его сертификат подписан «Certainly Root R1/E1», которого в
хранилище Windows не было.

Поэтому приложение возит собственный набор корней (``isheika/data/cacert.pem``,
корни Mozilla NSS) и добавляет его к системному доверию. Проверка сертификатов
остаётся обязательной: небезопасного режима «не проверять» в приложении нет.

Порядок источников доверия:
  1. системное доверие (хранилище Windows или пути OpenSSL в Linux);
  2. набор приложения ``isheika/data/cacert.pem``;
  3. необязательный файл из ``ISHEIKA_CA_BUNDLE`` (корпоративный прокси/УЦ).
"""
from __future__ import annotations

import os
import ssl
import threading

BUNDLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cacert.pem")
_LOCK = threading.Lock()
_CTX: ssl.SSLContext | None = None
_INFO: dict = {}


def _load(ctx: ssl.SSLContext, path: str) -> int:
    """Загружает набор корней; возвращает число добавленных сертификатов."""
    if not path or not os.path.isfile(path):
        return 0
    before = ctx.cert_store_stats().get("x509_ca", 0)
    ctx.load_verify_locations(cafile=path)
    return max(0, ctx.cert_store_stats().get("x509_ca", 0) - before)


def context() -> ssl.SSLContext:
    """Готовый контекст TLS: проверка включена, корни приложения добавлены."""
    global _CTX
    with _LOCK:
        if _CTX is None:
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            system = ctx.cert_store_stats().get("x509_ca", 0)
            bundled = _load(ctx, BUNDLE)
            bundled_certs = 0
            if os.path.isfile(BUNDLE):
                with open(BUNDLE, encoding="utf-8", errors="replace") as fh:
                    bundled_certs = fh.read().count("BEGIN CERTIFICATE")
            extra_path = os.environ.get("ISHEIKA_CA_BUNDLE") or ""
            extra = _load(ctx, extra_path)
            _CTX = ctx
            _INFO.update({
                "system_anchors": system,
                "bundled_anchors": bundled,
                "bundled_certs": bundled_certs,
                "bundle_path": BUNDLE if os.path.isfile(BUNDLE) else None,
                "extra_path": extra_path or None,
                "extra_anchors": extra,
                "total_anchors": ctx.cert_store_stats().get("x509_ca", 0),
                "verify": True,
            })
        return _CTX


def info() -> dict:
    """Сведения о доверии — для самопроверки и разбора отказов источников."""
    context()
    return dict(_INFO)


def reset() -> None:
    """Сбрасывает кэш (используется испытанием при смене набора корней)."""
    global _CTX
    with _LOCK:
        _CTX = None
        _INFO.clear()


def hint(error: str) -> str:
    """Пояснение к отказу проверки сертификата — что делать оператору."""
    if "CERTIFICATE_VERIFY_FAILED" not in (error or "").upper():
        return ""
    i = info()
    return ("Проверка сертификата источника не прошла. В приложении загружено "
            f'{i.get("total_anchors", 0)} корневых сертификатов '
            f'(системных {i.get("system_anchors", 0)}, в наборе приложения '
            f'{i.get("bundled_certs", 0)}). '
            "Если источник за корпоративным прокси или использует свой удостоверяющий "
            "центр, укажите его корни файлом в переменной окружения ISHEIKA_CA_BUNDLE "
            "и перезапустите приложение. Проверка сертификатов не отключается.")
