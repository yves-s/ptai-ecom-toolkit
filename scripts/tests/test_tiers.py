"""Einstufung der Quellen (Spec 2026-09-11, Abschnitt 3)."""
import subprocess
import sys
import unittest
from pathlib import Path

from audit import run, tiers

SCRIPTS = Path(__file__).resolve().parents[1]


class TestTable(unittest.TestCase):
    def test_every_run_source_appears_exactly_once(self):
        # Kommt eine Lauf-Quelle dazu, scheitert dieser Test, bis sie eingestuft ist.
        seen = [rs for s in tiers.SOURCES for rs in s.run_sources] + list(tiers.UNTIERED)
        self.assertEqual(sorted(seen), sorted(run.SOURCE_CADENCE))
        self.assertEqual(len(seen), len(set(seen)))

    def test_only_known_tiers_and_providers(self):
        for s in tiers.SOURCES:
            self.assertIn(s.tier, tiers.TIERS, s.key)
            self.assertIn(s.provider, tiers.PROVIDERS, s.key)

    def test_keys_and_labels_are_unique(self):
        self.assertEqual(len({s.key for s in tiers.SOURCES}), len(tiers.SOURCES))
        self.assertEqual(len({s.label for s in tiers.SOURCES}), len(tiers.SOURCES))

    def test_without_is_customer_language(self):
        for s in tiers.SOURCES:
            self.assertTrue(s.without.strip(), s.key)
            self.assertNotIn(".json", s.without, s.key)
            self.assertNotIn("`", s.without, s.key)
            self.assertNotIn("_", s.without, s.key)
            self.assertNotIn("/", s.without, s.key)

    def test_required_sources(self):
        self.assertEqual({s.key for s in tiers.SOURCES if s.tier == "required"},
                         {"shopify", "ga4", "gsc"})

    def test_keys_used_by_check_env_are_stable(self):
        # check_env.sh ruft source_section mit genau diesen Schlüsseln auf. Ein
        # umbenannter Schlüssel fiele dort still in die gezählte Gruppe "Quellen".
        self.assertEqual({s.key for s in tiers.SOURCES},
                         {"shopify", "ga4", "gsc", "dataforseo", "pagespeed", "geo", "ads"})


class TestLookup(unittest.TestCase):
    def test_by_key(self):
        self.assertEqual(tiers.by_key("dataforseo").tier, "recommended")

    def test_by_key_unknown_raises(self):
        with self.assertRaises(KeyError):
            tiers.by_key("klaviyo")

    def test_for_run_source(self):
        self.assertEqual(tiers.for_run_source("catalogue").key, "shopify")
        self.assertEqual(tiers.for_run_source("cwv_lab").key, "pagespeed")

    def test_untiered_run_source_gives_none(self):
        self.assertIsNone(tiers.for_run_source("crawl"))

    def test_unknown_run_source_raises(self):
        with self.assertRaises(KeyError):
            tiers.for_run_source("gsc_typo")


class TestCli(unittest.TestCase):
    def test_seven_tab_separated_columns_per_source(self):
        out = subprocess.run([sys.executable, "-m", "audit.tiers"], cwd=SCRIPTS,
                             capture_output=True, text=True, check=True).stdout
        rows = [line.split("\t") for line in out.splitlines()]
        self.assertEqual(len(rows), len(tiers.SOURCES))
        for row in rows:
            self.assertEqual(len(row), 7, row)
        shopify = next(r for r in rows if r[0] == "shopify")
        self.assertEqual(shopify[1:6], ["required", "Pflicht", "Shopify", "both",
                                        "shopify,catalogue,shop_tech"])


if __name__ == "__main__":
    unittest.main()
