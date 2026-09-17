"""Das Audit-PDF-Template gegen das prüfen, was die Skill über es sagt.

Das Template ist reine Prosa mit Platzhaltern, und der Lauf füllt sie von Hand
anhand der Tabellen in `skills/audit/SKILL.md`, Phase 4. Ein Platzhalter, den
die Skill nicht nennt, wird deshalb nie gefüllt und steht am Ende wörtlich im
Kundendokument: `__KPI_AOV__` statt einer Zahl. Kein anderer Test würde das
bemerken, weil das Rendern trotzdem gelingt.

Umgekehrt genauso: eine Skill, die einen Platzhalter beschreibt, den es im
Template nicht gibt, schickt den Lauf auf die Suche nach einer Stelle, die
nicht existiert.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "skills" / "audit" / "templates" / "audit.html"
SKILL = ROOT / "skills" / "audit" / "SKILL.md"

PLACEHOLDER = re.compile(r"__[A-Z][A-Z_]*__")
MARKER = re.compile(r"<!-- SECTION:([a-z]+) -->")

#: Die drei Pfad-Platzhalter nennt die Skill in Prosa statt in der Tabelle,
#: weil sie keine Quellfelder haben, sondern Pfade im Plugin sind.
PATH_PLACEHOLDERS = {"__CSS_PATH__", "__LOGO_PATH__", "__LOGO_REVERSED_PATH__"}


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


class TestPdfTemplate(unittest.TestCase):
    def test_every_placeholder_is_documented_in_the_skill(self):
        text = skill()
        for name in sorted(set(PLACEHOLDER.findall(template())) - PATH_PLACEHOLDERS):
            with self.subTest(placeholder=name):
                self.assertIn(name, text,
                              f"{name} steht im Template, aber in keiner Tabelle "
                              "der Skill. Der Lauf füllt ihn nicht, und er landet "
                              "wörtlich im Kundendokument.")

    def test_the_skill_invents_no_placeholder(self):
        found = set(PLACEHOLDER.findall(template()))
        # In der Skill stehen auch Platzhalter des Monats-Reports nicht, aber
        # jeder, der dort in einer Tabellenzeile steht, muss es geben.
        for name in sorted(set(PLACEHOLDER.findall(skill()))):
            with self.subTest(placeholder=name):
                self.assertIn(name, found,
                              f"{name} beschreibt die Skill, im Template gibt es "
                              "ihn nicht.")

    def test_every_section_marker_is_documented(self):
        text = skill()
        markers = MARKER.findall(template())
        self.assertTrue(markers, "das Template hat keinen einzigen SECTION-Marker")
        for name in markers:
            with self.subTest(marker=name):
                self.assertIn(f"SECTION:{name}", text)

    def test_the_skill_names_no_unknown_section(self):
        found = set(MARKER.findall(template()))
        for name in set(re.findall(r"`SECTION:([a-z]+)`", skill())):
            with self.subTest(marker=name):
                self.assertIn(name, found)

    def test_the_eight_skeleton_elements_are_present(self):
        """Das Skelett aus dem Report-Playbook, an seinen festen Bausteinen."""
        text = template()
        for needle, element in (
            ('class="cover"', "Kopf"),
            ('class="meta"', "Dokumentzeile"),
            ('class="lead"', "Einstieg"),
            ('class="kpi-grid', "Kennzahlenleiste"),
            ('class="summary"', "Zusammenfassung"),
            ('class="toc"', "Inhalt"),
            ('class="next-step"', "Nächster Schritt"),
            ("SECTION:sources", "Quellen"),
        ):
            with self.subTest(element=element):
                self.assertIn(needle, text, f"Element fehlt: {element}")

    def test_the_five_summary_labels_are_the_ones_the_playbook_fixes(self):
        text = template()
        for label in ("Was du hier siehst", "Warum", "Status quo",
                      "Das Problem", "Was möglich ist"):
            with self.subTest(label=label):
                self.assertIn(f">{label}<", text)

    def test_the_template_uses_only_classes_the_stylesheet_defines(self):
        """Eine Klasse ohne Regel rendert unsichtbar falsch, ohne Fehlermeldung."""
        css = (ROOT / "assets" / "brand" / "report.css").read_text(encoding="utf-8")
        # Klassen aus dem Markup, nicht aus dem Baukasten-Kommentar: der zeigt
        # dieselben Klassen und würde nichts Neues beitragen.
        used = set()
        for attr in re.findall(r'class="([^"]+)"', template()):
            # Ein Platzhalter im class-Attribut ist Absicht: der Lauf
            # entscheidet dort zwischen einer Klasse und keiner. Geprueft wird
            # der Wert, den das Script einsetzt, ueber die Konstanten unten.
            used.update(w for w in attr.split() if not w.startswith("__"))
        # Im <style>-Block des Templates definierte Klassen sind erlaubt.
        local = set(re.findall(r"\.([a-z][a-z0-9-]*)\s*\{",
                               template().split("<style>")[1].split("</style>")[0]))
        for name in sorted(used):
            with self.subTest(css_class=name):
                self.assertTrue(f".{name}" in css or name in local,
                                f"Klasse {name!r} hat weder in report.css noch "
                                "im Template eine Regel")

    def test_klassen_die_das_script_einsetzt_haben_eine_regel(self):
        """Eine Klasse, die erst zur Laufzeit entsteht, prueft niemand sonst."""
        css = (ROOT / "assets" / "brand" / "report.css").read_text(encoding="utf-8")
        for name in ("value--leer", "finding-block--hoch", "finding-block--mittel",
                     "finding-block--gering", "kpi-grid--3", "kpi-period",
                     "section-message", "problem-grid", "problem",
                     "score-total", "score-grid", "score", "scorebar",
                     "section-score"):
            with self.subTest(css_class=name):
                self.assertIn(f".{name}", css)


if __name__ == "__main__":
    unittest.main()
