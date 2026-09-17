"""Das Schluss-Panel folgt dem Betreiber, Path to AI steht nur als Herkunft da.

Entscheidung vom 12.09.2026, beim Halt vor dem Veröffentlichen von Yves
freigegeben: der Abbinder mit dem einen Satz "Erstellt mit ptai-ecom, dem
E-Commerce-Werkzeug von Path to AI." war zu dünn, und "Werkzeug" ist ein Wort,
das die eigene QA (`scripts/audit/qa.py`) in Kundentexten anmahnt. Den Schluss
des Verkaufs-PDFs zu übernehmen (Porträt, Stationen, Terminlink) kam nicht in
Frage: dann würde der Report jedes fremden Betreibers dessen Kunden Path to AI
anbieten.

Deshalb kommt das Panel aus den Einstellungen des Betreibers
(`PTAI_OPERATOR_NAME`, `PTAI_OPERATOR_CONTACT`, `PTAI_OPERATOR_EMAIL`,
`PTAI_OPERATOR_BOOKING_URL`) und wird von `scripts/audit/closing.py` gerendert.
Die beiden Vorlagen tragen nur noch den Platzhalter `__CLOSING__`,
`assets/brand/abbinder.md` ist entfernt. Bis zum 11.09.2026 hielt ein Kommentar
die Fassungen zusammen, und sie waren längst auseinander; eine Stelle im Code
kann das nicht mehr.

Am 15.09.2026 ist der Inhalt selbst noch einmal kleiner geworden: das Panel
zeigt nur noch die Kontaktzeilen, keinen Satz mehr. Der Absatz mit Überschrift
und Termin-Button im Audit war wörtlich aus dem Verkaufs-PDF kopiert, der
Kontakt-Satz im Monats-Report ein Mail-Schluss; beide waren beliebig, weil die
Kontaktdaten schon sagen, wie man den Betreiber erreicht.

Dieser Test prüft Vorlagen, Verweise und den Puls. Was im Panel steht, prüft
`test_closing.py` (Spec 2026-09-11 public release, B1, E3; Änderung 15.09.2026).
"""
import html
import re
import unittest
from pathlib import Path

from audit import closing
from tests import repo_files

ROOT = Path(__file__).resolve().parents[2]
PULSE = ROOT / "skills" / "pulse" / "SKILL.md"
REPORT_SKILL = ROOT / "skills" / "report" / "SKILL.md"
README = ROOT / "README.md"
PLACEHOLDER = "__CLOSING__"

TEMPLATES = {
    "report": ROOT / "skills" / "report" / "templates" / "report.html",
    "audit": ROOT / "skills" / "audit" / "templates" / "audit.html",
}

#: Die letzte Zeile des Wochen-Pulses.
PULSE_LINE = "Erstellt mit ptai-ecom von [Path to AI](https://path-to-ai.com)."

#: Woran man eine Person im Plugin erkennt: Mailadresse, Vorname, Werdegang,
#: Mail-Link. Kontaktdaten kommen nur aus den Einstellungen des Betreibers (E3).
PERSONAL = ("@", "Yves", "Jahre", "mailto:")

#: Was als Verweis auf die alte Quelle gilt. `docs/` hält die Geschichte und
#: bleibt, wie sie war.
SUFFIXES = (".py", ".md", ".sh", ".html", ".css", ".mjs", ".json", ".txt")


def footer(path: Path) -> str:
    """Das Schluss-Panel einer Vorlage, als Markup."""
    text = path.read_text(encoding="utf-8")
    start = text.index('<footer class="closing">')
    return text[start:text.index("</footer>", start)]


def closing_section(path: Path) -> str:
    """Kommentar über dem Panel plus Panel: alles, was zum Schluss gehört."""
    text = path.read_text(encoding="utf-8")
    start = text.index("<!-- Schluss-Panel")
    return text[start:text.index("</footer>", start)]


def section(path: Path, heading: str) -> str:
    """Ein Abschnitt einer Markdown-Datei, von der Überschrift bis zur nächsten."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def plain(markup: str) -> str:
    """Sichtbarer Text: Tags weg, Entities aufgelöst, Leerraum zusammengezogen."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", markup)).split())


