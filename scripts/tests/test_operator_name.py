"""Der Name des Betreibers in beiden Kundendokumenten (Spec 2026-09-11, B2, D7).

Gespeichert wird weiter `"Path to AI"`, und der Wert meint den Betreiber.
Angezeigt wird der Name aus `PTAI_OPERATOR_NAME`, sonst "Dienstleister". Ohne
das stünde beim Kunden eines fremden Betreibers Path to AI als Verantwortlicher
im Dokument, und genau das schließt E3 aus.
"""
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from audit import env, measures
from audit import report_build as rb

ROOT = Path(__file__).resolve().parents[2]
NAME = "PTAI_OPERATOR_NAME=Beispiel Consulting\n"


class Base(unittest.TestCase):
    """Ein leerer Workspace, keine Umgebungsvariable, keine zentrale Datei.

    Die echte zentrale Datei wird nie gelesen: auf Yves' Rechner steht dort ein
    Name, und der Test wäre dort grün und anderswo rot.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name) / "workspace"
        self.ws.mkdir()
        self.central = Path(tmp.name) / "central.env"
        for patcher in (mock.patch.object(env, "CENTRAL", self.central),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("PTAI_OPERATOR_NAME", None)


class TestResponsibleLabel(Base):
    def label(self, value, **kwargs):
        return measures.responsible_label(value, workspace=self.ws, **kwargs)

    def test_the_operator_without_a_name_is_the_service_provider(self):
        self.assertEqual(self.label("Path to AI"), "Dienstleister")

    def test_the_name_from_the_workspace(self):
        (self.ws / ".env").write_text(NAME, encoding="utf-8")
        self.assertEqual(self.label("Path to AI"), "Beispiel Consulting")

    def test_the_name_from_the_central_file(self):
        self.central.write_text('PTAI_OPERATOR_NAME="Beispiel Consulting"\n', encoding="utf-8")
        self.assertEqual(self.label("Path to AI"), "Beispiel Consulting")

    def test_the_environment_wins(self):
        (self.ws / ".env").write_text(NAME, encoding="utf-8")
        os.environ["PTAI_OPERATOR_NAME"] = "Beispiel Studio"
        self.assertEqual(self.label("Path to AI"), "Beispiel Studio")

    def test_the_customer_is_the_brand(self):
        self.assertEqual(self.label("Customer", brand="Beispielshop"), "Beispielshop")

    def test_the_customer_without_a_brand(self):
        self.assertEqual(self.label("Customer"), "Kunde")

    def test_a_third_party(self):
        self.assertEqual(self.label("Third Party"), "Dritter Dienstleister")

    def test_no_value_gives_no_text(self):
        self.assertEqual(self.label(None), "")

    def test_the_stored_value_stays(self):
        backlog = measures.create(
            measures.empty(), title="Alt-Texte ergänzen", discipline="seo",
            evidence="crawl.json > pages[0]", confidence="confirmed",
            leverage="low", effort="large", responsible="Path to AI")
        self.assertEqual(backlog["measures"][0]["responsible"], "Path to AI")


class TestMeasuresDocument(Base):
    def render(self, responsible):
        backlog = measures.create(
            measures.empty(), title="Alt-Texte ergänzen", discipline="seo",
            evidence="crawl.json > pages[0]", confidence="confirmed",
            leverage="low", effort="large", responsible=responsible,
            today=date(2026, 10, 1))
        measures.save(self.ws, backlog)
        return measures.render(self.ws).read_text(encoding="utf-8")

    def test_the_operator_is_not_called_path_to_ai(self):
        text = self.render("Path to AI")
        self.assertIn("| Dienstleister |", text)
        self.assertNotIn("Path to AI", text)

    def test_the_name_comes_from_the_workspace_of_the_run(self):
        (self.ws / ".env").write_text(NAME, encoding="utf-8")
        self.assertIn("| Beispiel Consulting |", self.render("Path to AI"))

    def test_a_third_party_has_the_same_word_as_in_the_audit(self):
        self.assertIn("| Dritter Dienstleister |", self.render("Third Party"))

    def test_no_responsible_stays_a_dash(self):
        self.assertIn("| - |", self.render(None))


class TestAuditMeasureBlock(Base):
    """Die Zeile "Wer" im großen Audit nutzt dieselbe Anzeige wie measures.md."""

    MEASURE = {"id": "M-001", "title": "Alt-Texte ergänzen", "leverage": "low",
               "effort": "large", "type": "measure"}
    WHO_ROW = re.compile(r'<div class="summary-label">Wer</div>'
                         r'<div class="summary-value">(.*?)</div>')

    def who(self, responsible):
        block = rb._measure_block({**self.MEASURE, "responsible": responsible},
                                  "Beispielshop", None, workspace=self.ws)
        found = self.WHO_ROW.search(block)
        return found.group(1) if found else None

    def test_the_operator_without_a_name(self):
        self.assertEqual(self.who("Path to AI"), "Dienstleister")

    def test_the_name_from_the_workspace(self):
        (self.ws / ".env").write_text(NAME, encoding="utf-8")
        self.assertEqual(self.who("Path to AI"), "Beispiel Consulting")

    def test_the_customer_is_the_brand(self):
        self.assertEqual(self.who("Customer"), "Beispielshop")

    def test_a_third_party(self):
        self.assertEqual(self.who("Third Party"), "Dritter Dienstleister")

    def test_without_responsible_there_is_no_row(self):
        self.assertIsNone(self.who(None))

    def test_the_words_live_in_one_place(self):
        # Bis zum 11.09.2026 hatte report_build.py eine eigene Zuordnung.
        self.assertFalse(hasattr(rb, "WHO"))


class TestAuditTexts(unittest.TestCase):
    """Die Regel in der Skill und der Hinweis in der Vorlage nennen den Betreiber."""

    def test_the_rule_speaks_of_the_operator(self):
        text = " ".join((ROOT / "skills" / "audit" / "SKILL.md").read_text(encoding="utf-8").split())
        self.assertNotIn("Kernangebot von Path to AI", text)
        self.assertIn("was der Betreiber für den Kunden umsetzt", text)
        # Geschrieben wird weiterhin der alte Wert (D7).
        self.assertIn('umsetzt (SEO, GEO, SEA, Shop und Conversion, Technik), `"Path to AI"`', text)
        self.assertIn("`measures.responsible_label()`", text)

    def test_the_template_hint_names_no_company(self):
        text = (ROOT / "skills" / "audit" / "templates" / "audit.html").read_text(encoding="utf-8")
        self.assertNotIn("<!-- Path to AI, Kunde oder Dritter -->", text)
        self.assertIn("<!-- Betreiber, Marke des Kunden oder Dritter Dienstleister -->", text)


class TestNoCompanyAsOperator(unittest.TestCase):
    """Kein Agent und keine Skill sagt, was Path to AI nicht ist (E3).

    Und wo "Yves" den meint, der den Lauf fährt, steht der Betreiber (D7).
    Zitate des Autors ("Yves dazu: ...") bleiben, sie nennen die Herkunft einer
    Regel, und der Funnel von audit-light bleibt Path to AI (D4).
    """

    #: Datei, alter Wortlaut, neuer Wortlaut.
    OPERATOR_WORDING = (
        ("skills/audit/SKILL.md", "Yves ist das Subjekt",
         "Der Betreiber ist das Subjekt (ich-Form)"),
        ("skills/audit/SKILL.md", "lässt Yves sie ein zweites Mal schreiben",
         "lässt den Betreiber sie ein zweites Mal schreiben"),
        ("scripts/audit/revision.py", "lässt Yves sie ein zweites Mal schreiben",
         "lässt den Betreiber sie ein zweites Mal schreiben"),
        ("scripts/audit/publish.py", "den Yves nicht gelesen hat",
         "bevor der Betreiber ihn gelesen hat"),
    )

    def test_no_text_says_what_path_to_ai_is_not(self):
        hits = [str(p.relative_to(ROOT)) for folder in ("agents", "skills")
                for p in sorted((ROOT / folder).rglob("*.md"))
                if "Path to AI ist keine" in " ".join(p.read_text(encoding="utf-8").split())]
        self.assertEqual(hits, [])

    def test_where_yves_means_the_operator_the_text_says_operator(self):
        for path, old, new in self.OPERATOR_WORDING:
            text = " ".join((ROOT / path).read_text(encoding="utf-8").split())
            with self.subTest(path=path, old=old):
                self.assertNotIn(old, text)
                self.assertIn(new, text)


if __name__ == "__main__":
    unittest.main()
