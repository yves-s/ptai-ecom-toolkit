"""Keine Verweise auf interne Ablagen im Plugin (Spec 2026-09-11 public release, C3).

Zwei Arten standen bis Teil C in Kommentaren: Pfade in Yves' Wissensablage
(`09-brand/`, `06-wissen/`) und Pfade nach `docs/`, das in der öffentlichen
Fassung fehlt. Keiner davon ist eine Abhängigkeit, aber jeder schickt einen
fremden Leser an einen Ort, den es für ihn nicht gibt.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from tests import repo_files  # noqa: E402

SUFFIXES = (".py", ".md", ".sh", ".json", ".html", ".css", ".mjs", ".txt")

#: Ein nummerierter Ordner der Wissensablage, etwa `06-wissen/`. Davor steht kein
#: Wortzeichen, Punkt, Schrägstrich oder Bindestrich, sonst träfe es Lauf-IDs wie
#: `2026-10-01-audit/`.
KNOWLEDGE_BASE = re.compile(r"(?<![\w./-])0\d-[a-z]+/")

#: Ein Pfad nach `docs/`, nicht der Teil einer URL wie `shopify.dev/docs/`.
DOCS = re.compile(r"(?<![\w./-])docs/[\w./-]*\w")

#: Was nicht in die öffentliche Fassung geht (release/exclude.txt).
NOT_PUBLIC = ("docs/", "release/", "CLAUDE.md")

#: Diese Datei und `test_no_workos.py` nennen die Muster selbst.
EXEMPT = {"scripts/tests/test_no_internal_references.py", "scripts/tests/test_no_workos.py"}


def public_lines():
    for name, text in repo_files.text_files(ROOT, SUFFIXES, exempt=EXEMPT):
        if name.startswith(NOT_PUBLIC):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            yield name, number, line


class TestNoInternalReferences(unittest.TestCase):
    def test_the_patterns_catch_what_stood_there(self):
        for sample in ("Abgeleitet aus 09-brand/STYLEGUIDE.md.", "(`06-wissen/dataforseo/`)"):
            with self.subTest(sample=sample):
                self.assertTrue(KNOWLEDGE_BASE.search(sample))
        for sample in ("reporting/runs/2026-01-01-audit/state.json", "data/2026-10-01-audit/x.json"):
            with self.subTest(sample=sample):
                self.assertIsNone(KNOWLEDGE_BASE.search(sample))
        self.assertTrue(DOCS.search("(Spec `docs/specs/2026-09-11-operator-setup-and-source-tiers-design.md`)"))
        self.assertIsNone(DOCS.search("shopify.dev/docs/api/shopifyql"))
        self.assertIsNone(DOCS.search("außerhalb von docs/."))

    def test_no_path_into_the_knowledge_base(self):
        hits = [f"{name}:{number}" for name, number, line in public_lines() if KNOWLEDGE_BASE.search(line)]
        self.assertEqual(hits, [])

    def test_no_path_into_docs(self):
        hits = [f"{name}:{number}" for name, number, line in public_lines() if DOCS.search(line)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
