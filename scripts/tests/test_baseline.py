"""Blockweises Schreiben und Einfrieren der Baseline."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit import baseline

#: Woher die Zahlen eines Blocks stammen, so wie der Orchestrator es aus
#: `state.json` und dem Snapshot zusammenstellt.
SOURCES = {
    "shopify": {"pulled_at": "2026-10-01",
                 "period": {"start": "2019-03-01", "end": "2026-09-30",
                            "granularity": "max_history"}},
}


#: Ein sauberes Prüfergebnis, wie gates.price_test_verdict() es liefert.
CLEAN_PRICE_TEST = {"checked": True, "running": False,
                     "evidence": "Kein bekanntes Preistest-Werkzeug im Crawl gefunden."}


class TestPriceTestGate(unittest.TestCase):
    """Der Conversion-Block darf unter laufendem Preistest nicht eingefroren
    werden. Geprüft wird nicht, ob der Aufrufer blockiert, sondern ob er die
    Prüfung überhaupt gemacht hat: eine fehlende Angabe ist der Fehler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, price_test):
        return baseline.write_block(
            self.ws, "conversion", {"cr": 0.021}, run_id="2026-10-01-audit",
            today=date(2026, 10, 1), trust={}, sources=SOURCES, price_test=price_test)

    def test_missing_check_is_the_error(self):
        # Der Kern: Vergessen scheitert. Ein Parameter, den der Aufrufer selbst
        # auf "blockiert" setzen müsste, erzwingt nichts, weil wer den Test
        # kennt, gar nicht erst schreibt.
        with self.assertRaises(ValueError) as caught:
            self._write(None)
        self.assertIn("price_test", str(caught.exception))

    def test_running_price_test_blocks_the_block(self):
        with self.assertRaises(baseline.PriceTestRunning):
            self._write({"checked": True, "running": True,
                          "evidence": "Tag intelligems-abc auf 312 Seiten"})

    def test_evidence_is_carried_into_the_message(self):
        with self.assertRaises(baseline.PriceTestRunning) as caught:
            self._write({"checked": True, "running": True,
                          "evidence": "Tag intelligems-abc auf 312 Seiten"})
        self.assertIn("312", str(caught.exception))

    def test_unchecked_verdict_is_refused_too(self):
        # "Nicht geprüft" ist keine Freigabe. Ohne Crawl weiß niemand, ob ein
        # Test lief, und der Block ist danach unveränderlich.
        with self.assertRaises(ValueError):
            self._write({"checked": False, "running": False,
                          "evidence": "Kein Crawl im Lauf"})

    def test_clean_verdict_lets_the_block_through(self):
        self._write({"checked": True, "running": False,
                      "evidence": "Kein bekanntes Preistest-Werkzeug gefunden"})
        self.assertIn("conversion", baseline.load(self.ws)["blocks"])

    def test_the_verdict_is_stored_with_the_block(self):
        # Der Beleg gehört in die Baseline, nicht nur in die Laufausgabe: wer
        # in einem Jahr fragt, warum diese Conversion als Nullpunkt gilt,
        # findet die Antwort im Block.
        self._write({"checked": True, "running": False,
                      "evidence": "Kein bekanntes Preistest-Werkzeug gefunden"})
        as_of = baseline.load(self.ws)["blocks"]["conversion"]["as_of"]
        self.assertIn("bekanntes", as_of["price_test"]["evidence"])

    def test_other_blocks_do_not_need_the_check(self):
        # Die Sperre gilt der Conversion. Ein Ranking oder ein Crawl-Befund
        # ist von einem Preistest nicht betroffen.
        baseline.write_block(self.ws, "geo", {"treffer": 3},
                              run_id="r", today=date(2026, 10, 1), trust={}, sources=SOURCES)
        self.assertIn("geo", baseline.load(self.ws)["blocks"])


