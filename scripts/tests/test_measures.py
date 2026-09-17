"""Der Maßnahmen-Backlog als Zustand: stabile IDs, Statushistorie, Priorisierung."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit import measures


class TestMeasures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _create(self, backlog=None, **overrides):
        values = {
            "title": "Alt-Text ergänzen",
            "discipline": "seo",
            "evidence": "crawl.json > pages[0].images",
            "confidence": "confirmed",
            "leverage": "high",
            "effort": "small",
        }
        values.update(overrides)
        return measures.create(backlog if backlog is not None else measures.empty(), **values)

    # -- IDs -------------------------------------------------------------

    def test_first_id_is_m001(self):
        backlog = self._create()
        self.assertEqual(backlog["measures"][0]["id"], "M-001")

    def test_ids_are_sequential_after_nine_comes_m010(self):
        backlog = measures.empty()
        for _ in range(10):
            backlog = self._create(backlog, title="X")
        ids = [m["id"] for m in backlog["measures"]]
        self.assertEqual(ids[8], "M-009")
        self.assertEqual(ids[9], "M-010")

    def test_id_is_never_reused_after_deleting_the_last_measure(self):
        backlog = self._create(title="A", evidence="crawl.json > pages[0]")
        # Die einzige Maßnahme wird aus dem Bestand entfernt, der Zähler im
        # Dokument bleibt davon unberührt: er lebt in `next_id`, nicht in
        # der Länge der Liste.
        backlog["measures"] = [m for m in backlog["measures"] if m["id"] != "M-001"]
        backlog = self._create(backlog, title="B", evidence="crawl.json > pages[1]")
        self.assertEqual(backlog["measures"][-1]["id"], "M-002")

    def test_rejected_creation_consumes_no_id(self):
        backlog = measures.empty()
        with self.assertRaises(ValueError):
            self._create(backlog, evidence="")
        backlog = self._create(backlog)
        self.assertEqual(backlog["measures"][0]["id"], "M-001")

    # -- Pflichtfelder und Validierung -----------------------------------

    def test_without_evidence_raises(self):
        with self.assertRaises(ValueError):
            self._create(evidence="")

    def test_without_title_raises(self):
        with self.assertRaises(ValueError):
            self._create(title="")

    def test_without_discipline_raises(self):
        with self.assertRaises(ValueError):
            self._create(discipline="")

    def test_unknown_confidence_raises(self):
        with self.assertRaises(ValueError):
            self._create(confidence="vermutung")

    def test_unknown_leverage_raises(self):
        with self.assertRaises(ValueError):
            self._create(leverage="riesig")

    def test_unknown_effort_raises(self):
        with self.assertRaises(ValueError):
            self._create(effort="episch")

    def test_unknown_responsible_raises(self):
        with self.assertRaises(ValueError):
            self._create(responsible="Praktikant")

    def test_responsible_is_optional(self):
        backlog = self._create()
        self.assertIsNone(backlog["measures"][0]["responsible"])

    def test_responsible_is_carried_over(self):
        backlog = self._create(responsible="Customer")
        self.assertEqual(backlog["measures"][0]["responsible"], "Customer")

    def test_data_source_and_check_rule_are_optional(self):
        backlog = self._create()
        self.assertIsNone(backlog["measures"][0]["data_source"])
        self.assertIsNone(backlog["measures"][0]["check_rule"])

    def test_data_source_and_check_rule_are_carried_over(self):
        backlog = self._create(
            data_source="Shopify-Backend", check_rule="Katalog-Snapshot: alt_text ist gesetzt")
        entry = backlog["measures"][0]
        self.assertEqual(entry["data_source"], "Shopify-Backend")
        self.assertEqual(entry["check_rule"], "Katalog-Snapshot: alt_text ist gesetzt")

    # -- Status und Historie ----------------------------------------------

    def test_new_measure_has_status_open(self):
        backlog = self._create()
        self.assertEqual(backlog["measures"][0]["status"], "open")

    def test_new_measure_has_a_first_history_entry(self):
        backlog = self._create()
        history = backlog["measures"][0]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "open")

    def test_set_status_changes_status_and_appends_to_history(self):
        backlog = self._create()
        backlog = measures.set_status(backlog, "M-001", "implemented", today=date(2026, 10, 1))
        entry = backlog["measures"][0]
        self.assertEqual(entry["status"], "implemented")
        self.assertEqual(len(entry["history"]), 2)
        self.assertEqual(entry["history"][-1], {"status": "implemented", "date": "2026-10-01"})
        # Der erste Eintrag bleibt erhalten, die Historie wird nie ersetzt.
        self.assertEqual(entry["history"][0]["status"], "open")

    def test_set_status_with_unknown_status_raises(self):
        backlog = self._create()
        with self.assertRaises(ValueError):
            measures.set_status(backlog, "M-001", "erledigt")

    def test_set_status_with_unknown_id_raises(self):
        backlog = self._create()
        with self.assertRaises(ValueError):
            measures.set_status(backlog, "M-999", "implemented")

    def test_set_status_leaves_other_measures_unchanged(self):
        backlog = self._create(title="A")
        backlog = self._create(backlog, title="B", evidence="crawl.json > pages[1]")
        backlog = measures.set_status(backlog, "M-001", "rejected")
        second = next(m for m in backlog["measures"] if m["id"] == "M-002")
        self.assertEqual(second["status"], "open")
        self.assertEqual(len(second["history"]), 1)

    # -- Typ (Maßnahme oder Test) -----------------------------------------

    def test_type_is_measure_when_confirmed(self):
        backlog = self._create(confidence="confirmed")
        self.assertEqual(backlog["measures"][0]["type"], "measure")

    def test_type_is_measure_when_plausible(self):
        backlog = self._create(confidence="plausible")
        self.assertEqual(backlog["measures"][0]["type"], "measure")

    def test_type_is_test_when_hypothesis(self):
        backlog = self._create(confidence="hypothesis")
        self.assertEqual(backlog["measures"][0]["type"], "test")

    # -- Priorisierung ------------------------------------------------------

    def test_hypothesis_is_not_prioritized(self):
        backlog = self._create(
            title="Preis testen", discipline="cro", evidence="ga4.json > funnel",
            confidence="hypothesis", leverage="medium", effort="small")
        prioritized = measures.prioritize(backlog)
        self.assertEqual(prioritized[0]["type"], "test")

    def test_prioritization_follows_confidence_before_leverage_before_effort(self):
        backlog = measures.empty()
        # Absichtlich in "falscher" Reihenfolge angelegt, damit die
        # Sortierung und nicht die Anlage-Reihenfolge geprüft wird.
        backlog = self._create(backlog, title="plausibel, hoch, klein",
                                evidence="a", confidence="plausible", leverage="high", effort="small")
        backlog = self._create(backlog, title="belegt, niedrig, gross",
                                evidence="b", confidence="confirmed", leverage="low", effort="large")
        backlog = self._create(backlog, title="belegt, hoch, klein",
                                evidence="c", confidence="confirmed", leverage="high", effort="small")
        prioritized = measures.prioritize(backlog)
        titles = [m["title"] for m in prioritized]
        self.assertEqual(titles, [
            "belegt, hoch, klein",
            "belegt, niedrig, gross",
            "plausibel, hoch, klein",
        ])

    def test_prioritization_keeps_tests_separate_behind_the_measures(self):
        backlog = measures.empty()
        backlog = self._create(backlog, title="Test", evidence="a", confidence="hypothesis",
                                leverage="low", effort="large")
        backlog = self._create(backlog, title="Maßnahme", evidence="b", confidence="plausible",
                                leverage="low", effort="large")
        prioritized = measures.prioritize(backlog)
        types = [m["type"] for m in prioritized]
        self.assertEqual(types, ["measure", "test"])

    def test_data_quality_stands_above_regardless_of_the_axes(self):
        backlog = measures.empty()
        backlog = self._create(backlog, title="starker Befund", discipline="seo",
                                evidence="a", confidence="confirmed", leverage="high", effort="small")
        backlog = self._create(backlog, title="Datenqualität", discipline="data_quality",
                                evidence="b", confidence="plausible", leverage="low", effort="large")
        prioritized = measures.prioritize(backlog)
        self.assertEqual(prioritized[0]["title"], "Datenqualität")

    # -- ID-Wiederverwendung, direkt vorgeführt ---------------------------

    def test_id_demonstration_deleting_the_middle_measure(self):
        backlog = measures.empty()
        backlog = self._create(backlog, title="A", evidence="a")
        backlog = self._create(backlog, title="B", evidence="b")
        backlog = self._create(backlog, title="C", evidence="c")
        backlog["measures"] = [m for m in backlog["measures"] if m["id"] != "M-002"]
        backlog = self._create(backlog, title="D", evidence="d")
        ids = [m["id"] for m in backlog["measures"]]
        self.assertEqual(ids, ["M-001", "M-003", "M-004"])

    # -- Persistenz ----------------------------------------------------------

    def test_load_or_empty_without_a_file_returns_an_empty_backlog(self):
        backlog = measures.load_or_empty(self.ws)
        self.assertEqual(backlog, measures.empty())

    def test_save_and_load_yield_the_same_backlog(self):
        backlog = self._create()
        measures.save(self.ws, backlog)
        loaded = measures.load(self.ws)
        self.assertEqual(loaded, backlog)

    def test_save_creates_the_file_under_reporting(self):
        backlog = self._create()
        path = measures.save(self.ws, backlog)
        self.assertEqual(path, self.ws / "reporting" / "measures.json")
        self.assertTrue(path.exists())

    def test_loading_a_corrupt_file_aborts_with_a_message(self):
        path = self.ws / "reporting" / "measures.json"
        path.parent.mkdir(parents=True)
        path.write_text("{kaputt", encoding="utf-8")
        with self.assertRaises(ValueError):
            measures.load_or_empty(self.ws)

    # -- check() -----------------------------------------------------------

    def test_check_returns_implemented_when_this_run_confirms_the_rule(self):
        backlog = self._create(check_rule="Katalog-Snapshot: alt_text ist gesetzt")
        measure = backlog["measures"][0]
        self.assertEqual(measures.check(measure, {measure["id"]: True}), "implemented")

    def test_check_returns_open_when_this_run_denies_the_rule(self):
        backlog = self._create(check_rule="Katalog-Snapshot: alt_text ist gesetzt")
        measure = backlog["measures"][0]
        self.assertEqual(measures.check(measure, {measure["id"]: False}), "open")

    def test_check_returns_unchecked_when_the_source_was_not_due(self):
        # Die Maßnahme hat eine Prüfregel, aber dieser Lauf hat die dafür
        # nötige Quelle nicht gezogen: sie taucht in den Snapshots des Laufs
        # schlicht nicht auf.
        backlog = self._create(check_rule="Katalog-Snapshot: alt_text ist gesetzt")
        measure = backlog["measures"][0]
        self.assertEqual(measures.check(measure, {}), "unchecked")

    def test_check_does_not_fall_back_to_open_when_another_measure_was_checked(self):
        # Der Fall, der zählt: in diesem Lauf wurden andere Maßnahmen
        # geprüft, diese hier nicht, weil ihre Quelle nicht fällig war. Das
        # Ergebnis darf nicht mit "open" verwechselbar sein, sonst behauptet
        # der Backlog einen Rückschritt, den niemand gemessen hat.
        backlog = self._create(title="A", evidence="a", check_rule="Crawl: Weiterleitung ist weg")
        backlog = self._create(backlog, title="B", evidence="b", check_rule="GSC: Ranking zurück")
        measure_a, measure_b = backlog["measures"]
        result = measures.check(measure_b, {measure_a["id"]: False})
        self.assertEqual(result, "unchecked")
        self.assertNotEqual(result, "open")

    def test_check_without_a_check_rule_is_always_unchecked(self):
        # Ohne Prüfregel kann kein Lauf je feststellen, ob eine Maßnahme
        # umgesetzt ist. Selbst ein mitgeliefertes Ergebnis darf das nicht
        # in "implemented" verwandeln, sonst wäre die Prüfregel-Pflicht aus
        # `create()` wirkungslos.
        backlog = self._create(check_rule=None)
        measure = backlog["measures"][0]
        self.assertEqual(measures.check(measure, {measure["id"]: True}), "unchecked")

    # -- render() ------------------------------------------------------------

    def _render(self) -> str:
        return measures.render(self.ws).read_text(encoding="utf-8")

    def test_render_without_a_prior_save_shows_empty_sections(self):
        # measures.json existiert noch gar nicht, render() muss trotzdem
        # ein leeres Dokument zeigen, genau wie baseline.render().
        markdown = self._render()
        self.assertIn("Keine Maßnahmen.", markdown)
        self.assertIn("Keine Tests.", markdown)

    def test_render_lists_measures_in_priority_order(self):
        backlog = measures.empty()
        backlog = self._create(backlog, title="niedrig", evidence="a",
                                confidence="plausible", leverage="low", effort="large")
        backlog = self._create(backlog, title="hoch", evidence="b",
                                confidence="confirmed", leverage="high", effort="small")
        measures.save(self.ws, backlog)
        markdown = self._render()
        section = markdown[:markdown.index("## Tests")]
        self.assertLess(section.index("hoch"), section.index("niedrig"))

    def test_render_shows_status_and_date_of_last_change(self):
        backlog = self._create()
        backlog = measures.set_status(backlog, "M-001", "implemented", today=date(2026, 10, 3))
        measures.save(self.ws, backlog)
        markdown = self._render()
        section = markdown[:markdown.index("## Tests")]
        # Das Dokument liest der Kunde, dort steht das deutsche Wort.
        self.assertIn("umgesetzt", section)
        self.assertNotIn("implemented", section)
        self.assertIn("2026-10-03", section)

    def test_render_keeps_tests_out_of_the_measures_section(self):
        backlog = self._create(title="echte Maßnahme", evidence="a")
        backlog = self._create(backlog, title="Preis testen", discipline="cro",
                                evidence="b", confidence="hypothesis",
                                leverage="medium", effort="small")
        measures.save(self.ws, backlog)
        markdown = self._render()
        section_measures = markdown[:markdown.index("## Tests")]
        section_tests = markdown[markdown.index("## Tests"):]
        self.assertIn("echte Maßnahme", section_measures)
        self.assertNotIn("Preis testen", section_measures)
        self.assertIn("Preis testen", section_tests)

    def test_render_writes_measures_md_next_to_measures_json(self):
        backlog = self._create()
        measures.save(self.ws, backlog)
        path = measures.render(self.ws)
        self.assertEqual(path, self.ws / "reporting" / "measures.md")
        self.assertTrue(path.exists())


class TestGermanLabels(unittest.TestCase):
    """measures.md liest der Kunde. Dort steht kein "low" und kein
    "in_progress"."""

    def test_values_appear_in_german_in_the_document(self):
        backlog = measures.create(
            measures.empty(), title="Alt-Texte ergänzen", discipline="seo",
            evidence="crawl.json > pages[0]", confidence="confirmed",
            leverage="low", effort="large", responsible="Customer",
            today=date(2026, 10, 1))
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            measures.save(ws, backlog)
            text = measures.render(ws).read_text(encoding="utf-8")
        self.assertIn("niedrig", text)
        self.assertIn("groß", text)
        self.assertIn("Kunde", text)
        self.assertNotIn("low", text)
        self.assertNotIn("large", text)

    def test_unknown_value_does_not_disappear(self):
        self.assertEqual(measures._label("leverage", "gibt_es_nicht"), "gibt_es_nicht")


if __name__ == "__main__":
    unittest.main()


class TestSaveRefusesTheWrongType(unittest.TestCase):
    """prioritize() liefert eine Liste, save() erwartet das Dokument."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_list_is_refused(self):
        backlog = measures.create(
            measures.empty(), title="Alt-Text ergänzen", discipline="seo_technical",
            evidence="crawl.json > pages[].images", confidence="confirmed",
            leverage="medium", effort="small", check_rule="Anteil sinkt",
            today=date(2026, 10, 1))
        with self.assertRaises(ValueError) as ctx:
            measures.save(self.ws, measures.prioritize(backlog))
        self.assertIn("prioritize()", str(ctx.exception))

    def test_the_document_is_accepted(self):
        backlog = measures.empty()
        measures.save(self.ws, backlog)
        self.assertEqual(measures.load(self.ws)["measures"], [])
