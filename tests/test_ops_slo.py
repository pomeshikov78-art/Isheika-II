"""Испытания эксплуатационного контура (ROADMAP P6, ред. 1.3).

SLO-01…08 — самопроверки, расчёт доступности, бюджет ошибок, burn rate,
жизненный цикл алертов и RBAC. BKP-01…06 — резервные копии: создание,
проверка, обнаружение повреждения, восстановление с подтверждением.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile

from isheika import backup as BK, slo
from isheika.api import server as SRV, service as S
from isheika.contracts import CoreError, iso_now, new_id
from isheika.storage import db
from tests.base import BaseCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SLOTests(BaseCase):
    def _fill(self, component: str, ok: int, failed: int) -> None:
        """Изолированная серия самопроверок: компонент-метка не пересекается с боевыми."""
        db.execute("DELETE FROM service_probes WHERE component=?", (component,))
        for i in range(ok):
            slo.record(component, True, 1.0, "тест", at=iso_now())
        for i in range(failed):
            slo.record(component, False, 2.0, "тестовый отказ", at=iso_now())

    def tearDown(self) -> None:
        db.execute("DELETE FROM service_probes WHERE component LIKE 'test-%'")

    def test_SLO_01_probes_measure_real_subsystems(self):
        """SLO-01: самопроверки выполняют реальные операции и фиксируют результат."""
        rows = slo.run_probes()
        self.assertEqual([r["component"] for r in rows], list(slo.COMPONENTS))
        for r in rows:
            self.assertTrue(r["ok"], r["detail"])
            self.assertGreaterEqual(r["latency_ms"], 0.0)
            self.assertTrue(db.one("SELECT * FROM service_probes WHERE id=?", (r["id"],)))
        with self.assertRaises(CoreError):
            slo.probe("не-существует")

    def test_SLO_02_no_data_is_not_fabricated(self):
        """SLO-02: без измерений — NO_DATA и null, а не «100 %» (принцип ИД-10)."""
        saved = db.query("SELECT * FROM service_probes")
        db.execute("DELETE FROM service_probes")
        try:
            st = slo.window_stats(24)
            self.assertEqual(st["state"], "NO_DATA")
            self.assertIsNone(st["availability_pct"])
            self.assertIsNone(st["error_budget_used_pct"])
            self.assertEqual(slo.burn_rate(1.0)["state"], "NO_DATA")
        finally:
            for r in saved:
                db.insert("service_probes", r)

    def test_SLO_03_availability_and_error_budget(self):
        """SLO-03: доступность = доля успехов; бюджет ошибок = 2 %; порог 98 %."""
        self._fill("test-slo-a", 98, 2)
        st = slo.window_stats(24, "test-slo-a")
        self.assertEqual(st["probes"], 100)
        self.assertAlmostEqual(st["availability_pct"], 98.0, places=6)
        self.assertAlmostEqual(st["error_budget_used_pct"], 100.0, places=3)
        self.assertEqual(st["state"], "OK")            # ровно на цели — не нарушение
        self._fill("test-slo-a", 97, 3)
        st = slo.window_stats(24, "test-slo-a")
        self.assertAlmostEqual(st["availability_pct"], 97.0, places=6)
        self.assertEqual(st["state"], "BREACH")
        self.assertAlmostEqual(st["error_budget_used_pct"], 150.0, places=3)
        self.assertEqual(slo.ERROR_BUDGET, 2.0)

    def test_SLO_04_burn_rate(self):
        """SLO-04: burn rate = доля отказов / допустимая доля; порог 14.4×."""
        self._fill("test-slo-b", 70, 30)               # 30 % отказов / 2 % = 15×
        br = slo.burn_rate(1.0, "test-slo-b")
        self.assertAlmostEqual(br["burn_rate"], 15.0, places=3)
        self.assertEqual(br["state"], "CRITICAL")
        self._fill("test-slo-b", 99, 1)                # 1 % / 2 % = 0.5×
        br = slo.burn_rate(1.0, "test-slo-b")
        self.assertAlmostEqual(br["burn_rate"], 0.5, places=3)
        self.assertEqual(br["state"], "OK")

    def test_SLO_05_alert_lifecycle(self):
        """SLO-05: алерт открывается по отказу и закрывается только после устранения."""
        db.execute("DELETE FROM ops_alerts WHERE rule_code='COMPONENT_DOWN'")
        slo.record("storage", False, 1.0, "тестовый отказ хранилища")
        res = slo.evaluate_alerts(emit_events=False)
        opened = [a for a in res["opened"] if a["rule_code"] == "COMPONENT_DOWN"]
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["severity"], "critical")
        self.assertIn("storage", opened[0]["message"])
        self.assertIn("components", opened[0]["context"])      # доказательства приложены
        slo.record("storage", True, 1.0, "тестовое восстановление")
        res = slo.evaluate_alerts(emit_events=False)
        self.assertIn(opened[0]["id"], res["closed"])
        row = db.one("SELECT * FROM ops_alerts WHERE id=?", (opened[0]["id"],))
        self.assertEqual(row["state"], "closed")
        self.assertTrue(row["closed_at"])

    def test_SLO_06_acknowledge_is_not_close(self):
        """SLO-06: подтверждение оператором не закрывает алерт и не плодит дубликаты."""
        db.execute("DELETE FROM ops_alerts WHERE rule_code='COMPONENT_DOWN'")
        slo.record("api", False, 1.0, "тестовый отказ транспорта")
        slo.evaluate_alerts(emit_events=False)
        alert = db.one("SELECT * FROM ops_alerts WHERE rule_code='COMPONENT_DOWN' AND state<>'closed'")
        acked = slo.acknowledge(alert["id"], actor="tester")
        self.assertEqual(acked["state"], "acknowledged")
        self.assertEqual(acked["ack_by"], "tester")
        slo.evaluate_alerts(emit_events=False)                 # причина ещё есть
        active = db.query("SELECT * FROM ops_alerts WHERE rule_code='COMPONENT_DOWN' AND state<>'closed'")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], alert["id"])
        with self.assertRaises(CoreError):
            slo.acknowledge("alr-нет-такого", actor="tester")
        slo.record("api", True, 1.0, "тестовое восстановление")
        slo.evaluate_alerts(emit_events=False)
        with self.assertRaises(CoreError):
            slo.acknowledge(alert["id"], actor="tester")       # закрытый подтвердить нельзя

    def test_SLO_07_rules_carry_evidence(self):
        """SLO-07: правила детерминированы и возвращают числа-основания."""
        fired, message, ev = slo.RULES["CONNECTORS_DEGRADED"]["fn"]()
        self.assertIsInstance(fired, bool)
        self.assertIn("checked", ev)
        self.assertIn("threshold", ev)
        fired, message, ev = slo.RULES["BACKUP_OVERDUE"]["fn"]()
        self.assertIn("max_age_hours", ev)
        self.assertEqual(set(slo.RULES), {"SLO_AVAILABILITY_30D", "SLO_BURN_RATE_1H", "COMPONENT_DOWN",
                                          "CONNECTORS_DEGRADED", "PROVIDERS_UNAVAILABLE", "BACKUP_OVERDUE"})

    def test_SLO_08_routes_and_rbac(self):
        """SLO-08: маршруты опубликованы; чтение — logs.read, запись — keys.write."""
        raw = json.dumps([list(map(str, r[:2])) for r in SRV.ROUTES])
        for path in ("/api/v1/slo", "/api/v1/alerts", "/api/v1/backups"):
            self.assertIn(path, raw)
        S.require({"login": "auditor", "role": "auditor"}, "logs.read")
        observer = {"login": "observer", "role": "observer"}
        with self.assertRaises(CoreError):
            S.require(observer, "logs.read")
        with self.assertRaises(CoreError):
            S.require(observer, "keys.write")
        S.require({"login": "admin", "role": "admin"}, "keys.write")


class BackupTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="isheika-bkptest-")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_BKP_01_create_and_verify(self):
        """BKP-01: копия создаётся, проверяется и попадает в реестр."""
        row = BK.create(actor="tester", dest_dir=self.tmp)
        self.assertTrue(os.path.exists(row["path"]))
        self.assertGreater(row["size_bytes"], 0)
        self.assertEqual(len(row["sha256"]), 64)
        check = BK.verify(row["path"])
        self.assertTrue(check["ok"], check["checks"])
        names = {c["check"] for c in check["checks"]}
        self.assertTrue({"zip_crc", "db_integrity", "db_schema"} <= names)
        self.assertIn("isheika.db", check["manifest"]["files"])
        self.assertTrue(any(r["id"] == row["id"] for r in BK.list_backups()))
        with zipfile.ZipFile(row["path"]) as z:
            self.assertIn("manifest.json", z.namelist())

    def test_BKP_02_corruption_detected(self):
        """BKP-02: повреждение копии обнаруживается проверкой."""
        row = BK.create(actor="tester", dest_dir=self.tmp)
        with open(row["path"], "r+b") as f:
            f.seek(max(0, row["size_bytes"] // 2))
            f.write(b"\x00\x01\x02\x03\x04\x05\x06\x07")
        check = BK.verify(row["path"], register=False)
        self.assertFalse(check["ok"])

    def test_BKP_03_restore_requires_confirmation(self):
        """BKP-03: без явного подтверждения восстановление не выполняется."""
        row = BK.create(actor="tester", dest_dir=self.tmp)
        before = db.count("core_researches")
        with self.assertRaises(CoreError) as ctx:
            BK.restore(row["path"], actor="tester")
        self.assertEqual(ctx.exception.error.code, "E_STATE")
        self.assertEqual(db.count("core_researches"), before)

    def test_BKP_04_restore_rejects_bad_copy(self):
        """BKP-04: повреждённая копия не допускается к записи поверх состояния."""
        row = BK.create(actor="tester", dest_dir=self.tmp)
        with open(row["path"], "r+b") as f:
            f.seek(max(0, row["size_bytes"] // 2))
            f.write(b"\xff" * 16)
        before = db.count("core_researches")
        with self.assertRaises(CoreError) as ctx:
            BK.restore(row["path"], actor="tester", confirm=True)
        self.assertEqual(ctx.exception.error.code, "E_VALIDATION")
        self.assertEqual(db.count("core_researches"), before)

    def test_BKP_05_cli_roundtrip(self):
        """BKP-05: CLI --backup → потеря данных → --restore --yes возвращает состояние."""
        data = os.path.join(self.tmp, "data")
        env = dict(os.environ, ISHEIKA_DATA=data, PYTHONIOENCODING="utf-8")

        def run(*args, code=None):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), *args],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
            if code is not None:
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            return r.stdout + r.stderr

        seed = ("from isheika.storage import db;from isheika.registry import loader;"
                "from isheika.api import service as S;db.init_db();loader.seed_all();"
                "S.create_research({'query':'связь за горизонтом','title':'До сбоя','countries':['RU']},actor='t');"
                "print(db.count('core_researches'))")
        out = subprocess.run([sys.executable, "-c", seed], cwd=ROOT, env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "1")
        backup_out = run("--backup", code=0)
        self.assertIn("Проверка: пройдена", backup_out)
        path = [l.split("Копия: ")[1].strip() for l in backup_out.splitlines() if l.startswith("Копия: ")][0]
        self.assertIn(os.path.basename(path), run("--list-backups", code=0))
        self.assertIn("Подтвердите ключом --yes", run("--restore", path, code=2))
        subprocess.run([sys.executable, "-c",
                        "from isheika.storage import db;db.init_db();db.execute('DELETE FROM core_researches')"],
                       cwd=ROOT, env=env, capture_output=True, timeout=180, check=True)
        restore_out = run("--restore", path, "--yes", code=0)
        self.assertIn("Копия прежнего состояния:", restore_out)
        count = subprocess.run([sys.executable, "-c",
                                "from isheika.storage import db;db.init_db();print(db.count('core_researches'))"],
                               cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
        self.assertEqual(count.stdout.strip().splitlines()[-1], "1")

    def test_BKP_06_backup_registered_in_alert_rule(self):
        """BKP-06: свежая копия снимает правило BACKUP_OVERDUE."""
        db.execute("DELETE FROM ops_alerts WHERE rule_code='BACKUP_OVERDUE'")
        BK.create(actor="tester", dest_dir=self.tmp)
        fired, _message, ev = slo.RULES["BACKUP_OVERDUE"]["fn"]()
        self.assertFalse(fired)
        self.assertTrue(ev["last_backup_at"])
        self.assertLess(ev["age_hours"], slo.BACKUP_MAX_AGE_HOURS)