class TestBaseline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, block="commerce", values=None, run="2026-10-01-audit", sources=None,
               known_gaps=()):
        # Die preistest-empfindlichen Blöcke brauchen das Prüfergebnis,
        # genau wie im echten Lauf. Die übrigen nicht.
        extra = ({"price_test": CLEAN_PRICE_TEST}
                  if block in baseline.PRICE_TEST_SENSITIVE else {})
        return baseline.write_block(
            self.ws, block, values or {"umsatz": 1000}, run_id=run,
            today=date(2026, 10, 1), trust={}, sources=sources or SOURCES,
            known_gaps=known_gaps, **extra)

    def test_first_block_is_written(self):
        self._write()
        b = baseline.load(self.ws)
        self.assertEqual(b["blocks"]["commerce"]["values"]["umsatz"], 1000)

    def test_block_carries_its_own_as_of(self):
        self._write()
        as_of = baseline.load(self.ws)["blocks"]["commerce"]["as_of"]
        self.assertEqual(as_of["written"], "2026-10-01")
        self.assertEqual(as_of["run_id"], "2026-10-01-audit")

    def test_as_of_separates_freezing_from_measuring(self):
        # Beim Nachtrag laufen die beiden Daten auseinander: die Zahlen sind
        # älter als der Tag, an dem sie festgeschrieben wurden. Ohne die
        # Trennung liest ein späterer Report das Festschreibedatum als
        # Erhebungsdatum und vergleicht gegen einen Zeitpunkt, an dem nie
        # gemessen wurde.
        baseline.write_block(
            self.ws, "traffic", {"sessions": 10}, run_id="2026-12-01-audit",
            today=date(2026, 12, 1), trust={},
            sources={"ga4": {"pulled_at": "2026-11-28"}})
        as_of = baseline.load(self.ws)["blocks"]["traffic"]["as_of"]
        self.assertEqual(as_of["written"], "2026-12-01")
        self.assertEqual(as_of["sources"]["ga4"]["pulled_at"], "2026-11-28")

    def test_as_of_keeps_the_covered_period(self):
        # Ohne den abgedeckten Zeitraum weiss ein späterer Report nicht,
        # wogegen er vergleicht: "Umsatz je Monat über die volle Historie"
        # ist ohne Anfang und Ende keine Aussage.
        self._write()
        period = baseline.load(self.ws)["blocks"]["commerce"]["as_of"]["sources"]["shopify"]["period"]
        self.assertEqual(period["start"], "2019-03-01")

    def test_block_without_sources_is_rejected(self):
        # Ein Block ohne Herkunft lässt sich später nicht nachprüfen, und
        # sein Festschreibedatum wird als Erhebungsdatum gelesen.
        with self.assertRaises(ValueError):
            baseline.write_block(self.ws, "geo", {"treffer": 1},
                                  run_id="r", today=date(2026, 10, 1), trust={}, sources={})

    def test_source_without_pull_date_is_rejected(self):
        with self.assertRaises(ValueError):
            baseline.write_block(self.ws, "geo", {"treffer": 1},
                                  run_id="r", today=date(2026, 10, 1), trust={},
                                  sources={"geo": {"period": {"start": "x"}}})

    def test_period_is_optional(self):
        # Screenshots und Crawl sind Momentaufnahmen ohne Zeitraum. Sie
        # dürfen keinen erfinden müssen.
        baseline.write_block(self.ws, "tech", {"lcp": 2.1}, run_id="r",
                              today=date(2026, 10, 1), trust={},
                              sources={"cwv": {"pulled_at": "2026-10-01"}})
        self.assertEqual(
            baseline.load(self.ws)["blocks"]["tech"]["as_of"]["sources"]["cwv"],
            {"pulled_at": "2026-10-01"})

    def test_written_block_is_not_overwritten(self):
        self._write()
        with self.assertRaises(baseline.BlockAlreadyWritten):
            self._write(values={"umsatz": 9999}, run="2026-11-01-audit")

    def test_value_stays_unchanged_after_rejected_overwrite(self):
        self._write()
        try:
            self._write(values={"umsatz": 9999})
        except baseline.BlockAlreadyWritten:
            pass
        self.assertEqual(baseline.load(self.ws)["blocks"]["commerce"]["values"]["umsatz"], 1000)

    def test_empty_blocks_are_named(self):
        self._write()
        empty = baseline.empty_blocks(self.ws)
        self.assertNotIn("commerce", empty)
        self.assertIn("sea", empty)

    def test_backfill_fills_only_what_is_empty(self):
        self._write()
        baseline.write_block(self.ws, "sea", {"ausgaben": 500},
                              run_id="2026-12-01-audit", today=date(2026, 12, 1), trust={},
                              sources={"ads": {"pulled_at": "2026-12-01"}})
        b = baseline.load(self.ws)
        self.assertEqual(b["blocks"]["commerce"]["as_of"]["run_id"], "2026-10-01-audit")
        self.assertEqual(b["blocks"]["sea"]["as_of"]["run_id"], "2026-12-01-audit")

    def test_block_without_values_is_rejected(self):
        # Sonst gilt der Block als geschrieben, ist für immer eingefroren und
        # enthält nichts: empty_blocks meldet ihn nicht mehr, --backfill
        # füllt ihn nie, und die Baseline gilt als vollständig.
        with self.assertRaises(ValueError):
            baseline.write_block(self.ws, "geo", {}, run_id="2026-10-01-audit",
                                  today=date(2026, 10, 1), trust={}, sources=SOURCES)

    def test_unknown_block_raises(self):
        with self.assertRaises(ValueError):
            self._write(block="zauberei")

    def test_baseline_lives_under_number_01(self):
        self._write()
        self.assertTrue((self.ws / "reporting" / "baseline" / "01" / "baseline.json").exists())

    def test_complete_only_once_no_block_is_empty(self):
        self.assertFalse(baseline.is_complete(self.ws))
        for block in baseline.BLOCKS:
            # conversion braucht zusätzlich die Preistest-Angabe, die übrigen
            # Blöcke nicht. Genau diese Ungleichbehandlung ist die Sperre.
            extra = ({"price_test": CLEAN_PRICE_TEST}
                      if block in baseline.PRICE_TEST_SENSITIVE else {})
            baseline.write_block(self.ws, block, {"x": 1}, run_id="2026-10-01-audit",
                                  today=date(2026, 10, 1), trust={}, sources=SOURCES, **extra)
        self.assertTrue(baseline.is_complete(self.ws))

    # -- render() -----------------------------------------------------

    def _render(self) -> str:
        return baseline.render(self.ws).read_text(encoding="utf-8")

    def test_render_has_a_heading_per_block_in_order(self):
        self._write()
        markdown = self._render()
        positions = [markdown.index(baseline.HEADINGS[block]) for block in baseline.BLOCKS]
        self.assertEqual(positions, sorted(positions))

    def test_render_without_a_prior_write_shows_all_blocks_empty(self):
        # baseline.json existiert noch gar nicht, render() muss trotzdem
        # alle zehn Blöcke als "noch nicht erhoben" zeigen.
        markdown = self._render()
        for block in baseline.BLOCKS:
            self.assertIn(baseline.HEADINGS[block], markdown)
        self.assertEqual(markdown.lower().count("noch nicht erhoben"), len(baseline.BLOCKS))

    def test_empty_block_shows_not_yet_collected(self):
        self._write()  # füllt nur "commerce"
        markdown = self._render()
        section_sea = markdown[markdown.index(baseline.HEADINGS["sea"]):]
        self.assertIn("noch nicht erhoben", section_sea.lower())

    def test_render_shows_measuring_and_freezing_date(self):
        # Im Kundendokument müssen beide Daten stehen. Sonst liest der
        # Leser das Festschreibedatum als den Tag, an dem gemessen wurde.
        baseline.write_block(
            self.ws, "traffic", {"sessions": 10}, run_id="2026-12-01-audit",
            today=date(2026, 12, 1), trust={},
            sources={"ga4": {"pulled_at": "2026-11-28",
                              "period": {"start": "2024-01-01", "end": "2026-11-27",
                                         "granularity": "max_history"}}})
        markdown = self._render()
        section = markdown[markdown.index(baseline.HEADINGS["traffic"]):]
        section = section[:section.index(baseline.HEADINGS["conversion"])]
        self.assertIn("2026-12-01", section)   # festgeschrieben
        self.assertIn("2026-11-28", section)   # erhoben
        self.assertIn("2024-01-01", section)   # Zeitraum

    def test_render_names_the_source_of_each_block(self):
        self._write()
        section = self._render()
        section = section[:section.index(baseline.HEADINGS["traffic"])]
        self.assertIn("shopify", section)

    def test_filled_block_shows_its_own_as_of(self):
        self._write(run="2026-10-01-audit")
        baseline.write_block(self.ws, "sea", {"ausgaben": 500},
                              run_id="2026-12-01-audit", today=date(2026, 12, 1), trust={},
                              sources={"ads": {"pulled_at": "2026-12-01"}})
        markdown = self._render()

        section_commerce = markdown[:markdown.index(baseline.HEADINGS["traffic"])]
        self.assertIn("2026-10-01", section_commerce)
        self.assertIn("2026-10-01-audit", section_commerce)

        sea_start = markdown.index(baseline.HEADINGS["sea"])
        sea_end = markdown.index(baseline.HEADINGS["tech"])
        section_sea = markdown[sea_start:sea_end]
        self.assertIn("2026-12-01", section_sea)
        self.assertIn("2026-12-01-audit", section_sea)
        # der Stand von "commerce" darf nicht in den Abschnitt von "sea" durchsickern
        self.assertNotIn("2026-10-01-audit", section_sea)

    def test_measured_zero_stays_distinct_from_empty_block(self):
        self._write(values={"umsatz": 0})
        markdown = self._render()
        section_commerce = markdown[:markdown.index(baseline.HEADINGS["traffic"])]
        self.assertIn("0", section_commerce)
        self.assertNotIn("noch nicht erhoben", section_commerce.lower())

    def test_monthly_values_appear_in_full(self):
        # Ein Block wie "Handel" trägt Zeitreihen (Umsatz je Monat), keine
        # Einzelzahl. Jeder Monat und jeder Wert muss im Dokument stehen.
        self._write(values={"umsatz_je_monat": {"2026-07": 12345, "2026-08": 23456}})
        markdown = self._render()
        self.assertIn("2026-07", markdown)
        self.assertIn("12345", markdown)
        self.assertIn("2026-08", markdown)
        self.assertIn("23456", markdown)

    def test_list_appears_in_full(self):
        # GEO-Query-Set und Wettbewerberliste sind Listen, kein Einzelwert.
        self._write(block="geo", values={"query_set": ["frage eins", "frage zwei"]})
        markdown = self._render()
        self.assertIn("frage eins", markdown)
        self.assertIn("frage zwei", markdown)

    def test_incalculable_value_is_not_silently_zero(self):
        self._write(values={"conversion_rate": None},
                    known_gaps=("conversion_rate",))
        markdown = self._render()
        section_commerce = markdown[:markdown.index(baseline.HEADINGS["traffic"])]
        self.assertNotIn("| conversion_rate | 0 |", section_commerce)
        self.assertNotIn("None", section_commerce)

    def test_boolean_value_is_rendered_in_german(self):
        self._write(block="geo", values={"llms_txt": True})
        markdown = self._render()
        self.assertIn("ja", markdown)
        self.assertNotIn("True", markdown)

    def test_render_writes_baseline_md_next_to_baseline_json(self):
        self._write()
        path = baseline.render(self.ws)
        self.assertEqual(path, self.ws / "reporting" / "baseline" / "01" / "baseline.md")
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()


