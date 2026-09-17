"""Das Schluss-Panel trägt nur die Kontaktfakten des Betreibers (Entscheidung 15.09.2026).

`audit.closing` rendert das Ende des großen Audits und des Monats-Reports, für
beide identisch: eine Kontaktzeile je gesetzter und gültiger Einstellung
(`PTAI_OPERATOR_NAME`, `PTAI_OPERATOR_CONTACT`, `PTAI_OPERATOR_EMAIL`,
`PTAI_OPERATOR_BOOKING_URL`), darunter immer die Herkunftszeile. Ohne eine
gültige Einstellung bleibt nur die Herkunftszeile.

`apply()` setzt den Schluss in ein fertiges Dokument ein (zweiter Teil der
Entscheidung vom 15.09.2026): die Schlussseite aus `PTAI_CLOSING_FILE` zwischen
die Markierungen, sonst den neutralen Schluss für den Platzhalter. Die
Markierungen bleiben stehen, ein zweiter Aufruf auf derselben Datei findet
dieselbe Stelle.

Die echte zentrale Datei wird nie gelesen: auf dem Rechner eines Betreibers
stehen dort echte Werte, und der Test wäre dort grün und anderswo rot. Alle
Werte hier sind erfunden.
"""
import contextlib
import html
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import closing, env

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

NAME = "Beispiel GmbH"
CONTACT = "Mara Beispiel"
EMAIL = "kontakt@beispielshop.example"
BOOKING = "https://termine.example/30min"

SETTINGS = ("PTAI_OPERATOR_NAME", "PTAI_OPERATOR_CONTACT", "PTAI_OPERATOR_EMAIL",
            "PTAI_OPERATOR_BOOKING_URL", "PTAI_CLOSING_FILE")

ORIGIN_HTML = 'Erstellt mit ptai-ecom von <a href="https://path-to-ai.com">Path to AI</a>.'
ORIGIN_MD = "Erstellt mit ptai-ecom von [Path to AI](https://path-to-ai.com)."

LABEL = '<p class="eyebrow eyebrow--line">Kontakt</p>'

#: Sätze und Wörter, die im alten Panel standen und nie wieder auftauchen dürfen:
#: das Verkaufs-PDF-Zitat im Audit, der Mail-Schluss im Monats-Report. Der
#: Button-Text ist zusammengesetzt, damit die Suche nach dem alten Schluss des
#: Verkaufs-PDFs nicht diese Datei findet.
FORBIDDEN = ("Gespräch", "priorisieren", "Termin " + "vereinbaren", "meldet euch",
            "Wie es weitergeht", "Werkzeug")

START = "<!-- CLOSING:start -->"
END = "<!-- CLOSING:end -->"

#: Eine erfundene Schlussseite in der Form, die `PTAI_CLOSING_FILE` verlangt.
FRAGMENT = ('<section class="beispiel-abbinder" '
            'style="break-before:page;width:210mm;height:297mm">Beispiel-Abbinder</section>\n')

#: Ein Dokument mit dem Schluss-Panel zwischen den Markierungen, gebaut wie die
#: beiden Vorlagen.
PAGE = ("<body>\n<div class=\"content\">Inhalt</div>\n"
        f"{START}\n"
        "<footer class=\"closing\">\n"
        "  <img class=\"logo-reversed\" src=\"logo-reversed.svg\" alt=\"\">\n"
        "  __CLOSING__\n"
        "  <div class=\"panel-footer\"><span>Fußzeile</span></div>\n"
        "</footer>\n"
        f"{END}\n"
        "</body>\n")

#: Dasselbe Dokument ohne die Markierungen.
PAGE_WITHOUT_MARKERS = PAGE.replace(f"{START}\n", "").replace(f"{END}\n", "")


