"""Die Web-Fassung: dieselben Zahlen wie im PDF, plus Navigation und Filter.

Seit dem 15.09.2026 endet sie mit demselben Schluss wie die Druckfassung. Der
Schluss liest die Einstellungen des Betreibers; die echte zentrale Datei wird
nie gelesen, alle Werte hier sind erfunden.
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import closing, env
from audit import report_build as rb
from audit import report_web

ROOT = Path(__file__).resolve().parents[2]

#: Die Einstellungen, aus denen der Schluss entsteht.
CLOSING_SETTINGS = ("PTAI_OPERATOR_NAME", "PTAI_OPERATOR_CONTACT", "PTAI_OPERATOR_EMAIL",
                    "PTAI_OPERATOR_BOOKING_URL", "PTAI_CLOSING_FILE")

#: Eine erfundene Schlussseite in der Form, die `PTAI_CLOSING_FILE` verlangt.
FRAGMENT = ('<section class="beispiel-abbinder" '
            'style="break-before:page;width:210mm;height:297mm">Beispiel-Abbinder</section>\n')


def _schreibe(pfad: Path, doc) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class TestWebFassung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.central = self.ws / "operator-central.env"
        for patcher in (mock.patch.object(env, "CENTRAL", self.central),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ["PTAI_ENV_FILE"] = str(self.central)
        os.environ["HOME"] = str(self.ws)
        for name in CLOSING_SETTINGS:
            os.environ.pop(name, None)
        self.run_id = "2026-10-01-audit"
        _schreibe(self.ws / "reporting" / "config.json", {"brand": "Beispielshop"})
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "state.json",
                  {"sources": {"ga4": {"status": "failed", "reason": "Zugang fehlt"}}})
        _schreibe(self.ws / "reporting" / "runs" / self.run_id / "findings"
                  / "commerce.json",
                  {"discipline": "commerce", "findings": [
                      {"id": "HDL-01", "statement": "Ein Befund über den Shop.",
                       "severity": "hoch", "why": "Kostet Geld.",
                       "fix": "Beheben.", "evidence": "shopify.json > totals"}]})
        self.text = {k: "Text" for k in rb.TEXT_FIELDS}

    def tearDown(self):
        self.tmp.cleanup()

    def _seite(self) -> str:
        return report_web.build(rb.Run(self.ws, self.run_id), self.text)

    def test_kein_platzhalter_bleibt_stehen(self):
        import re
        self.assertEqual(re.findall(r"__[A-Z_]{3,}__", self._seite()), [])

    def test_der_filter_findet_den_schweregrad(self):
        """Ohne data-severity filtert das Skript ins Leere, ohne Fehler."""
        self.assertIn('data-severity="hoch"', self._seite())

    def test_massnahmen_bleiben_bei_jedem_filter_sichtbar(self):
        """Eine Maßnahme trägt keinen eigenen Schweregrad, sie folgt aus
        ihrem Befund. Sie darf deshalb von keiner Stufe ausgeblendet werden."""
        self.assertIn('class="measure" data-severity="alle"', self._seite()
                      + '<div class="measure" data-severity="alle">')

    def test_alles_steht_in_einer_datei(self):
        """Die Seite muss in einem Jahr aus einem Ordner heraus funktionieren:
        kein CDN, kein externes Skript, keine Schrift von außen."""
        page = self._seite()
        # Auf Teilstrings zu pruefen geht hier nicht: die eingebetteten
        # Schriften sind base64 und enthalten zufaellig jede Zeichenfolge.
        # Geprueft wird deshalb, was tatsaechlich eine Anfrage ausloest. Ein
        # Link in <a> laedt nichts; der Schluss traegt immer einen, die
        # Herkunftszeile.
        for muster in (r'src\s*=\s*"https?:', r'<link\b[^>]*href\s*=\s*"https?:',
                       r"url\(\s*['\"]?https?:", r"@import", r"<script src"):
            with self.subTest(muster=muster):
                self.assertEqual(re.findall(muster, page), [])

    def test_keine_steuerzeichen_im_stylesheet(self):
        """Python liest "\\2192" in einem normalen String als Oktal-Escape.

        Im Dokument stand daraufhin "92?a068 erreichbar" statt "→ 68
        erreichbar". Ein CSS-Escape gehört in eine .css-Datei; in einem
        Python-String steht das Zeichen selbst.
        """
        from audit import report_web
        schlecht = [hex(ord(c)) for c in report_web.STYLE
                    if ord(c) < 32 and c not in "\n\t"]
        self.assertEqual(schlecht, [], "Steuerzeichen im Stylesheet")

    def test_die_navigation_haengt_nicht_am_skript(self):
        """Die Abschnittslinks müssen ohne JavaScript funktionieren.

        Am 07.09.2026 sah die Seite aus wie eine kaputte Navigation, weil das
        Skript den nativen Ankersprung unterband und ihn selbst nachbaute.
        Fällt dort irgendwo etwas aus, passiert beim Klicken gar nichts mehr.
        """
        from audit import report_web
        self.assertNotIn("preventDefault", report_web.SCRIPT)
        self.assertIn("scroll-margin-top", report_web.STYLE)
        page = self._seite()
        for key in ("s-commerce", "s-seo"):
            with self.subTest(anker=key):
                self.assertIn(f'href="#{key}"', page)
                self.assertIn(f'id="{key}"', page)

    def test_jeder_baustein_laeuft_fuer_sich(self):
        """Ein Fehler im Filter darf die Markierung nicht mitnehmen."""
        from audit import report_web
        self.assertIn("function versuch(", report_web.SCRIPT)
        self.assertGreaterEqual(report_web.SCRIPT.count("versuch("), 3)

    def test_die_kopfleistenhoehe_stimmt_auch_ohne_skript(self):
        """Sonst steht die Navigation unter der Leiste oder eine Lücke davor."""
        from audit import report_web
        self.assertIn("--topbar:38px", report_web.STYLE.replace(" ", ""))
        self.assertIn("--topbar:70px", report_web.STYLE.replace(" ", ""))

    def test_die_marke_ist_eingebettet_nicht_verlinkt(self):
        """Ein relativer Font-Pfad ueberlebt das erste Verschieben nicht."""
        page = self._seite()
        self.assertIn("@font-face", page)
        self.assertIn("Archivo Black", page)
        self.assertIn("data:font/woff2;base64,", page)
        self.assertIn("--p2a-accent:#E2381B", page)

    def test_zahlen_kommen_aus_demselben_builder(self):
        """Zwei Builder wären zwei Wahrheiten."""
        run = rb.Run(self.ws, self.run_id)
        inh = rb.content(run, self.text)
        page = report_web.build(run, self.text, inh)
        self.assertIn(inh["werte"]["__KPI_REVENUE__"], page)
        self.assertIn(inh["werte"]["__KPI_SIXTH_LABEL__"], page)

    def test_jede_sektion_bekommt_einen_anker(self):
        page = self._seite()
        for key in rb.SECTIONS:
            with self.subTest(sektion=key):
                self.assertIn(f'id="s-{key}"', page)
                self.assertIn(f'href="#s-{key}"', page)


class TestClosingInTheWebVersion(unittest.TestCase):
    """Die Web-Fassung endet mit demselben Schluss wie die Druckfassung (15.09.2026).

    Bis dahin hatte sie keinen, und das Portal zeigt die Web-Fassung zuerst: wer
    den Audit dort las, sah den Schluss nie.
    """

    setUp = TestWebFassung.setUp
    tearDown = TestWebFassung.tearDown
    _seite = TestWebFassung._seite

    def configure(self, text: str) -> None:
        self.central.write_text(text, encoding="utf-8")

    def closing_page(self) -> Path:
        path = self.ws / "schlussseite.html"
        path.write_text(FRAGMENT, encoding="utf-8")
        return path

    @staticmethod
    def region(page: str) -> str:
        """Was zwischen den beiden Markierungen steht."""
        return page[page.index(closing.START) + len(closing.START):page.index(closing.END)]

    def test_the_closing_page_follows_the_content_unchanged(self):
        self.configure(f"PTAI_CLOSING_FILE={self.closing_page()}\n"
                       "PTAI_OPERATOR_CONTACT=Mara Beispiel\n")
        page = self._seite()
        self.assertEqual(page.count(FRAGMENT), 1)
        self.assertEqual(self.region(page), "\n" + FRAGMENT)
        self.assertEqual((page.count(closing.START), page.count(closing.END)), (1, 1))
        for gone in ('<footer class="closing">', "__CLOSING__", "Mara Beispiel",
                     "Erstellt mit ptai-ecom"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, page)
        order = [page.index("</main>"), page.index('<div class="closing-web">'),
                 page.index(closing.START), page.index(FRAGMENT), page.index(closing.END),
                 page.index("<script>")]
        self.assertEqual(order, sorted(order))

    def test_without_the_setting_the_neutral_closing(self):
        self.configure("PTAI_OPERATOR_CONTACT=Mara Beispiel\n")
        page = self._seite()
        region = self.region(page)
        self.assertNotIn("__CLOSING__", page)
        self.assertIn('<footer class="closing">', region)
        self.assertIn(closing.report_html(self.ws), region)
        self.assertIn("Mara Beispiel", region)
        self.assertIn('class="logo-reversed"', region)
        self.assertIn("Beispielshop · E-Com-Audit", region)
        self.assertLess(page.index("</main>"), page.index(closing.START))

    def test_applying_again_changes_nothing(self):
        self.configure(f"PTAI_CLOSING_FILE={self.closing_page()}\n")
        page = self._seite()
        self.assertEqual(closing.apply(page, self.ws), page)

    def test_every_class_of_the_neutral_closing_has_a_web_rule(self):
        self.configure("PTAI_OPERATOR_NAME=Beispiel GmbH\nPTAI_OPERATOR_CONTACT=Mara Beispiel\n"
                       "PTAI_OPERATOR_EMAIL=kontakt@beispielshop.example\n"
                       "PTAI_OPERATOR_BOOKING_URL=https://termine.example/30min\n")
        page = self._seite()
        start = page.index('<div class="closing-web">')
        markup = re.sub(r"<svg\b.*?</svg>", "", page[start:page.index("</footer>", start)],
                        flags=re.S)
        names = {name for attr in re.findall(r'class="([^"]+)"', markup) for name in attr.split()}
        self.assertTrue({"closing-web", "closing", "summary-value", "origin"} <= names, names)
        for name in sorted(names):
            with self.subTest(css_class=name):
                self.assertIn(f".{name}", report_web.STYLE)

    def test_the_screen_layout_exists_only_in_the_web_version(self):
        css = (ROOT / "assets" / "brand" / "report.css").read_text(encoding="utf-8")
        self.assertIn(".closing-web", report_web.STYLE)
        self.assertNotIn("closing-web", css)

    def test_the_filter_leaves_the_closing_page_alone(self):
        """Der Filter blendet jede Sektion ohne sichtbaren Befund aus. Die
        Schlussseite ist selbst ein <section> und verschwände beim Filtern."""
        self.assertNotIn("querySelectorAll('section')", report_web.SCRIPT)
        self.assertIn("querySelectorAll('main section')", report_web.SCRIPT)

    def test_a_narrow_screen_scales_only_the_closing_page(self):
        """Das A4-Blatt ist breiter als ein Telefon. Das Skript verkleinert nur
        das Blatt des Betreibers auf die Breite des Bands, nie das neutrale Panel,
        und läuft vor allen anderen Bausteinen, damit deren Fehler es nicht stoppen."""
        script = report_web.SCRIPT
        self.assertIn("band.querySelector(':scope > section')", script)
        self.assertIn("sheet.style.zoom", script)
        self.assertLess(script.index("versuch('Schlussseite'"), script.index("versuch('Filter'"))


if __name__ == "__main__":
    unittest.main()