class TestKnownGaps(unittest.TestCase):
    """Ein None ohne Anmeldung ist ein Tippfehler, kein dokumentierter Wert."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, values, known_gaps=()):
        return baseline.write_block(
            self.ws, "commerce", values, run_id="2026-10-01-audit",
            today=date(2026, 10, 1), trust={}, sources=SOURCES, known_gaps=known_gaps,
            price_test=CLEAN_PRICE_TEST)

    def test_unannounced_none_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self._write({"umsatz": 1000, "repeat_rate": None})
        self.assertIn("repeat_rate", str(ctx.exception))

    def test_announced_gap_is_written(self):
        self._write({"umsatz": 1000, "repeat_rate": None},
                    known_gaps=("repeat_rate",))
        block = baseline.load(self.ws)["blocks"]["commerce"]
        self.assertIsNone(block["values"]["repeat_rate"])

    def test_the_message_names_every_unannounced_field(self):
        with self.assertRaises(ValueError) as ctx:
            self._write({"umsatz": 1000, "a": None, "b": None},
                        known_gaps=("a",))
        self.assertIn("'b'", str(ctx.exception))
        self.assertNotIn("'a'", str(ctx.exception))


class TestMessqualitaet(unittest.TestCase):
    """Der Nullpunkt haelt fest, was der Shop ueber sich wusste, und dazu
    gehoert eine kaputte Messung. Gefaehrlich wird sie erst als Nenner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, values, trust, block="traffic"):
        return baseline.write_block(
            self.ws, block, values, run_id="2026-10-01-audit",
            today=date(2026, 10, 1), sources=SOURCES, trust=trust)

    def test_trust_ist_pflicht(self):
        """Dieselbe Mechanik wie price_test: erzwungen wird nicht ein Urteil,
        sondern dass der Aufrufer hingesehen hat."""
        with self.assertRaises(TypeError):
            baseline.write_block(self.ws, "traffic", {"sessions": 10},
                                 run_id="r", today=date(2026, 10, 1),
                                 sources=SOURCES)

    def test_ein_leeres_dict_heisst_alles_gemessen(self):
        self._write({"sessions": 10}, {})
        self.assertEqual(
            baseline.load(self.ws)["blocks"]["traffic"]["values"]["sessions"], 10)

    def test_eine_kaputte_zahl_wird_eingefroren_nicht_weggelassen(self):
        """Sie ist der Zustand, auf dem die Entscheidungen des Kunden beruhten.
        Ohne sie fehlt spaeter die Erklaerung fuer den Sprung nach der
        Reparatur."""
        self._write({"sessions": 2_897_045}, {
            "sessions": {"status": "contaminated",
                         "reason": "Analytics zaehlt 3,64-mal so viele Besuche",
                         "break": "2026-06", "finding": "MES-03"}})
        block = baseline.load(self.ws)["blocks"]["traffic"]
        self.assertEqual(block["values"]["sessions"], 2_897_045)
        vermerk = block["as_of"]["trust"]["sessions"]
        self.assertEqual(vermerk["status"], "contaminated")
        self.assertEqual(vermerk["break"], "2026-06")

    def test_eine_rechnung_auf_einer_kaputten_zahl_wird_abgelehnt(self):
        """Der Fall, der wirklich weh tut: eine Rate aus einer ueberhoehten
        Sitzungszahl sieht aus wie eine Kennzahl und vererbt den Fehler."""
        with self.assertRaises(baseline.ContaminatedInput):
            self._write({"sessions": 2_897_045, "conversion_rate": 0.0089}, {
                "sessions": {"status": "contaminated", "reason": "Faktor 3,64"},
                "conversion_rate": {"derived_from": ["sessions"]}})

    def test_eine_rechnung_auf_einer_gesunden_zahl_geht_durch(self):
        self._write({"orders": 100, "revenue": 5000, "aov": 50.0}, {
            "aov": {"derived_from": ["orders", "revenue"]}})
        self.assertEqual(
            baseline.load(self.ws)["blocks"]["traffic"]["values"]["aov"], 50.0)

    def test_kaputt_ohne_grund_wird_abgelehnt(self):
        """Ein Wert, dem niemand mehr ansieht, warum er falsch ist, ist nach dem
        Einfrieren nur noch eine seltsame Zahl."""
        with self.assertRaises(ValueError):
            self._write({"sessions": 10},
                        {"sessions": {"status": "contaminated"}})

    def test_ein_unbekannter_status_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            self._write({"sessions": 10}, {"sessions": {"status": "komisch"}})

    def test_ein_vermerk_auf_einen_wert_den_es_nicht_gibt_wirkt_nie(self):
        with self.assertRaises(ValueError):
            self._write({"sessions": 10}, {"besuche": {"status": "measured"}})


