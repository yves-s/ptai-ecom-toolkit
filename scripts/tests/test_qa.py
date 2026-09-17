"""Die Abnahme: was sie fangen muss, und was sie durchlassen muss.

Ein Gate, das bei allem anschlägt, wird ignoriert; eins, das nichts fängt,
ist Dekoration. Die Tests halten beides fest.
"""
import json
import tempfile
import unittest
from pathlib import Path

from audit import qa
from audit import report_build as rb


def _schreibe(pfad: Path, doc) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


SAUBER = {
    "id": "HDL-01",
    "statement": "Ein Drittel des Sortiments ist nicht bestellbar.",
    "evidence": "shopify.json > availability.products_fully_unavailable",
    "severity": "hoch", "confidence": "confirmed", "effort": "medium",
    "metrics": [{"label": "Nicht bestellbar", "value": "1.000",
                 "context": "von 3.000 aktiven Produkten"}],
    "why": "Ein Drittel der sichtbaren Auswahl kann niemand kaufen.",
    "fix": "Die Liste durchgehen und je Produkt entscheiden.",
}


class TestBefunde(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json",
                  {"sources": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def _pruefe(self, *findings):
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "findings"
                  / "commerce.json",
                  {"discipline": "commerce", "findings": list(findings)})
        return qa.check_findings(rb.Run(self.ws, self.run_id))

    def test_ein_sauberer_befund_meldet_nichts(self):
        self.assertEqual(self._pruefe(SAUBER), [])

    def test_fehlende_pflichtfelder_sind_ein_fehler(self):
        ohne = {k: v for k, v in SAUBER.items() if k not in ("id", "severity")}
        stufen = [b.stufe for b in self._pruefe(ohne)]
        self.assertIn("fehler", stufen)

    def test_ersatzumlaute_sind_ein_fehler(self):
        kaputt = dict(SAUBER, why="Das ist fuer den Shop ein Problem.")
        treffer = [b for b in self._pruefe(kaputt) if b.stufe == "fehler"]
        self.assertTrue(treffer)
        self.assertIn("Ersatzumlaute", treffer[0].text)

    def test_werkzeugsprache_ist_eine_warnung(self):
        """Der Kunde hat Fragen zu seinem Shop, keine zu unseren Dateien."""
        kaputt = dict(SAUBER, why="Laut shopify.json fehlt der Bestand.")
        treffer = [b for b in self._pruefe(kaputt) if b.stufe == "warnung"]
        self.assertTrue(any("Werkzeugsprache" in b.text for b in treffer))

    def test_werkzeugsprache_in_evidence_ist_erlaubt(self):
        """Dort gehört sie hin, damit ein Mensch nachrechnen kann."""
        self.assertEqual(self._pruefe(SAUBER), [])

    def test_ein_unbekannter_schweregrad_ist_ein_fehler(self):
        kaputt = dict(SAUBER, severity="kritisch")
        self.assertTrue(any("keine der drei Stufen" in b.text
                            for b in self._pruefe(kaputt)))

    def test_ein_befund_ohne_massnahmenfelder_ist_nur_eine_warnung(self):
        beobachtung = {k: v for k, v in SAUBER.items()
                       if k not in ("why", "fix", "metrics")}
        stufen = {b.stufe for b in self._pruefe(beobachtung)}
        self.assertNotIn("fehler", stufen)
        self.assertIn("warnung", stufen)

    def test_keine_befunddatei_ist_ein_fehler(self):
        findings = qa.check_findings(rb.Run(self.ws, self.run_id))
        self.assertEqual([b.stufe for b in findings], ["fehler"])


class TestDatenlage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "X"})
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json",
                  {"sources": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def _crawl(self, summary, index=None):
        _schreibe(self.ws / "reporting" / "data" / self.run_id / "crawl.json",
                  {"summary": summary, "findings_index": index or {}})
        return qa.check_source_status(rb.Run(self.ws, self.run_id))

    def test_die_selbstpruefung_des_crawlers_wird_zum_fehler(self):
        """Der Crawler meldet, dass seine Titel verdächtig aussehen."""
        findings = self._crawl({"self_check": ["1667 von 1667 Seiten tragen "
                                              "denselben Titel 'Visa'."]})
        self.assertEqual(findings[0].stufe, "fehler")

    def test_gedrosselte_seiten_werden_gemeldet(self):
        findings = self._crawl({"throttled_pages": 826, "url_count": 2500})
        self.assertTrue(any("826" in b.text for b in findings))

    def test_eine_fremde_mess_id_ist_ein_fehler(self):
        _schreibe(self.ws / "reporting" / "data" / self.run_id / "ga4.json",
                  {"property": {"measurement_ids": ["G-AAA"]}})
        findings = self._crawl({}, {"inline_tag_ids": {"G-AAA": 10, "G-BBB": 10}})
        self.assertTrue(any("G-BBB" in b.text and b.stufe == "fehler"
                            for b in findings))

    def test_dieselbe_mess_id_meldet_nichts(self):
        _schreibe(self.ws / "reporting" / "data" / self.run_id / "ga4.json",
                  {"property": {"measurement_ids": ["G-AAA"]}})
        findings = self._crawl({}, {"inline_tag_ids": {"G-AAA": 10}})
        self.assertEqual(findings, [])


class TestMenschenteil(unittest.TestCase):
    def test_die_liste_fuer_den_menschen_ist_nicht_leer(self):
        """Was Urteil braucht, bleibt beim Menschen, und das muss dastehen."""
        self.assertGreaterEqual(len(qa.FOR_HUMANS), 4)


if __name__ == "__main__":
    unittest.main()


class TestKundenwissen(unittest.TestCase):
    """Die einzige Stelle, an der auffaellt, dass eine Kundenaussage ins Leere
    lief. Ohne sie merkt das niemand ausser dem Kunden, im naechsten Termin."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json",
                  {"sources": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def _pruefe(self, finding, entries=None):
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "findings"
                  / "commerce.json",
                  {"discipline": "commerce", "findings": [finding]})
        if entries is not None:
            _schreibe(self.ws / "reporting" / "context.json",
                      {"entries": entries})
        return qa.check_customer_context(rb.Run(self.ws, self.run_id), self.ws)

    def _eintrag(self, **kw):
        e = {"id": "CTX-001", "date": "2026-09-08", "source": "Termin, Tim",
             "about": ["HDL-01"], "kind": "reason",
             "statement": "Die Produkte sind ausverkauft."}
        e.update(kw)
        return e

    def test_ohne_kundenwissen_meldet_nichts(self):
        self.assertEqual(self._pruefe(dict(SAUBER)), [])

    def test_ein_unveraenderter_befund_wird_gemeldet(self):
        findings = self._pruefe(dict(SAUBER), [self._eintrag()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].stufe, "warnung")
        self.assertIn("CTX-001", findings[0].text)

    def test_ein_befund_der_den_widerspruch_benennt_geht_durch(self):
        """Es gibt den legitimen Fall, dass die Zahlen der Kundenaussage
        widersprechen. Dann bleibt der Befund stehen, mit dem Widerspruch
        darin, und das Gate darf nicht dagegen anschlagen."""
        f = dict(SAUBER)
        f["why"] = ("Laut Kundenangabe CTX-001 ausverkauft. Gemessen sind 108 "
                    "dieser Titel im selben Zeitraum in Warenkoerben gelandet.")
        self.assertEqual(self._pruefe(f, [self._eintrag()]), [])

    def test_ein_anderer_befund_bleibt_unberuehrt(self):
        e = self._eintrag(about=["SEO-03"])
        self.assertEqual(self._pruefe(dict(SAUBER), [e]), [])

    def test_ein_kaputter_eintrag_ist_ein_fehler_kein_stilles_ueberspringen(self):
        findings = self._pruefe(dict(SAUBER), [self._eintrag(about=[])])
        self.assertTrue(any(b.stufe == "fehler" for b in findings), findings)


class TestLaienwoerter(unittest.TestCase):
    """Umschreibungen, wo ein Fachbegriff oder eine Zahl hingehoert."""

    def test_werkzeug_is_an_error(self):
        # Der belegte Fall: "ein Werkzeug fuer Preis- und Angebotstests",
        # waehrend der Produktname in der Tabelle darunter stand.
        treffer = [m for muster, _ in qa.LAY_WORDS
                   if (m := muster.search("Auf allen Seiten läuft ein Werkzeug"))]
        self.assertTrue(treffer)

    def test_menschen_is_an_error(self):
        treffer = [muster for muster, _ in qa.LAY_WORDS
                   if muster.search("so viele Besuche, wie der Shop als Menschen zählt")]
        self.assertTrue(treffer)

    def test_a_product_name_is_fine(self):
        for muster, _ in qa.LAY_WORDS:
            self.assertIsNone(muster.search(
                "Intelligems spielt auf 3.000 Seiten Preistests aus"))

    def test_crawler_is_allowed_again(self):
        # Stand bis zum 09.09.2026 auf der Verbotsliste und hat die Analysen
        # auf Laienwoerter ausweichen lassen.
        self.assertIsNone(qa.TOOL_WORDS.search("Der Crawler hat 3.500 Seiten geöffnet"))

    def test_our_pipeline_stays_forbidden(self):
        self.assertIsNotNone(qa.TOOL_WORDS.search("laut crawl.json"))
        self.assertIsNotNone(qa.TOOL_WORDS.search("aus DataForSEO"))

    def test_a_vague_quantity_is_only_a_warning(self):
        self.assertIsNotNone(qa.VAGUE_QUANTITIES.search("mehrere Anbieter fehlen"))

    def test_a_counted_quantity_passes(self):
        self.assertIsNone(qa.VAGUE_QUANTITIES.search("Acht von zwölf Diensten fehlen"))
