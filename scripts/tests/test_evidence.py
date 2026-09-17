"""Belegprüfung: löst jeder Beleg eines Befunds auf sein Quellfeld auf?"""
import json
import tempfile
import unittest
from pathlib import Path

from audit import evidence


class TestSplitAndClassify(unittest.TestCase):
    def test_semicolon_separates_claims(self):
        claims = evidence.split_claims("a.json > x; b.json > y")
        self.assertEqual(claims, ["a.json > x", "b.json > y"])

    def test_comma_does_not_separate(self):
        # Ein Komma steht innerhalb einer Erläuterung und darf nicht trennen.
        claims = evidence.split_claims("crawl.json > pages[] (url, status 200)")
        self.assertEqual(len(claims), 1)

    def test_empty_evidence_yields_nothing(self):
        self.assertEqual(evidence.split_claims(""), [])
        self.assertEqual(evidence.split_claims(None), [])

    def test_file_claim_keeps_only_the_path(self):
        c = evidence.classify("crawl.json > findings_index.errors (by_status.404)")
        self.assertEqual(c["kind"], "file")
        self.assertEqual(c["file"], "crawl.json")
        self.assertEqual(c["path"], "findings_index.errors")

    def test_the_word_mit_ends_the_path(self):
        c = evidence.classify("geo.json > queries[] mit group=brand")
        self.assertEqual(c["path"], "queries[]")

    def test_image_claim_is_recognised(self):
        c = evidence.classify("start-desktop.png (Ankündigungsleiste)")
        self.assertEqual(c["kind"], "image")
        self.assertEqual(c["file"], "start-desktop.png")

    def test_url_claim_is_external(self):
        self.assertEqual(evidence.classify("https://example.test/x")["kind"], "url")

    def test_free_text_is_prose(self):
        c = evidence.classify("eigene Messung mit PageSpeed Insights am 08.09.2026")
        self.assertEqual(c["kind"], "prose")


class TestPathEndsAtSpaceOrComma(unittest.TestCase):
    """Wie die Analysen Belege wirklich schreiben.

    Alle Fälle hier stammen aus dem Lauf vom 08.09.2026, in dem die erste
    Fassung des Parsers zwölf Fehlalarme erzeugt hat. Eine Liste von
    Füllwörtern fängt nur, woran jemand gedacht hat.
    """

    def test_a_trailing_explanation_is_cut(self):
        c = evidence.classify("crawl.json > pages[].description, exakter "
                              "Textvergleich gegen die Startseite")
        self.assertEqual(c["path"], "pages[].description")

    def test_sibling_fields_do_not_bleed_into_the_path(self):
        c = evidence.classify("shop-tech.json > locales, markets")
        self.assertEqual(c["path"], "locales")

    def test_the_word_ist_ends_the_path(self):
        c = evidence.classify("geo.json > competitors ist leer, die "
                              "Einordnung erfolgte nach Domainnamen")
        self.assertEqual(c["path"], "competitors")

    def test_a_filter_description_ends_the_path(self):
        c = evidence.classify("crawl.json > pages[] gefiltert auf "
                              "/collections/ ohne /products/: h1, description")
        self.assertEqual(c["path"], "pages[]")

    def test_a_screenshot_named_via_the_index_is_an_image(self):
        # Die Analysen schreiben Bildbelege als "screens.json > bild.png",
        # weil der Index nun einmal so heisst. Als Feldpfad gelesen schlägt
        # jeder davon fehl: images[] trägt keinen Schlüssel je Dateiname.
        c = evidence.classify("screens.json > product-mobil.png (Kaufbutton)")
        self.assertEqual(c["kind"], "image")
        self.assertEqual(c["file"], "product-mobil.png")

    def test_the_first_of_several_screenshots_counts(self):
        c = evidence.classify("screens.json > start-desktop.png, "
                              "cart-desktop.png (Cookie-Dialog)")
        self.assertEqual((c["kind"], c["file"]), ("image", "start-desktop.png"))

    def test_slash_alternatives_survive_because_they_have_no_space(self):
        c = evidence.classify("catalog.json > summary.length_p10/p50/p90")
        self.assertEqual(c["path"], "summary.length_p10/p50/p90")