class TestRenderTrust(unittest.TestCase):
    """Ein eingefrorener Wert, der nachweislich falsch ist, darf in
    `baseline.md` nicht wie eine gewöhnliche Zahl aussehen. Bis zum
    12.09.2026 schrieb render() nur die Zahl, Grund, Bruch, Befund und die
    nachgetragenen Korrekturen standen allein in der JSON."""

    #: Jede Form, die `_render_values` kennt: einfache Werte, eine Liste aus
    #: Dicts, eine Zeitreihe und eine einfache Liste.
    VALUES = {
        "orders": 100,
        "purchases": 180,
        "estimated_traffic": 4200.5,
        "index_report": None,
        "channels": [{"channel": "Direct", "sessions": 10}],
        "monthly": {"2026-07": 5},
        "queries": ["frage eins", "frage zwei"],
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _render(self, trust) -> str:
        """Schreibt die JSON direkt statt über write_block: Korrekturen werden
        nach dem Einfrieren von Hand nachgetragen, und render() zeigt, was in
        der Datei steht. Zurück kommt der Abschnitt "Messung", der letzte."""
        as_of = {"written": "2026-10-01", "run_id": "2026-10-01-audit",
                 "sources": {"shopify": {"pulled_at": "2026-10-01"}}}
        if trust is not None:
            as_of["trust"] = trust
        blocks = {block: None for block in baseline.BLOCKS}
        blocks["measurement"] = {"values": self.VALUES, "as_of": as_of}
        path = self.ws / "reporting" / "baseline" / baseline.NUMBER / "baseline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"blocks": blocks}, ensure_ascii=False),
                        encoding="utf-8")
        markdown = baseline.render(self.ws).read_text(encoding="utf-8")
        return markdown[markdown.index("## " + baseline.HEADINGS["measurement"]):]

    def test_block_without_trust_renders_as_before(self):
        # Werte ohne Vermerk sehen Byte für Byte aus wie vor dem 12.09.2026.
        # Eine bereits gerenderte baseline.md ändert sich beim erneuten
        # Rendern nur dort, wo ein Vermerk steht.
        self.assertEqual(self._render(trust=None), (
            "## Messung\n"
            "\n"
            "Festgeschrieben: 2026-10-01 (Lauf 2026-10-01-audit)\n"
            "\n"
            "| Quelle | Erhoben am | Zeitraum |\n"
            "|---|---|---|\n"
            "| shopify | 2026-10-01 | Momentaufnahme |\n"
            "\n"
            "| Kennzahl | Wert |\n"
            "|---|---|\n"
            "| orders | 100 |\n"
            "| purchases | 180 |\n"
            "| estimated_traffic | 4200.5 |\n"
            "| index_report | nicht berechenbar |\n"
            "\n"
            "### channels\n"
            "\n"
            "| channel | sessions |\n"
            "|---|---|\n"
            "| Direct | 10 |\n"
            "\n"
            "### monthly\n"
            "\n"
            "| Schlüssel | Wert |\n"
            "|---|---|\n"
            "| 2026-07 | 5 |\n"
            "\n"
            "### queries\n"
            "\n"
            "- frage eins\n"
            "- frage zwei\n"
        ))

    def test_block_with_trust_shows_every_note(self):
        # Die Zeilen ohne Vermerk (orders, monthly) sind dieselben wie im Test
        # darüber. Der Vermerk zu einer Tabelle oder Liste steht als Zitat vor
        # ihren Zahlen: ohne das Zitat liefe er in Markdown mit einer
        # nachfolgenden Aufzählung zu einer einzigen Liste zusammen.
        section = self._render(trust={
            "purchases": {
                "status": "contaminated",
                "reason": "Zwei Mess-IDs laufen parallel.",
                "break": "2026-05", "finding": "MES-01",
                "corrections": [
                    {"date": "2026-09-12", "note": "Enthält Erstattungen."},
                    {"date": "2026-09-14", "note": "Betrag in Berichtswährung."},
                ],
            },
            "estimated_traffic": {"status": "measured",
                                  "reason": "Schätzwert, kein gemessener Klick."},
            "index_report": {"status": "not_measurable"},
            "channels": {"status": "contaminated",
                         "reason": "Beruht auf denselben Sitzungen."},
            "queries": {"status": "measured", "reason": "Eingefrorenes Abfrage-Set."},
        })
        self.assertEqual(section, (
            "## Messung\n"
            "\n"
            "Festgeschrieben: 2026-10-01 (Lauf 2026-10-01-audit)\n"
            "\n"
            "| Quelle | Erhoben am | Zeitraum |\n"
            "|---|---|---|\n"
            "| shopify | 2026-10-01 | Momentaufnahme |\n"
            "\n"
            "| Kennzahl | Wert |\n"
            "|---|---|\n"
            "| orders | 100 |\n"
            "| purchases | 180 (nachweislich falsch) |\n"
            "| estimated_traffic | 4200.5 (gemessen) |\n"
            "| index_report | nicht berechenbar (nicht messbar) |\n"
            "\n"
            "> **purchases**\n"
            "> - Status: nachweislich falsch\n"
            "> - Grund: Zwei Mess-IDs laufen parallel.\n"
            "> - Monat des Bruchs: 2026-05\n"
            "> - Befund: MES-01\n"
            "> - Korrektur vom 2026-09-12: Enthält Erstattungen.\n"
            "> - Korrektur vom 2026-09-14: Betrag in Berichtswährung.\n"
            "\n"
            "> **estimated_traffic**\n"
            "> - Status: gemessen\n"
            "> - Hinweis: Schätzwert, kein gemessener Klick.\n"
            "\n"
            "> **index_report**\n"
            "> - Status: nicht messbar\n"
            "\n"
            "### channels\n"
            "\n"
            "> - Status: nachweislich falsch\n"
            "> - Grund: Beruht auf denselben Sitzungen.\n"
            "\n"
            "| channel | sessions |\n"
            "|---|---|\n"
            "| Direct | 10 |\n"
            "\n"
            "### monthly\n"
            "\n"
            "| Schlüssel | Wert |\n"
            "|---|---|\n"
            "| 2026-07 | 5 |\n"
            "\n"
            "### queries\n"
            "\n"
            "> - Status: gemessen\n"
            "> - Hinweis: Eingefrorenes Abfrage-Set.\n"
            "\n"
            "- frage eins\n"
            "- frage zwei\n"
        ))

    def test_wrong_value_is_marked_in_its_own_row(self):
        # Wer nur die Tabelle überfliegt, sieht es an der Zahl selbst, nicht
        # erst im Vermerk darunter.
        section = self._render(trust={"purchases": {
            "status": "contaminated", "reason": "Zwei Mess-IDs."}})
        self.assertIn("| purchases | 180 (nachweislich falsch) |", section)

    def test_every_trust_state_has_a_german_label(self):
        labels = {"measured": "gemessen", "contaminated": "nachweislich falsch",
                  "not_measurable": "nicht messbar"}
        self.assertEqual(set(labels), set(baseline.TRUST_STATES))
        for state, label in labels.items():
            with self.subTest(state=state):
                section = self._render(trust={"orders": {"status": state,
                                                         "reason": "Grund."}})
                self.assertIn(f"| orders | 100 ({label}) |", section)
                self.assertIn(f"> - Status: {label}\n", section)

    def test_every_correction_appears_with_its_date(self):
        section = self._render(trust={"purchases": {
            "status": "contaminated", "reason": "Zwei Mess-IDs.",
            "corrections": [
                {"date": "2026-09-12", "note": "Enthält Erstattungen."},
                {"date": "2026-09-14", "note": "Betrag in Berichtswährung."},
            ]}})
        self.assertIn("> - Korrektur vom 2026-09-12: Enthält Erstattungen.\n", section)
        self.assertIn("> - Korrektur vom 2026-09-14: Betrag in Berichtswährung.\n", section)

    def test_note_on_a_table_stands_before_its_numbers(self):
        section = self._render(trust={"channels": {
            "status": "contaminated", "reason": "Dieselben Sitzungen."}})
        channels = section[section.index("### channels"):section.index("### monthly")]
        self.assertLess(channels.index("nachweislich falsch"),
                        channels.index("| Direct | 10 |"))

    def test_entry_without_status_counts_as_measured(self):
        # write_block lässt einen Eintrag mit nur derived_from zu, und ein
        # Wert ohne status gilt dort als gemessen. Hier genauso.
        section = self._render(trust={"orders": {"derived_from": ["purchases"]}})
        self.assertIn("| orders | 100 (gemessen) |", section)

    def test_note_on_a_missing_value_is_refused(self):
        # Korrekturen werden von Hand nachgetragen. Ein vertippter Schlüssel
        # würde den Vermerk sonst still verschlucken, und das ist genau der
        # Fehler, den diese Darstellung beheben soll.
        with self.assertRaises(ValueError) as caught:
            self._render(trust={"purchase": {"status": "contaminated", "reason": "x"}})
        self.assertIn("'purchase'", str(caught.exception))

    def test_unknown_status_is_refused(self):
        with self.assertRaises(ValueError):
            self._render(trust={"orders": {"status": "komisch"}})
