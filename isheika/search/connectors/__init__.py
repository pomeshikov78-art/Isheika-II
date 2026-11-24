"""Реестр коннекторов поискового контура.

Импорт модулей регистрирует классы в REGISTRY. Добавление нового источника
не требует изменения ядра (ТЗ, требование «расширение без правки ядра»).
"""
from .base import BaseConnector, REGISTRY, build_connector, register, mark_source_status  # noqa: F401
from . import science, patents, other  # noqa: F401  (регистрация классов)

__all__ = ["BaseConnector", "REGISTRY", "build_connector", "register", "mark_source_status"]