class TestResolve(unittest.TestCase):
    SNAP = {
        "summary": {"products_total": 12, "description_length_p10": 4},
        "pages": [{"url": "/a"}, {"url": "/b", "hreflang": ["de"]}],
        "compare_properties": [{"property_id": "1", "by_month": []}],
    }

    def test_plain_path_resolves(self):
        self.assertTrue(evidence.resolve(self.SNAP, "summary.products_total"))

    def test_missing_field_does_not_resolve(self):
        self.assertFalse(evidence.resolve(self.SNAP, "summary.does_not_exist"))

    def test_empty_path_means_the_whole_file(self):
        self.assertTrue(evidence.resolve(self.SNAP, ""))

    def test_list_notation_finds_a_field_in_any_element(self):
        # `pages[].hreflang` steht nur im zweiten Element und gilt trotzdem.
        self.assertTrue(evidence.resolve(self.SNAP, "pages[].hreflang"))

    def test_list_notation_fails_when_no_element_has_it(self):
        self.assertFalse(evidence.resolve(self.SNAP, "pages[].nonsense"))

    def test_index_notation_descends_into_that_element(self):
        self.assertTrue(
            evidence.resolve(self.SNAP, "compare_properties[0].by_month"))

    def test_index_beyond_the_end_does_not_resolve(self):
        self.assertFalse(
            evidence.resolve(self.SNAP, "compare_properties[3].by_month"))

    def test_an_empty_list_is_still_a_field_that_exists(self):
        # "competitors ist leer" kann selbst der Befund sein. Ein leeres Feld
        # als fehlend zu melden macht aus einer Aussage einen Fehlalarm.
        self.assertTrue(evidence.resolve({"competitors": []}, "competitors"))

    def test_slash_alternatives_check_the_written_out_one(self):
        # "p10/p50/p90" ist ein menschliches Kürzel für drei Geschwisterfelder.
        # Geprüft wird das ausgeschriebene, sonst schlägt der Prüfer Fehlalarm.
        self.assertTrue(
            evidence.resolve(self.SNAP, "summary.description_length_p10/p50/p90"))


class TestCheckRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        self.data = self.ws / "reporting" / "data" / self.run_id
        self.runs = self.ws / "reporting" / "runs" / self.run_id
        (self.runs / "findings").mkdir(parents=True)
        self.data.mkdir(parents=True)
        (self.data / "crawl.json").write_text(
            json.dumps({"summary": {"url_count": 10}}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _finding(self, evidence_text, finding_id="TEC-01"):
        (self.runs / "findings" / "seo-technical.json").write_text(json.dumps({
            "discipline": "seo_technical", "run_id": self.run_id,
            "findings": [{"id": finding_id, "statement": "x",
                          "evidence": evidence_text, "severity": "hoch",
                          "confidence": "confirmed", "effort": "small"}],
        }), encoding="utf-8")

    def test_a_resolvable_claim_is_clean(self):
        self._finding("crawl.json > summary.url_count")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["counts"]["resolved"], 1)

    def test_a_missing_field_becomes_a_problem(self):
        self._finding("crawl.json > summary.invented_number")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(len(result["problems"]), 1)
        self.assertEqual(result["problems"][0]["verdict"], "missing_field")
        self.assertEqual(result["problems"][0]["id"], "TEC-01")

    def test_a_missing_snapshot_becomes_a_problem(self):
        self._finding("ads.json > summary.spend")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"][0]["verdict"], "missing_file")

    def test_an_image_not_in_the_index_becomes_a_problem(self):
        # Der belegte Fall vom 08.09.2026: der Befund nennt einen Dateinamen,
        # den der Screenshot-Index nicht führt.
        self._finding("checkout-warenkorb.png (Warenkorb)", finding_id="CRO-01")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"][0]["verdict"], "missing_image")

    def test_an_indexed_image_without_a_file_becomes_a_problem(self):
        # Der Index nennt sie, die Platte hat sie nicht. Ohne diese Prüfung
        # sieht ein Befund über ein nie aufgenommenes Bild belegt aus.
        (self.runs / "screens.json").write_text(json.dumps({
            "images": [{"page_type": "cart", "device": "desktop",
                        "path": str(self.ws / "nirgends" / "cart.png")}]},
        ), encoding="utf-8")
        self._finding("cart.png (Warenkorb)", finding_id="CRO-02")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"][0]["verdict"], "missing_image")

    def test_an_indexed_image_that_exists_resolves(self):
        image = self.ws / "cart.png"
        image.write_bytes(b"\x89PNG")
        (self.runs / "screens.json").write_text(json.dumps({
            "images": [{"page_type": "cart", "device": "desktop",
                        "path": str(image)}]}), encoding="utf-8")
        self._finding("cart.png (Warenkorb)")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"], [])

    def test_prose_and_urls_are_not_problems(self):
        self._finding("eigene Messung am 08.09.2026; https://example.test/x")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["counts"]["prose"], 1)
        self.assertEqual(result["counts"]["external"], 1)

    def test_a_run_without_findings_is_clean(self):
        result = evidence.check_run(self.ws, "2026-11-01-audit")
        self.assertEqual(result["findings"], 0)
        self.assertEqual(result["problems"], [])

    def test_broken_json_is_reported_instead_of_raising(self):
        (self.runs / "findings" / "kaputt.json").write_text("{", encoding="utf-8")
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(len(result["problems"]), 1)

    def test_the_cli_returns_one_when_a_claim_points_nowhere(self):
        self._finding("crawl.json > summary.invented_number")
        code = evidence.main(["--workspace", str(self.ws), "--run-id", self.run_id])
        self.assertEqual(code, 1)

    def test_the_cli_returns_zero_when_everything_resolves(self):
        self._finding("crawl.json > summary.url_count")
        code = evidence.main(["--workspace", str(self.ws), "--run-id", self.run_id])
        self.assertEqual(code, 0)


class TestCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        self.findings = self.ws / "reporting" / "runs" / self.run_id / "findings"
        self.findings.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, discipline, findings, blocked):
        (self.findings / name).write_text(json.dumps({
            "discipline": discipline,
            "blocked_questions": [f"q{i}" for i in range(blocked)],
            "findings": [{"id": f"X-{i}", "statement": "x", "evidence": "",
                          "severity": "hoch", "confidence": "confirmed",
                          "effort": "small"} for i in range(findings)],
        }), encoding="utf-8")

    def test_more_blocked_than_answered_is_thin(self):
        # Der belegte Fall: vier Befunde, fünf offene Fragen.
        self._write("conversion.json", "cro", findings=4, blocked=5)
        entry = evidence.check_coverage(self.ws, self.run_id)[0]
        self.assertTrue(entry["thin"])
        self.assertEqual(entry["discipline"], "cro")

    def test_equal_counts_are_thin_as_well(self):
        self._write("geo.json", "geo", findings=3, blocked=3)
        self.assertTrue(evidence.check_coverage(self.ws, self.run_id)[0]["thin"])

    def test_more_answered_than_blocked_is_fine(self):
        self._write("commerce.json", "commerce", findings=5, blocked=4)
        self.assertFalse(evidence.check_coverage(self.ws, self.run_id)[0]["thin"])

    def test_no_blocked_questions_is_never_thin(self):
        # Eine Analyse ohne Befunde und ohne offene Fragen hat schlicht nichts
        # gefunden. Das ist eine Aussage über den Shop, keine Lücke im Lauf.
        self._write("traffic.json", "traffic", findings=0, blocked=0)
        self.assertFalse(evidence.check_coverage(self.ws, self.run_id)[0]["thin"])

    def test_coverage_rides_along_in_the_run_result(self):
        self._write("conversion.json", "cro", findings=1, blocked=2)
        result = evidence.check_run(self.ws, self.run_id)
        self.assertEqual(len(result["coverage"]), 1)
        self.assertTrue(result["coverage"][0]["thin"])

    def test_a_thin_analysis_alone_does_not_fail_the_run(self):
        # Eine fehlende Quelle ist ein legitimer Zustand und bricht nichts ab.
        # Sichtbar sein muss sie trotzdem.
        self._write("conversion.json", "cro", findings=1, blocked=2)
        code = evidence.main(["--workspace", str(self.ws), "--run-id", self.run_id])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()


class TestKeysWithDots(unittest.TestCase):
    """Ein Schlüssel darf selbst Punkte enthalten."""

    SNAP = {"storefront_script_hosts": {"cdn.intelligems.io": 3059,
                                        "a.klaviyo.com": 3059},
            "summary": {"url_count": 3500}}

    def test_a_hostname_key_resolves(self):
        # Der belegte Fall: die Zuordnung Host auf Seitenzahl. Am Punkt zu
        # trennen meldet einen korrekten Beleg als fehlendes Feld.
        self.assertTrue(evidence.resolve(
            self.SNAP, "storefront_script_hosts.cdn.intelligems.io"))

    def test_a_missing_hostname_key_does_not_resolve(self):
        self.assertFalse(evidence.resolve(
            self.SNAP, "storefront_script_hosts.cdn.erfunden.io"))

    def test_a_normal_path_still_works(self):
        self.assertTrue(evidence.resolve(self.SNAP, "summary.url_count"))
        self.assertFalse(evidence.resolve(self.SNAP, "summary.nonsense"))


class TestEvidenceLabel(unittest.TestCase):
    """Der Beleg im Kundendokument nennt die Quelle, nicht den Dateipfad."""

    def label(self, roh):
        from audit.report_build import evidence_label
        return evidence_label(roh)

    def test_a_snapshot_path_becomes_its_source(self):
        self.assertEqual(self.label("ga4.json > totals.sessions"),
                         "Google Analytics 4")

    def test_repeated_paths_into_one_file_name_it_once(self):
        # Der belegte Fall: drei Verweise in dieselbe Datei ergaben drei
        # Nennungen derselben Quelle.
        self.assertEqual(
            self.label("ga4.json > by_month; ga4.json > totals; shopify.json > by_month"),
            "Google Analytics 4; Shopify")

    def test_text_already_in_customer_language_survives(self):
        roh = "Screenshot start-desktop.png (Cookie-Dialog); Rohquelltext der Startseite"
        self.assertEqual(self.label(roh), roh)

    def test_an_unknown_snapshot_keeps_its_name(self):
        self.assertEqual(self.label("neu.json > feld"), "neu.json")

    def test_empty_stays_empty(self):
        self.assertEqual(self.label(""), "")
        self.assertEqual(self.label(None), "")

    def test_no_pipeline_word_survives_a_real_claim(self):
        roh = ("crawl.json > summary.third_party_script_hosts; "
               "crawl.json > findings_index.script_hosts (cdn.intelligems.io)")
        out = self.label(roh)
        self.assertNotIn(".json", out)
        self.assertIn("Seiten-Erfassung", out)
