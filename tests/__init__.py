"""Автотесты «ИЩЕЙКА НТР AI».

Тесты работают в изолированном каталоге данных (временная БД), не трогают
рабочую базу и не выполняют сетевых обращений.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="isheika-tests-")
os.environ["ISHEIKA_DATA"] = _TMP
os.environ["ISHEIKA_PROFILE"] = "DEV"
os.environ["ISHEIKA_NETWORK_ENABLED"] = "false"
os.environ["ISHEIKA_AI_MODE"] = "simulation"
os.environ["ISHEIKA_ALLOW_PAID_AI"] = "false"