class TestTemplates(unittest.TestCase):
    def test_the_markers_wrap_the_closing_panel_once(self):
        # Zwischen den Markierungen ersetzt `closing.apply()` alles durch die
        # Schlussseite aus PTAI_CLOSING_FILE (zweiter Teil, 15.09.2026).
        self.assertEqual((closing.START, closing.END),
                         ("<!-- CLOSING:start -->", "<!-- CLOSING:end -->"))
        for name, path in TEMPLATES.items():
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=name):
                self.assertEqual(text.count(closing.START), 1)
                self.assertEqual(text.count(closing.END), 1)
                region = text[text.index(closing.START):text.index(closing.END)]
                self.assertIn(PLACEHOLDER, region)
                self.assertIn('<footer class="closing">', region)
                self.assertIn("</footer>", region)

    def test_one_placeholder_inside_the_closing_panel(self):
        for name, path in TEMPLATES.items():
            with self.subTest(template=name):
                self.assertEqual(path.read_text(encoding="utf-8").count(PLACEHOLDER), 1)
                self.assertIn(PLACEHOLDER, footer(path))

    def test_logo_and_footer_line_frame_the_placeholder(self):
        for name, path in TEMPLATES.items():
            panel = footer(path)
            with self.subTest(template=name):
                self.assertLess(panel.index('class="logo-reversed"'), panel.index(PLACEHOLDER))
                self.assertLess(panel.index(PLACEHOLDER), panel.index('class="panel-footer"'))

    def test_the_template_has_no_closing_text_of_its_own(self):
        # Stünde Label oder Herkunftssatz wieder in der Vorlage, gäbe es zwei Fassungen.
        for name, path in TEMPLATES.items():
            panel = footer(path)
            with self.subTest(template=name):
                self.assertNotIn("Erstellt mit", panel)
                self.assertNotIn('class="eyebrow', panel)

    def test_no_person_and_no_werkzeug_in_the_closing(self):
        for name, path in TEMPLATES.items():
            for word in PERSONAL + ("Werkzeug",):
                with self.subTest(template=name, word=word):
                    self.assertNotIn(word, closing_section(path))


class TestPulse(unittest.TestCase):
    def test_the_pulse_line_is_the_origin_line(self):
        self.assertEqual(closing.ORIGIN_MARKDOWN, PULSE_LINE)
        self.assertEqual(plain(closing.ORIGIN_HTML), "Erstellt mit ptai-ecom von Path to AI.")

    def test_the_pulse_ends_with_the_origin_line(self):
        text = PULSE.read_text(encoding="utf-8")
        self.assertIn(PULSE_LINE, text)
        self.assertNotIn("abbinder.md", text)
        self.assertNotIn("@path-to-ai.com", text)


class TestOneSource(unittest.TestCase):
    def test_the_old_source_is_gone(self):
        self.assertFalse((ROOT / "assets" / "brand" / "abbinder.md").exists())

    def test_nothing_points_to_the_old_source(self):
        hits = [name for name, text in repo_files.text_files(
                    ROOT, SUFFIXES, exempt={"scripts/tests/test_abbinder.py"})
                if not name.startswith("docs/") and "abbinder.md" in text]
        self.assertEqual(hits, [])

    def test_the_report_skill_takes_the_closing_from_the_module(self):
        text = " ".join(REPORT_SKILL.read_text(encoding="utf-8").split())
        self.assertIn(PLACEHOLDER, text)
        self.assertIn("python3 -m audit.closing report-md .", text)
        # Das HTML bekommt den Schluss über `apply`, gespeichert und vor dem
        # Rendern. Das Einfügen von Hand über `report-html` ist abgelöst.
        apply = "python3 -m audit.closing apply reporting/reports/YYYY-MM-monthly.html ."
        self.assertIn(apply, text)
        self.assertLess(text.index(apply), text.index("render_pdf.sh"))
        self.assertNotIn("audit.closing report-html", text)

    def test_no_closing_text_says_werkzeug(self):
        texts = {
            "closing.py": (ROOT / "scripts" / "audit" / "closing.py").read_text(encoding="utf-8"),
            "README, Eigene Marke": section(README, "## Eigene Marke"),
            "Puls": PULSE_LINE,
        }
        texts.update({f"{name}.html": closing_section(path) for name, path in TEMPLATES.items()})
        for name, text in texts.items():
            with self.subTest(text=name):
                self.assertNotIn("werkzeug", text.lower())


if __name__ == "__main__":
    unittest.main()
