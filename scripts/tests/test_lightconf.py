"""Lauf-Config für audit-light."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from audit import lightconf
from tests import support


class TestPickPageTypes(unittest.TestCase):
    URLS = [
        "https://shop.de/collections/hosen",
        "https://shop.de/collections/hosen/latzhosen",
        "https://shop.de/products/latzhose-blau",
        "https://shop.de/cart",
        "https://shop.de/search?q=hose",
        "https://shop.de/blogs/ratgeber/pflege",
        "https://shop.de/pages/ueber-uns",
    ]

    def test_alle_sechs_typen_sind_schluessel(self):
        r = lightconf.pick_page_types(self.URLS, "https://shop.de")
        self.assertEqual(sorted(r), sorted(lightconf.PAGE_TYPES))

    def test_start_ist_immer_die_domain(self):
        r = lightconf.pick_page_types([], "https://shop.de")
        self.assertEqual(r["start"], "https://shop.de/")

    def test_erkennt_die_gaengigen_typen(self):
        r = lightconf.pick_page_types(self.URLS, "https://shop.de")
        self.assertEqual(r["product"], "https://shop.de/products/latzhose-blau")
        self.assertEqual(r["cart"], "https://shop.de/cart")
        self.assertEqual(r["search"], "https://shop.de/search?q=hose")
        self.assertEqual(r["blog"], "https://shop.de/blogs/ratgeber/pflege")

    def test_flachste_url_gewinnt(self):
        r = lightconf.pick_page_types(self.URLS, "https://shop.de")
        self.assertEqual(r["collection"], "https://shop.de/collections/hosen")

    def test_sammelseiten_werden_uebersprungen(self):
        # /collections/ selbst ist keine Kategorieseite mit Produkten.
        r = lightconf.pick_page_types(
            ["https://shop.de/collections/", "https://shop.de/collections/echte-kategorie"],
            "https://shop.de")
        self.assertEqual(r["collection"], "https://shop.de/collections/echte-kategorie")

    def test_alles_seite_wird_uebersprungen(self):
        # /collections/all ist eine echte Seite mit Produkten, aber keine
        # Kategorie: kein Filter, kein Kategorietext. Am echten Shop aufgefallen.
        r = lightconf.pick_page_types(
            ["https://shop.de/collections/all", "https://shop.de/collections/hosen"],
            "https://shop.de")
        self.assertEqual(r["collection"], "https://shop.de/collections/hosen")

    def test_alles_seite_allein_ergibt_keine_kategorie(self):
        r = lightconf.pick_page_types(["https://shop.de/collections/all"], "https://shop.de")
        self.assertIsNone(r["collection"])

    def test_nicht_gefundener_typ_bleibt_none(self):
        r = lightconf.pick_page_types(["https://shop.de/products/x"], "https://shop.de")
        self.assertIsNone(r["blog"])
        self.assertIsNone(r["cart"])

    def test_woocommerce_und_deutsche_pfade(self):
        r = lightconf.pick_page_types(
            ["https://shop.de/produkt/hose", "https://shop.de/warenkorb", "https://shop.de/suche"],
            "https://shop.de")
        self.assertEqual(r["product"], "https://shop.de/produkt/hose")
        self.assertEqual(r["cart"], "https://shop.de/warenkorb")
        self.assertEqual(r["search"], "https://shop.de/suche")

    def test_ein_typ_gewinnt_je_url(self):
        # /collections/x/products/y darf nicht in zwei Toepfen landen.
        r = lightconf.pick_page_types(["https://shop.de/collections/a/products/b"], "https://shop.de")
        treffer = [t for t, u in r.items() if u and t != "start"]
        self.assertEqual(len(treffer), 1)


class TestBrandQueries(unittest.TestCase):
    def test_drei_fragen(self):
        self.assertEqual(len(lightconf.brand_queries("Beispiel", "beispiel.de")), 3)

    def test_rechtsform_faellt_weg(self):
        q = lightconf.brand_queries("Martin Beispiel GmbH", "martin-beispiel.example")
        self.assertIn("Was ist Martin Beispiel?", q)

    def test_klammerzusatz_faellt_weg(self):
        q = lightconf.brand_queries("Handel GmbH (Marke Wohnlicht)", "lead-eins.example")
        self.assertTrue(all("Marke Wohnlicht" not in x for x in q))

    def test_leerer_name_faellt_auf_die_domain_zurueck(self):
        q = lightconf.brand_queries("", "musterhaus.example")
        self.assertIn("Was ist musterhaus?", q)


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)

    def test_kernfelder_stehen(self):
        c = lightconf.build("https://www.shop.de/x", "shop", brand="Shop GmbH")
        # www bleibt: der Shop kanonisiert darauf, und ein Crawl auf die
        # Nicht-www-Form wuerde die Weiterleitung mitmessen.
        self.assertEqual(c["domain"], "https://www.shop.de/x")
        self.assertEqual(c["account_slug"], "shop")
        self.assertEqual(c["drive_path"], str(self.root / "shop"))
        self.assertEqual(c["geo_method"], "api")

    def test_www_bleibt_in_der_lauf_domain(self):
        self.assertEqual(lightconf.build("https://www.shop.de", "shop", brand="S")["domain"],
                         "https://www.shop.de")

    def test_fehlendes_schema_wird_ergaenzt(self):
        self.assertEqual(lightconf.build("shop.de", "shop", brand="S")["domain"],
                         "https://shop.de")

    def test_abschliessender_schraegstrich_und_query_fallen_weg(self):
        self.assertEqual(lightconf.build("https://shop.de/?utm=x", "shop", brand="S")["domain"],
                         "https://shop.de")

    def test_kundenquellen_sind_aus(self):
        c = lightconf.build("shop.de", "shop", brand="Shop")
        for q in ("shopify", "ga4", "gsc", "ads", "catalogue", "shop_tech"):
            self.assertFalse(c["sources"][q], q)

    def test_bezahlte_quellen_sind_per_default_aus(self):
        c = lightconf.build("shop.de", "shop", brand="Shop")
        for q in ("dfs_rankings", "shopping", "backlinks", "dfs_keywords"):
            self.assertFalse(c["sources"][q], q)

    def test_with_dfs_schaltet_die_bezahlten_an(self):
        c = lightconf.build("shop.de", "shop", brand="Shop", with_dfs=True)
        self.assertTrue(c["sources"]["dfs_rankings"])
        self.assertTrue(c["sources"]["shopping"])

    def test_checkout_path_ist_per_default_aus(self):
        self.assertFalse(lightconf.build("shop.de", "shop", brand="S")["checkout_capture"])
        self.assertTrue(lightconf.build("shop.de", "shop", brand="S", checkout_path=True)["checkout_capture"])

    def test_audit_id_landet_in_der_config(self):
        # Ohne sie findet audit-light-send den Lauf und damit den Empfaenger nicht.
        c = lightconf.build("shop.de", "shop", brand="Shop", audit_id="abc-123")
        self.assertEqual(c["audit_id"], "abc-123")

    def test_ohne_audit_id_steht_none_statt_zu_fehlen(self):
        # Ein eigener Lauf ohne Lead ist gueltig, das Feld muss trotzdem da sein.
        c = lightconf.build("shop.de", "shop", brand="Shop")
        self.assertIn("audit_id", c)
        self.assertIsNone(c["audit_id"])

    def test_kategorie_und_problem_bleiben_leer(self):
        c = lightconf.build("shop.de", "shop", brand="Shop")
        self.assertEqual(c["geo_queries"]["category"], [])
        self.assertEqual(c["geo_queries"]["problem"], [])
        self.assertEqual(len(c["geo_queries"]["brand"]), 3)


class TestAddPageTypesUndMissing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        support.temp_accounts_root(self)
        self.cfg = lightconf.build("shop.de", "shop", brand="Shop")

    def _crawl(self, payload) -> str:
        p = os.path.join(self.tmp.name, "crawl.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return p

    def test_seitentypen_kommen_aus_dem_crawl(self):
        p = self._crawl({"pages": [{"url": "https://shop.de/products/x"},
                                   {"url": "https://shop.de/cart"}]})
        c = lightconf.add_page_types(self.cfg, p)
        self.assertEqual(c["page_types"]["product"], "https://shop.de/products/x")

    def test_fehlender_crawl_laesst_die_config_unveraendert(self):
        c = lightconf.add_page_types(self.cfg, os.path.join(self.tmp.name, "gibt-es-nicht.json"))
        self.assertEqual(list(c["page_types"]), ["start"])

    def test_kaputter_crawl_wirft_nicht(self):
        p = os.path.join(self.tmp.name, "kaputt.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{nicht json")
        self.assertEqual(lightconf.add_page_types(self.cfg, p), self.cfg)

    def test_missing_meldet_fehlende_kategorie_und_seitentypen(self):
        fehlt = lightconf.missing(self.cfg)
        self.assertTrue(any("geo_queries.category" in f for f in fehlt))
        self.assertTrue(any("page_types" in f for f in fehlt))

    def test_missing_ist_leer_wenn_alles_steht(self):
        p = self._crawl({"pages": [{"url": "https://shop.de/products/x"}]})
        c = lightconf.add_page_types(self.cfg, p)
        c = lightconf.set_geo_queries(c, ["Beste Latzhosen?"], ["Wo Arbeitshosen kaufen?"])
        self.assertEqual(lightconf.missing(c), [])

    def test_set_geo_queries_kappt_bei_drei(self):
        c = lightconf.set_geo_queries(self.cfg, ["a", "b", "c", "d"], [])
        self.assertEqual(len(c["geo_queries"]["category"]), 3)

    def test_set_geo_queries_laesst_die_marke_stehen(self):
        vorher = list(self.cfg["geo_queries"]["brand"])
        c = lightconf.set_geo_queries(self.cfg, ["x"], ["y"])
        self.assertEqual(c["geo_queries"]["brand"], vorher)

    def test_write_legt_ordner_an(self):
        goal = os.path.join(self.tmp.name, "lauf", "run-config.json")
        lightconf.write(self.cfg, goal)
        with open(goal, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["account_slug"], "shop")


class TestCli(unittest.TestCase):
    def test_an_unknown_customer_points_to_the_create_command(self):
        root = support.temp_accounts_root(self)
        environment = {**os.environ, "PTAI_ENV_FILE": str(root.parent / "keine-zentrale.env")}
        result = subprocess.run([sys.executable, "-m", "audit.lightconf", "beispielshop.example"],
                                cwd=Path(__file__).resolve().parents[1], env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("audit.account create beispielshop.example", result.stderr)
        self.assertNotIn("workos", result.stderr)


if __name__ == "__main__":
    unittest.main()
