"""Tests fuer `audit.context`: Kundenwissen zu Befunden."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import context  # noqa: E402


def entry(**kw):
    basis = {"id": "CTX-001", "date": "2026-09-08", "source": "Termin, Tim",
             "about": ["HDL-07"], "kind": "reason",
             "statement": "Die Produkte sind ausverkauft."}
    basis.update(kw)
    return basis


class TestLaden(unittest.TestCase):
    def test_eine_fehlende_datei_ist_kein_fehler(self):
        """Der erste Lauf hat kein Kundenwissen, und das ist der Normalfall."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(context.load(tmp), [])

    def test_kaputtes_json_wirft_statt_still_leer_zu_sein(self):
        """Eine unlesbare Datei als 'kein Kundenwissen' zu behandeln waere der
        schlimmste Fall: beide Seiten glauben, die Aussage sei angekommen."""
        with tempfile.TemporaryDirectory() as tmp:
            p = context.context_path(tmp)
            p.parent.mkdir(parents=True)
            p.write_text("{kaputt", encoding="utf-8")
            with self.assertRaises(ValueError):
                context.load(tmp)

    def test_eine_blanke_liste_geht_auch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = context.context_path(tmp)
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps([entry()]), encoding="utf-8")
            self.assertEqual(len(context.load(tmp)), 1)


class TestPruefen(unittest.TestCase):
    def test_ein_vollstaendiger_eintrag_ist_sauber(self):
        self.assertEqual(context.validate([entry()]), [])

    def test_ohne_about_erreicht_der_eintrag_keinen_befund(self):
        errors = context.validate([entry(about=[])])
        self.assertTrue(any("about" in f for f in errors), errors)

    def test_ohne_statement_sagt_der_eintrag_nichts(self):
        errors = context.validate([entry(statement="   ")])
        self.assertTrue(any("statement" in f for f in errors), errors)

    def test_eine_unbekannte_art_wird_gemeldet(self):
        errors = context.validate([entry(kind="egal")])
        self.assertTrue(any("kind" in f for f in errors), errors)

    def test_eine_doppelte_kennung_wird_gemeldet(self):
        errors = context.validate([entry(), entry()])
        self.assertTrue(any("doppelt" in f for f in errors), errors)

    def test_ohne_quelle_ist_spaeter_nicht_nachvollziehbar_wer_das_sagte(self):
        errors = context.validate([entry(source="")])
        self.assertTrue(any("source" in f for f in errors), errors)


class TestAnhaengen(unittest.TestCase):
    def test_der_erste_eintrag_bekommt_ctx_001(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = context.add(tmp, "Ausverkauft.", ["HDL-07"], "reason",
                            "Termin 08.09.2026, Mara", heute=date(2026, 9, 8))
            self.assertEqual(e["id"], "CTX-001")
            self.assertEqual(e["date"], "2026-09-08")

    def test_kennungen_laufen_fort(self):
        with tempfile.TemporaryDirectory() as tmp:
            context.add(tmp, "A", ["HDL-07"], "reason", "Termin")
            zweiter = context.add(tmp, "B", ["SEO-03"], "decision", "Chat")
            self.assertEqual(zweiter["id"], "CTX-002")
            self.assertEqual(len(context.load(tmp)), 2)

    def test_ein_neuer_eintrag_ersetzt_nie_einen_alten(self):
        """Was der Kunde einmal gesagt hat, bleibt nachvollziehbar. Eine
        geaenderte Einschaetzung ist ein neuer Eintrag."""
        with tempfile.TemporaryDirectory() as tmp:
            context.add(tmp, "Ist ausverkauft.", ["HDL-07"], "reason", "Termin")
            context.add(tmp, "Doch ein Fehler.", ["HDL-07"], "correction", "Chat")
            alle = context.load(tmp)
            self.assertEqual(len(alle), 2)
            self.assertEqual(alle[0]["statement"], "Ist ausverkauft.")

    def test_ohne_about_wird_gar_nicht_erst_geschrieben(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                context.add(tmp, "Irgendwas", [], "reason", "Termin")
            self.assertFalse(context.context_path(tmp).exists())

    def test_eine_unbekannte_art_wird_abgelehnt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                context.add(tmp, "Irgendwas", ["HDL-07"], "egal", "Termin")


class TestZuordnung(unittest.TestCase):
    def test_ein_eintrag_findet_seinen_befund(self):
        self.assertEqual(
            len(context.for_finding([entry()], "HDL-07")), 1)

    def test_ein_anderer_befund_bleibt_unberuehrt(self):
        self.assertEqual(context.for_finding([entry()], "SEO-03"), [])

    def test_eine_sektion_trifft_jeden_befund_darin(self):
        """Manches haengt nicht an einem einzelnen Befund: 'wir bespielen Paid
        Social bewusst nicht' gilt fuer die ganze Sektion."""
        e = entry(about=["sea"], kind="decision")
        self.assertEqual(len(context.for_finding([e], "SEA-02")), 1)

    def test_die_zuordnung_ignoriert_gross_und_kleinschreibung(self):
        self.assertEqual(len(context.for_finding([entry(about=["hdl-07"])],
                                                 "HDL-07")), 1)


class TestPrompt(unittest.TestCase):
    def test_ohne_eintraege_bleibt_der_abschnitt_leer(self):
        """Ein leerer Abschnitt erzeugt sonst die Illusion, es haette
        Kundenwissen gegeben und nichts habe gepasst."""
        self.assertEqual(context.as_prompt([]), "")

    def test_der_prompt_traegt_kennung_ziel_und_aussage(self):
        text = context.as_prompt([entry()])
        self.assertIn("CTX-001", text)
        self.assertIn("HDL-07", text)
        self.assertIn("ausverkauft", text)
        self.assertIn("Termin, Tim", text)

    def test_der_prompt_sagt_dem_agenten_was_er_tun_soll(self):
        text = context.as_prompt([entry()])
        self.assertIn("nicht erneut gestellt", text)
        self.assertIn("gewinnen die Zahlen", text)


if __name__ == "__main__":
    unittest.main()
