"""Normalisierung der Plattform-Antworten in check-geo.

Der Schwerpunkt liegt auf Google AI. Die Skill gleicht die Shop-Domain gegen
die `citations` ab und wirft dabei den Google-Redirect-Host aus. Liefert der
Code nur Redirect-URLs, findet sie nie eine Übereinstimmung und meldet für
jeden Shop "nicht zitiert", ohne dass irgendwo ein Fehler auftaucht. Genau das
war am 07.09.2026 der Fall, nachdem Google die Quelldomain von `web.domain`
nach `web.title` verschoben hatte.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL / "skills" / "check-geo" / "scripts"))

import geo_api  # noqa: E402

REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ"


def antwort(chunks, text="egal"):
    """Eine Gemini-Antwort, wie post_json sie zurückgibt."""
    return {"candidates": [{"content": {"parts": [{"text": text}]},
                            "groundingMetadata": {"groundingChunks": chunks}}],
            "modelVersion": "gemini-3.6-flash"}


class TestHostnameErkennung(unittest.TestCase):
    def test_blanke_domains_zaehlen(self):
        for value in ("reddit.com", "fachblog.example", "beispielshop.example",
                     "shop.example.co.uk", "xn--mller-kva.de"):
            self.assertTrue(geo_api._ist_hostname(value), value)

    def test_seitentitel_zaehlt_nicht(self):
        # Sonst liefe der Domain-Abgleich der Skill gegen Fließtext, und ein
        # Titel mit dem Markennamen darin wäre ein falscher Treffer.
        for value in ("Ledertasche | Startseite", "Die 7 besten Ledertaschen",
                     "reddit", "", "   ", "https://reddit.com",
                     "reddit.com/r/watches", "-start.de", "reddit.c0m"):
            self.assertFalse(geo_api._ist_hostname(value), repr(value))


class TestGoogleAI(unittest.TestCase):
    def setUp(self):
        self._alt = geo_api.post_json
        self.addCleanup(lambda: setattr(geo_api, "post_json", self._alt))

    def antworte_mit(self, resp):
        geo_api.post_json = lambda *a, **k: resp

    def test_quelldomain_aus_title_landet_in_den_citations(self):
        # Die Shape der Live-API, geprüft am 07.09.2026.
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT + "1", "title": "reddit.com"}},
                                   {"web": {"uri": REDIRECT + "2", "title": "beispielshop.example"}}]))
        c = geo_api.query_google_ai("k", "q", 10)["citations"]
        self.assertIn("beispielshop.example", c)
        self.assertIn("reddit.com", c)

    def test_domain_wird_weiter_verstanden(self):
        # Falls Google das Feld zurückbringt, darf nichts umgebaut werden.
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT, "domain": "ndr.de"}}]))
        self.assertIn("ndr.de", geo_api.query_google_ai("k", "q", 10)["citations"])

    def test_die_redirect_url_bleibt_erhalten(self):
        # Die Skill wirft sie selbst aus; hier abschneiden hieße Belege werfen.
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT, "title": "reddit.com"}}]))
        self.assertIn(REDIRECT, geo_api.query_google_ai("k", "q", 10)["citations"])

    def test_ohne_verwertbare_domain_bleibt_es_bei_der_url(self):
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT, "title": "Die besten Rollen"}}]))
        self.assertEqual(geo_api.query_google_ai("k", "q", 10)["citations"], [REDIRECT])

    def test_grosschreibung_wird_vereinheitlicht(self):
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT, "title": "Beispielshop.EXAMPLE"}}]))
        self.assertIn("beispielshop.example", geo_api.query_google_ai("k", "q", 10)["citations"])

    def test_dubletten_fallen_weg(self):
        self.antworte_mit(antwort([{"web": {"uri": REDIRECT, "title": "reddit.com"}},
                                   {"web": {"uri": REDIRECT, "title": "reddit.com"}}]))
        self.assertEqual(geo_api.query_google_ai("k", "q", 10)["citations"],
                         [REDIRECT, "reddit.com"])

    def test_fehlendes_grounding_ist_kein_fehler(self):
        # Keine Quelle heißt: die Frage hat nichts getroffen, nicht: Absturz.
        self.antworte_mit({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})
        r = geo_api.query_google_ai("k", "q", 10)
        self.assertEqual(r["citations"], [])
        self.assertEqual(r["answer_text"], "hi")

    def test_kaputte_chunks_werfen_nicht(self):
        self.antworte_mit(antwort([None, "quatsch", {}, {"web": None},
                                   {"web": {"title": "ndr.de"}}]))
        self.assertEqual(geo_api.query_google_ai("k", "q", 10)["citations"], ["ndr.de"])


class TestResolveKey(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name)
        self.central = self.ws / "central.env"
        old = geo_api.operator_env.CENTRAL
        geo_api.operator_env.CENTRAL = self.central
        self.addCleanup(setattr, geo_api.operator_env, "CENTRAL", old)
        saved = os.environ.pop("PTAI_GEMINI_KEY", None)
        if saved is not None:
            self.addCleanup(os.environ.__setitem__, "PTAI_GEMINI_KEY", saved)

    def test_key_from_the_central_file(self):
        self.central.write_text("PTAI_GEMINI_KEY=zentral\n", encoding="utf-8")
        self.assertEqual(geo_api.resolve_key("google-ai", None, self.ws), "zentral")

    def test_dash_counts_as_no_argument(self):
        # Bis 11.09.2026 ging "-" als wörtlicher Key an die API, wenn sonst keiner stand.
        with self.assertRaises(SystemExit):
            geo_api.resolve_key("google-ai", "-", self.ws)

    def test_argument_is_the_last_resort(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            result = geo_api.resolve_key("google-ai", "aus-argument", self.ws)
        self.assertEqual(result, "aus-argument")
        self.assertIn("Prozessliste", out.getvalue())

    def test_explicit_argument_is_ignored_when_a_key_is_found_elsewhere(self):
        # Bis 11.09.2026 verschwand das Argument hier still: ein --check mit
        # explizitem Key testete dann einen anderen Key als den übergebenen.
        self.central.write_text("PTAI_GEMINI_KEY=zentral\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            result = geo_api.resolve_key("google-ai", "aus-argument", self.ws)
        self.assertEqual(result, "zentral")
        self.assertIn("wird ignoriert", out.getvalue())
        self.assertIn("PTAI_GEMINI_KEY", out.getvalue())

    def test_the_hint_names_the_source_not_the_value(self):
        self.central.write_text("PTAI_GEMINI_KEY=das-geheimnis\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            geo_api.resolve_key("google-ai", "aus-argument", self.ws)
        self.assertIn("zentral", out.getvalue())
        self.assertNotIn("das-geheimnis", out.getvalue())

    def test_dash_as_argument_is_never_reported_as_ignored(self):
        # "-" ist der Platzhalter für "kein Argument" und damit kein
        # ignoriertes Argument, das einen Hinweis verdiente.
        self.central.write_text("PTAI_GEMINI_KEY=zentral\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            geo_api.resolve_key("google-ai", "-", self.ws)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
