"""Реестры: полнота посева, категории, страны, стоп-лист, «кладбище API» (ТЗ-01 §62)."""
from isheika.registry import loader
from isheika.storage import db

from .base import BaseCase


class RegistryTests(BaseCase):
    def test_sources_count_meets_spec(self):
        n = db.count("registry_sources")
        self.assertGreaterEqual(n, 300, "ТЗ требует не менее 300 источников")
        self.assertGreaterEqual(n, 800, "перечень содержит 806 позиций")

    def test_countries_35(self):
        self.assertEqual(db.count("dict_countries"), 35)

    def test_categories_12(self):
        cats = db.query("SELECT DISTINCT category FROM registry_sources ORDER BY category")
        self.assertEqual(len(cats), 12)

    def test_every_source_has_card_fields(self):
        rows = db.query("SELECT code, name, category, access_class, evidence_marker, integration_status FROM registry_sources")
        for r in rows:
            self.assertTrue(r["code"] and r["name"] and r["category"], r)
            self.assertIn(r["access_class"], {"A0", "A1", "A2", "A3", "A4", "UNKNOWN"})
            self.assertIn(r["evidence_marker"], {"П", "Р", "Д"})

    def test_connectors_providers_agents(self):
        self.assertGreaterEqual(db.count("registry_connectors"), 20)
        self.assertGreaterEqual(db.count("ai_providers"), 15)
        self.assertEqual(db.count("ai_agents"), 12)
        codes = [r["code"] for r in db.query("SELECT code FROM ai_agents ORDER BY code")]
        self.assertEqual(codes, [f"A{i:02d}" for i in range(1, 13)])

    def test_stoplist_and_graveyard(self):
        self.assertGreaterEqual(db.count("registry_stoplist"), 6)
        kinds = {r["kind"] for r in db.query("SELECT DISTINCT kind FROM registry_changelog")}
        self.assertIn("graveyard", kinds)
        self.assertIn("critical_change", kinds)

    def test_paid_connectors_disabled_by_default(self):
        from isheika.config import SETTINGS
        self.assertFalse(SETTINGS.allow_paid_ai)
        for r in db.query("SELECT code, paid FROM registry_connectors WHERE paid=1"):
            self.assertTrue(r["paid"])

    def test_methodology_versioned(self):
        m = loader.methodology()
        self.assertTrue(m["version"].startswith("M-"))
        self.assertEqual(m["status"], "калибровка не завершена")
        self.assertTrue(m["trl"]["averaging_forbidden"])
        self.assertEqual(len(m["barriers"]["types"]), 11)
        self.assertEqual(len(m["forecast"]["horizons"]), 6)

    def test_seed_is_idempotent(self):
        before = db.count("registry_sources")
        loader.seed_all()
        self.assertEqual(db.count("registry_sources"), before)
