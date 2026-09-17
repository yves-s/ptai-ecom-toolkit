"""Kein Kundenbezug im Plugin (Spec 2026-09-11 public release, C2).

**Warum das ein Test ist und keine grep-Zeile in der CLAUDE.md.** Dort stand
bis zum 08.09.2026 `grep -rinE "kundenname|shop\\.myshopify"`. Der Befehl sucht
das Wort "kundenname", findet also jeden Platzhalter und keinen echten Namen,
und Zahlen sucht er gar nicht. Auf origin lagen daraufhin die Sitemap-Größe
und die Variantenzahl eines echten Shops, in Kommentaren, als Begründung für
eine Codezeile.

Ein Test läuft bei jedem `run_tests.sh` mit. Eine Prosa-Regel läuft, wenn
jemand daran denkt.

**Woher die Namen kommen: nicht aus dieser Datei.** Eine Liste von
Kundennamen in einem Repo ist selbst der Kundenbezug, den dieser Test
verhindern soll. Bis Teil C standen hier trotzdem sechs Kundennamen als
Ausnahmen und sechs Zahlen aus echten Läufen, und gesucht wurde nur nach
Ordnernamen: keine Marke, die nicht im Ordnernamen steckt, kein Kontakt, kein
Wettbewerber. Jetzt liefert `release/customer_terms.py` Namen, Domains und
Zahlen aus Quellen außerhalb von git, die Ausnahmen stehen in `allow.txt`
daneben.

**Die öffentliche Fassung hat diese Listen nicht.** Dort fehlt `release/`, die
Prüfung gegen die Listen überspringt sich mit einer Meldung, die Prüfungen nach
Form laufen überall. Kaputte Listen überspringen nichts: sie machen den Test rot.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from tests import repo_files  # noqa: E402

SUFFIXES = (".py", ".md", ".sh", ".json", ".html", ".css", ".mjs", ".txt")

#: Namen, die im Repo als Beispiel gedacht sind. Sie sind der Grund, warum die
#: Muster unten eine Ausnahmeliste brauchen: ein Muster ohne sie meldet jeden
#: Platzhalter, und ein Prüfer mit Fehlalarm wird nach dem zweiten Mal
#: ignoriert. Geprüft wird der Anfang, nicht die Gleichheit: `beispielshop-de`
#: und `beispiel-store` sind beide Platzhalter.
PLACEHOLDER_STORES = ("beispiel", "shop.", "test")

#: Property-Nummern, die erkennbar erfunden sind: lauter Nullen, aufsteigende
#: oder absteigende Ziffern, runde Zahlen.
PLACEHOLDER_NUMBERS = {"000000000", "123456789", "987654321",
                       "450000000", "310000000", "111111111"}

#: Muster, die ohne Listen greifen, weil sie an der Form erkennbar sind.
SHAPES = (
    # ein Shopify-Store, der nicht als Platzhalter erkennbar ist
    (re.compile(r"\b([a-z0-9][a-z0-9-]{2,})\.myshopify\.com", re.IGNORECASE),
     "ein echter Shopify-Store", lambda m: m.group(1).lower().startswith(PLACEHOLDER_STORES)),
    # eine GA4-Property-Nummer: neun Ziffern, allein stehend
    (re.compile(r"(?<![\d.])\d{9}(?![\d.])"),
     "eine GA4-Property-Nummer", lambda m: m.group(0) in PLACEHOLDER_NUMBERS),
)

#: Dateien, in denen ein Treffer erlaubt ist: nur dieser Test selbst.
#:
#: Bis zum 11.09.2026 stand hier auch `report-pdf-full.mjs`, wegen der Zitate
#: zweier Kundenkontakte samt Porträt im Verkaufs-PDF. Die sind raus, weil eine
#: Freigabe für ein PDF an Leads keine Freigabe für ein öffentliches Repo ist
#: (Spec 2026-09-11, D3). **Wer hier eine Datei einträgt, muss sagen können,
#: wer die Freigabe gegeben hat.**
EXEMPT = {"scripts/tests/test_no_customer_data.py"}


def _customer_terms():
    """Das Modul und seine Begriffe, oder der Grund, warum es sie hier nicht gibt."""
    if not (ROOT / "release" / "customer_terms.py").is_file():
        return None, None, "release/customer_terms.py fehlt, das ist die öffentliche Fassung"
    if str(ROOT) not in sys.path:
        sys.path.insert(1, str(ROOT))
    from release import customer_terms
    try:
        return customer_terms, customer_terms.load(), None
    except customer_terms.TermsUnavailable as exc:
        return None, None, f"auf diesem Rechner gibt es keine Listen ({exc})"


class TestNoCustomerData(unittest.TestCase):
    def setUp(self):
        self.files = list(repo_files.text_files(ROOT, SUFFIXES, exempt=EXEMPT))
        self.assertTrue(self.files, "keine Datei gefunden")

    def test_no_customer_term_appears_in_the_plugin(self):
        """Kundenordner, Lead-Tabelle, Denylist: jeder Treffer nennt öffentlich
        einen Kunden, einen Lead, einen Kontakt oder eine Zahl aus einem echten Lauf."""
        module, terms, reason = _customer_terms()
        if terms is None:
            self.skipTest(f"Prüfung gegen die Listen entfällt: {reason}")
        exclude = module.read_exclude(ROOT / "release" / "exclude.txt")
        # Die Meldung nennt Datei, Zeile und Art, nie den Begriff: diese Suite
        # läuft auf Yves' Rechner in Sitzungen, deren Verlauf gespeichert wird.
        hits = [f"{name}:{hit.line} {hit.kind}"
                for name, text in self.files if not module.is_excluded(name, exclude)
                for hit in module.find(text, terms)
                if not module.is_allowed(name, hit, terms)]
        self.assertEqual(hits, [])

    def test_no_customer_identifier_by_shape(self):
        """Greift auch ohne Listen: ein Store-Name oder eine Property-Nummer ist
        an ihrer Form erkennbar, ohne dass jemand eine Liste pflegt."""
        for pattern, what, is_placeholder in SHAPES:
            hits = sorted({f"{name}: {match.group(0)}"
                           for name, text in self.files
                           for match in pattern.finditer(text)
                           if not is_placeholder(match)})
            with self.subTest(what=what):
                self.assertEqual(hits, [], f"{what} steht in: {hits}")

    def test_the_placeholder_shop_is_the_one_we_use(self):
        """Gegenprobe: der vorgesehene Platzhalter kommt wirklich vor. Ohne
        diesen Test könnte jemand alle Beispiele entfernen und der Test oben
        wäre still grün."""
        hits = [name for name, text in self.files if "beispielshop" in text.lower()]
        self.assertTrue(hits, "kein einziges Beispiel nutzt beispielshop")


class TestNoCustomerVoices(unittest.TestCase):
    """Porträts und Zitate der zwei Kundenkontakte sind raus (Spec 2026-09-11, D3).

    Eine Freigabe für ein PDF an Leads ist keine Freigabe für ein öffentliches
    Repo. Bis zum 11.09.2026 stand `report-pdf-full.mjs` deshalb unter den
    Ausnahmen, und die Namensprüfung sah in diese Datei gar nicht hinein.
    """

    def test_only_this_test_is_exempt(self):
        self.assertEqual(EXEMPT, {"scripts/tests/test_no_customer_data.py"})

    def test_no_portrait_is_tracked(self):
        # Seit dem 15.09.2026 auch das des Betreibers nicht mehr: die letzte
        # Seite jedes Dokuments kommt aus PTAI_CLOSING_FILE, außerhalb des Repos.
        portraits = [name for name in repo_files.tracked(ROOT)
                     if name.startswith("assets/brand/portraits/")]
        self.assertEqual(portraits, [])


class TestNoListsInThisFile(unittest.TestCase):
    def test_no_hand_kept_names_numbers_or_drive(self):
        """Gegenprobe zu C2: die alten Listen und der Pfad in den Drive kommen
        nicht zurück. Die Marken sind zusammengesetzt, sonst träfe der Test sich selbst."""
        text = Path(__file__).read_text(encoding="utf-8")
        for marker in ("ZU_" + "GENERISCH", "ECHTE_" + "ZAHLEN", "pathto" + "ai", "Path.home" + "()"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