def with_page(fragment: str = FRAGMENT, page: str = PAGE) -> str:
    """`page` mit `fragment` zwischen den Markierungen, so wie `apply()` es einsetzt:
    die Markierungen bleiben, die Seite steht auf eigenen Zeilen dazwischen."""
    start, end = page.index(START), page.index(END) + len(END)
    body = fragment if fragment.endswith("\n") else fragment + "\n"
    return page[:start] + f"{START}\n{body}{END}" + page[end:]

ROW = re.compile(r'<div class="summary-label">(.*?)</div>'
                 r'<div class="summary-value">(.*?)</div></div>')


def plain(markup: str) -> str:
    """Sichtbarer Text: Tags weg, Entities aufgelöst, Leerraum zusammengezogen."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", markup)).split())


def rows(markup: str) -> list[tuple[str, str]]:
    """Die Kontaktzeilen als (Label, sichtbarer Wert)."""
    return [(plain(label), plain(value)) for label, value in ROW.findall(markup)]


class Base(unittest.TestCase):
    """Leerer Workspace, eigene zentrale Datei, keine Einstellung in der Umgebung."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = self.base = Path(tmp.name)
        self.ws = base / "workspace"
        self.ws.mkdir()
        (base / "home").mkdir()
        self.central = base / "central.env"
        for patcher in (mock.patch.object(env, "CENTRAL", self.central),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ["HOME"] = str(base / "home")
        os.environ["PTAI_ENV_FILE"] = str(self.central)
        for name in SETTINGS:
            os.environ.pop(name, None)

    def configure(self, **values):
        """Schreibt die Einstellungen in die zentrale Test-Datei, ersetzt den Inhalt."""
        self.central.write_text("".join(f"{k}={v}\n" for k, v in values.items()),
                                encoding="utf-8")

    def configure_all(self):
        self.configure(PTAI_OPERATOR_NAME=NAME, PTAI_OPERATOR_CONTACT=CONTACT,
                       PTAI_OPERATOR_EMAIL=EMAIL, PTAI_OPERATOR_BOOKING_URL=BOOKING)


class TestAuditHtml(Base):
    def test_all_settings(self):
        self.configure_all()
        out = closing.audit_html(self.ws)
        self.assertIn(LABEL, out)
        self.assertEqual(rows(out), [("Unternehmen", NAME), ("Ansprechpartner", CONTACT),
                                     ("E-Mail", EMAIL), ("Termin", "termine.example/30min")])
        self.assertIn(f'<a href="mailto:{EMAIL}">{EMAIL}</a>', out)
        self.assertIn(f'<a href="{BOOKING}">termine.example/30min</a>', out)
        self.assertIn(ORIGIN_HTML, out)
        # Reihenfolge: Label, Zeilen, Herkunft.
        order = [out.index(LABEL), out.index('class="summary"'), out.index(ORIGIN_HTML)]
        self.assertEqual(order, sorted(order))

    def test_no_settings_only_the_origin(self):
        out = closing.audit_html(self.ws)
        self.assertIn(ORIGIN_HTML, out)
        self.assertEqual(plain(out), plain(ORIGIN_HTML))
        for part in ("eyebrow", "Kontakt", "summary"):
            with self.subTest(part=part):
                self.assertNotIn(part, out)

    def test_a_contact_alone_is_enough(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        out = closing.audit_html(self.ws)
        self.assertIn(LABEL, out)
        self.assertEqual(rows(out), [("Ansprechpartner", CONTACT)])

    def test_javascript_booking_url_is_ignored(self):
        self.configure(PTAI_OPERATOR_EMAIL=EMAIL, PTAI_OPERATOR_BOOKING_URL="javascript:alert(1)")
        out = closing.audit_html(self.ws)
        self.assertNotIn("javascript", out.lower())
        self.assertEqual(rows(out), [("E-Mail", EMAIL)])

    def test_only_http_and_https_links(self):
        for url in ("JavaScript:alert(1)", "data:text/html,x", "ftp://termine.example/30min",
                    "//termine.example/30min", "termine.example/30min", "https://",
                    "https://termine.example/30 min"):
            with self.subTest(url=url):
                self.configure(PTAI_OPERATOR_BOOKING_URL=url)
                self.assertEqual(plain(closing.audit_html(self.ws)), plain(ORIGIN_HTML))
        self.configure(PTAI_OPERATOR_BOOKING_URL="http://termine.example/30min")
        self.assertIn('href="http://termine.example/30min"', closing.audit_html(self.ws))

    def test_booking_url_link_text_drops_the_scheme(self):
        self.configure(PTAI_OPERATOR_BOOKING_URL="https://cal.com/beispiel/30min")
        self.assertEqual(rows(closing.audit_html(self.ws)),
                         [("Termin", "cal.com/beispiel/30min")])

    def test_booking_url_link_text_drops_a_trailing_slash(self):
        self.configure(PTAI_OPERATOR_BOOKING_URL="https://cal.com/beispiel/30min/")
        self.assertEqual(rows(closing.audit_html(self.ws)),
                         [("Termin", "cal.com/beispiel/30min")])

    def test_invalid_email_is_ignored(self):
        for value in ("keine-adresse", "kontakt@beispielshop", "kontakt beispielshop.example",
                      "kontakt@beispiel shop.example", '"><b>@x.example', "a@b@beispiel.example"):
            with self.subTest(value=value):
                self.configure(PTAI_OPERATOR_CONTACT=CONTACT, PTAI_OPERATOR_EMAIL=value,
                               PTAI_OPERATOR_BOOKING_URL=BOOKING)
                out = closing.audit_html(self.ws)
                self.assertNotIn("mailto:", out)
                self.assertEqual(rows(out), [("Ansprechpartner", CONTACT),
                                             ("Termin", "termine.example/30min")])

    def test_a_name_that_is_not_set_gives_no_row_and_no_default(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        out = closing.audit_html(self.ws)
        self.assertEqual(rows(out), [("Ansprechpartner", CONTACT)])
        self.assertNotIn("Dienstleister", out)
        self.assertNotIn("Unternehmen", out)

    def test_values_are_escaped(self):
        self.configure(PTAI_OPERATOR_NAME="Beispiel <b>GmbH</b>",
                       PTAI_OPERATOR_CONTACT="Mara <b>Beispiel</b>",
                       PTAI_OPERATOR_EMAIL=EMAIL,
                       PTAI_OPERATOR_BOOKING_URL='https://termine.example/30min?a=1&b="2"')
        out = closing.audit_html(self.ws)
        self.assertNotIn("<b>", out)
        self.assertIn("Beispiel &lt;b&gt;GmbH&lt;/b&gt;", out)
        self.assertIn("Mara &lt;b&gt;Beispiel&lt;/b&gt;", out)
        self.assertIn('href="https://termine.example/30min?a=1&amp;b=&quot;2&quot;"', out)

    def test_the_workspace_wins_over_the_central_file(self):
        self.configure_all()
        (self.ws / ".env").write_text("PTAI_OPERATOR_CONTACT=Tom Beispiel\n", encoding="utf-8")
        self.assertIn(("Ansprechpartner", "Tom Beispiel"), rows(closing.audit_html(self.ws)))


class TestReportHtml(Base):
    def test_with_all_settings(self):
        self.configure_all()
        out = closing.report_html(self.ws)
        self.assertIn(LABEL, out)
        self.assertEqual(rows(out), [("Unternehmen", NAME), ("Ansprechpartner", CONTACT),
                                     ("E-Mail", EMAIL), ("Termin", "termine.example/30min")])
        self.assertIn(ORIGIN_HTML, out)
        self.assertLess(out.index('class="summary"'), out.index(ORIGIN_HTML))

    def test_a_contact_alone_is_enough(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        out = closing.report_html(self.ws)
        self.assertIn(LABEL, out)
        self.assertEqual(rows(out), [("Ansprechpartner", CONTACT)])

    def test_without_settings_only_the_origin(self):
        out = closing.report_html(self.ws)
        self.assertEqual(plain(out), plain(ORIGIN_HTML))
        self.assertNotIn("Kontakt", out)


class TestAuditAndReportAreIdentical(Base):
    def test_identical_with_settings(self):
        self.configure_all()
        self.assertEqual(closing.audit_html(self.ws), closing.report_html(self.ws))

    def test_identical_without_settings(self):
        self.assertEqual(closing.audit_html(self.ws), closing.report_html(self.ws))


class TestReportMarkdown(Base):
    def test_with_all_settings(self):
        self.configure_all()
        self.assertEqual(closing.report_markdown(self.ws),
                         f"## Kontakt\n\n"
                         f"- Unternehmen: {NAME}\n"
                         f"- Ansprechpartner: {CONTACT}\n"
                         f"- E-Mail: [{EMAIL}](mailto:{EMAIL})\n"
                         f"- Termin: [termine.example/30min]({BOOKING})\n\n"
                         f"{ORIGIN_MD}")

    def test_without_settings(self):
        self.assertEqual(closing.report_markdown(self.ws), ORIGIN_MD)

    def test_markdown_in_a_value_stays_text(self):
        self.configure(PTAI_OPERATOR_CONTACT="Mara [Beispiel](javascript:x) *fett* <b>")
        self.assertIn(r"- Ansprechpartner: Mara \[Beispiel\](javascript:x) \*fett\* \<b\>",
                      closing.report_markdown(self.ws))


class TestWording(Base):
    def outputs(self):
        return (closing.audit_html(self.ws), closing.report_html(self.ws),
                closing.report_markdown(self.ws))

    def test_no_output_says_werkzeug(self):
        for setup in (lambda: None, self.configure_all):
            setup()
            for out in self.outputs():
                self.assertNotIn("werkzeug", out.lower())

    def test_no_output_contains_the_old_sentences(self):
        for label, setup in (("leer", lambda: None), ("konfiguriert", self.configure_all)):
            setup()
            for out in self.outputs():
                for phrase in FORBIDDEN:
                    with self.subTest(setup=label, phrase=phrase):
                        self.assertNotIn(phrase, out)

    def test_real_umlauts_and_no_dashes(self):
        self.configure(PTAI_OPERATOR_NAME="Bärenstärke GmbH", PTAI_OPERATOR_CONTACT=CONTACT)
        for out in self.outputs():
            self.assertNotIn("—", out)
            self.assertNotIn("–", out)

    def test_every_class_has_a_rule(self):
        self.configure_all()
        css = (ROOT / "assets" / "brand" / "report.css").read_text(encoding="utf-8")
        for out in (closing.audit_html(self.ws), closing.report_html(self.ws)):
            for attr in re.findall(r'class="([^"]+)"', out):
                for name in attr.split():
                    with self.subTest(css_class=name):
                        self.assertIn(f".{name}", css)


class TestApply(Base):
    """Der Schluss im fertigen Dokument: Schlussseite des Betreibers oder neutral."""

    def fragment(self, path: Path, text: str = FRAGMENT) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    def apply(self, page: str = PAGE) -> tuple[str, str]:
        """Das Ergebnis von `apply()` und alles, was dabei auf stderr landet."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = closing.apply(page, self.ws)
        return out, err.getvalue()

    def neutral(self, page: str = PAGE) -> str:
        return page.replace("__CLOSING__", closing.report_html(self.ws))

    def test_a_usable_file_replaces_what_is_between_the_markers(self):
        path = self.fragment(self.base / "schlussseite.html")
        self.configure(PTAI_CLOSING_FILE=path, PTAI_OPERATOR_CONTACT=CONTACT)
        out, err = self.apply()
        start, end = PAGE.index(START), PAGE.index(END) + len(END)
        self.assertEqual(out, PAGE[:start] + f"{START}\n{FRAGMENT}{END}" + PAGE[end:])
        self.assertEqual((out.count(START), out.count(END)), (1, 1))
        for gone in ('<footer class="closing">', "__CLOSING__", "Erstellt mit", CONTACT):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, out)
        self.assertEqual(err, "")

    def test_a_page_without_a_final_newline_ends_its_own_line(self):
        self.configure(PTAI_CLOSING_FILE=self.fragment(self.base / "schlussseite.html",
                                                       FRAGMENT.rstrip("\n")))
        self.assertEqual(self.apply()[0], with_page(FRAGMENT))

    def test_without_the_setting_the_neutral_closing(self):
        self.configure_all()
        out, err = self.apply()
        self.assertEqual(out, self.neutral())
        self.assertIn('<footer class="closing">', out)
        self.assertIn(("Ansprechpartner", CONTACT), rows(out))
        self.assertIn(ORIGIN_HTML, out)
        self.assertEqual((out.count(START), out.count(END)), (1, 1))
        self.assertEqual(err, "")

    # ---- ein zweiter Aufruf auf dem fertigen Dokument ----

    def test_the_same_page_twice_gives_the_same_document(self):
        self.configure(PTAI_CLOSING_FILE=self.fragment(self.base / "schlussseite.html"))
        once = self.apply()[0]
        twice, err = self.apply(once)
        self.assertEqual(twice, once)
        self.assertEqual(err, "")

    def test_a_new_page_replaces_an_earlier_page(self):
        path = self.fragment(self.base / "schlussseite.html")
        self.configure(PTAI_CLOSING_FILE=path)
        once = self.apply()[0]
        newer = FRAGMENT.replace("Beispiel-Abbinder", "Neuer Abbinder")
        self.fragment(path, newer)
        out, err = self.apply(once)
        self.assertEqual(out, with_page(newer))
        self.assertNotIn("Beispiel-Abbinder", out)
        self.assertEqual(err, "")

    def test_a_page_replaces_an_earlier_neutral_closing(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        neutral = self.apply()[0]
        self.assertIn(CONTACT, neutral)
        self.configure(PTAI_CLOSING_FILE=self.fragment(self.base / "schlussseite.html"))
        out, err = self.apply(neutral)
        self.assertEqual(out, with_page(FRAGMENT))
        self.assertEqual(err, "")

    def test_without_the_setting_a_page_stays_and_one_line_says_why(self):
        self.configure(PTAI_CLOSING_FILE=self.fragment(self.base / "schlussseite.html"))
        earlier = self.apply()[0]
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        out, err = self.apply(earlier)
        self.assertEqual(out, earlier)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("Vorlage", err)

    def test_without_the_setting_a_filled_panel_stays_and_one_line_says_why(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        earlier = self.apply()[0]
        self.configure(PTAI_OPERATOR_CONTACT="Tom Beispiel")
        out, err = self.apply(earlier)
        self.assertEqual(out, earlier)
        self.assertNotIn("Tom Beispiel", out)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("Vorlage", err)

    def test_a_vanished_file_leaves_the_earlier_page_with_two_lines(self):
        path = self.fragment(self.base / "schlussseite.html")
        self.configure(PTAI_CLOSING_FILE=path)
        earlier = self.apply()[0]
        path.unlink()
        out, err = self.apply(earlier)
        self.assertEqual(out, earlier)
        lines = err.splitlines()
        self.assertEqual(len(lines), 2, err)
        self.assertIn("PTAI_CLOSING_FILE", lines[0])
        self.assertIn("Vorlage", lines[1])

    def test_a_page_that_contains_a_marker_is_refused(self):
        # Ein END in der Seite beendete den Abschnitt beim nächsten Aufruf mitten
        # in ihr, ein Platzhalter darin würde ohne Einstellung neutral gefüllt.
        path = self.base / "schlussseite.html"
        for marker in (START, END, "__CLOSING__"):
            with self.subTest(marker=marker):
                self.fragment(path, FRAGMENT.replace("Beispiel-Abbinder",
                                                     f"Beispiel {marker} Abbinder"))
                self.configure(PTAI_CLOSING_FILE=path)
                for document in (PAGE, with_page(FRAGMENT)):
                    with self.assertRaises(ValueError) as caught:
                        closing.apply(document, self.ws)
                    self.assertIn(marker, str(caught.exception))
                    self.assertIn(str(path), str(caught.exception))
                    self.assertNotIn("\n", str(caught.exception))

    def test_an_unusable_file_gives_the_neutral_closing_and_one_warning(self):
        folder = self.base / "ordner"
        folder.mkdir()
        broken = self.base / "kein-utf8.html"
        broken.write_bytes(b"<section>\xff\xfe</section>")
        for label, path in (("fehlt", self.base / "fehlt.html"),
                            ("leer", self.fragment(self.base / "leer.html", " \n\n")),
                            ("Ordner", folder),
                            ("kein UTF-8", broken)):
            with self.subTest(file=label):
                self.configure(PTAI_CLOSING_FILE=path, PTAI_OPERATOR_CONTACT=CONTACT)
                out, err = self.apply()
                self.assertEqual(out, self.neutral())
                self.assertIn(("Ansprechpartner", CONTACT), rows(out))
                self.assertEqual(len(err.splitlines()), 1, err)
                self.assertIn("PTAI_CLOSING_FILE", err)

    def test_a_leading_tilde_is_expanded(self):
        self.fragment(self.base / "home" / "schlussseite.html")
        self.configure(PTAI_CLOSING_FILE="~/schlussseite.html")
        out, err = self.apply()
        self.assertIn(FRAGMENT, out)
        self.assertEqual(err, "")

    def test_the_environment_sets_the_file_too(self):
        os.environ["PTAI_CLOSING_FILE"] = str(self.fragment(self.base / "schlussseite.html"))
        self.assertIn(FRAGMENT, self.apply()[0])

    def test_a_configured_file_without_markers_raises(self):
        self.configure(PTAI_CLOSING_FILE=self.fragment(self.base / "schlussseite.html"))
        with self.assertRaises(ValueError) as caught:
            closing.apply(PAGE_WITHOUT_MARKERS, self.ws)
        self.assertIn(START, str(caught.exception))

    def test_without_the_setting_missing_markers_are_no_error(self):
        self.assertEqual(self.apply(PAGE_WITHOUT_MARKERS)[0], self.neutral(PAGE_WITHOUT_MARKERS))


class TestCli(Base):
    def run_cli(self, *args, cwd=SCRIPTS):
        clean = dict(os.environ, PYTHONPATH=str(SCRIPTS), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-m", "audit.closing", *args], cwd=cwd,
                              env=clean, capture_output=True, text=True, timeout=60)

    def test_report_html(self):
        self.configure_all()
        result = self.run_cli("report-html", str(self.ws))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), closing.report_html(self.ws).strip())

    def test_report_md_from_the_workspace(self):
        # So ruft die Report-Skill es auf: im Workspace, mit Punkt.
        (self.ws / ".env").write_text(f"PTAI_OPERATOR_CONTACT={CONTACT}\n", encoding="utf-8")
        result = self.run_cli("report-md", ".", cwd=self.ws)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"- Ansprechpartner: {CONTACT}", result.stdout)
        self.assertTrue(result.stdout.rstrip().endswith(ORIGIN_MD))

    def test_unknown_command(self):
        result = self.run_cli("pdf")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_apply_rewrites_the_file_with_the_closing_page(self):
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.configure(PTAI_CLOSING_FILE=fragment)
        page = self.ws / "report.html"
        page.write_text(PAGE, encoding="utf-8")
        result = self.run_cli("apply", str(page), str(self.ws))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = page.read_text(encoding="utf-8")
        self.assertEqual(text, with_page(FRAGMENT))
        self.assertNotIn('<footer class="closing">', text)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn("PTAI_CLOSING_FILE", result.stdout)

    def test_apply_twice_with_the_closing_page_gives_the_same_file(self):
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.configure(PTAI_CLOSING_FILE=fragment)
        page = self.ws / "report.html"
        page.write_text(PAGE, encoding="utf-8")
        self.assertEqual(self.run_cli("apply", str(page), str(self.ws)).returncode, 0)
        result = self.run_cli("apply", str(page), str(self.ws))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(page.read_text(encoding="utf-8"), with_page(FRAGMENT))
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn("PTAI_CLOSING_FILE", result.stdout)

    def test_apply_with_the_closing_page_after_the_neutral_closing(self):
        self.configure(PTAI_OPERATOR_CONTACT=CONTACT)
        page = self.ws / "report.html"
        page.write_text(PAGE, encoding="utf-8")
        self.assertEqual(self.run_cli("apply", str(page), str(self.ws)).returncode, 0)
        self.assertIn(CONTACT, page.read_text(encoding="utf-8"))
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.configure(PTAI_CLOSING_FILE=fragment)
        result = self.run_cli("apply", str(page), str(self.ws))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(page.read_text(encoding="utf-8"), with_page(FRAGMENT))

    def test_apply_without_the_setting_leaves_an_earlier_closing(self):
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        for label, first in (("Schlussseite", {"PTAI_CLOSING_FILE": fragment}),
                             ("neutral", {"PTAI_OPERATOR_CONTACT": CONTACT})):
            with self.subTest(earlier=label):
                page = self.ws / "report.html"
                page.write_text(PAGE, encoding="utf-8")
                self.configure(**first)
                self.assertEqual(self.run_cli("apply", str(page), str(self.ws)).returncode, 0)
                before, mtime = page.read_bytes(), page.stat().st_mtime_ns
                self.configure(PTAI_OPERATOR_CONTACT="Tom Beispiel")
                result = self.run_cli("apply", str(page), str(self.ws))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(page.read_bytes(), before)
                self.assertEqual(page.stat().st_mtime_ns, mtime, "Datei neu geschrieben")
                self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
                self.assertIn("Vorlage", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_apply_refuses_a_closing_page_with_a_marker_and_leaves_the_file(self):
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT.replace("Beispiel-Abbinder", f"Beispiel {END}"),
                            encoding="utf-8")
        self.configure(PTAI_CLOSING_FILE=fragment)
        page = self.ws / "report.html"
        page.write_text(PAGE, encoding="utf-8")
        result = self.run_cli("apply", str(page), str(self.ws))
        self.assertEqual(result.returncode, 1)
        self.assertIn(END, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(page.read_text(encoding="utf-8"), PAGE)

    def test_apply_from_the_workspace_without_the_setting(self):
        # So ruft die Report-Skill es auf: im Workspace, Datei relativ, mit Punkt.
        (self.ws / ".env").write_text(f"PTAI_OPERATOR_CONTACT={CONTACT}\n", encoding="utf-8")
        page = self.ws / "reporting" / "reports" / "2026-09-monthly.html"
        page.parent.mkdir(parents=True)
        page.write_text(PAGE, encoding="utf-8")
        result = self.run_cli("apply", "reporting/reports/2026-09-monthly.html", ".", cwd=self.ws)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(page.read_text(encoding="utf-8"),
                         PAGE.replace("__CLOSING__", closing.report_html(self.ws)))
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertIn("neutral", result.stdout)

    def test_apply_without_markers_fails_and_leaves_the_file(self):
        fragment = self.base / "schlussseite.html"
        fragment.write_text(FRAGMENT, encoding="utf-8")
        self.configure(PTAI_CLOSING_FILE=fragment)
        page = self.ws / "report.html"
        page.write_text(PAGE_WITHOUT_MARKERS, encoding="utf-8")
        result = self.run_cli("apply", str(page), str(self.ws))
        self.assertEqual(result.returncode, 1)
        self.assertIn(START, result.stderr)
        self.assertEqual(page.read_text(encoding="utf-8"), PAGE_WITHOUT_MARKERS)


if __name__ == "__main__":
    unittest.main()
