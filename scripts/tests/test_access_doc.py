"""Die Kundenanforderung in reference/access.md gegen tiers.py (Spec 2026-09-11, 3.4)."""
import re
import unittest
from pathlib import Path

from audit import tiers

ACCESS = Path(__file__).resolve().parents[2] / "reference" / "access.md"

#: Einträge in Teil B ohne Stufe, je mit Grund.
EXPLAINED = {
    # Der Pilot pull-klaviyo hängt noch nicht an run.SOURCE_CADENCE; die
    # Einstufung kommt mit der Anbindung, die Anforderung bleibt bis dahin stehen.
    "Klaviyo": "Pilot, noch nicht angebunden",
    # Keine Datenquelle, deshalb nicht in tiers.py.
    "Der Crawler in eurer Firewall": "keine Datenquelle",
}


def part_b() -> str:
    text = ACCESS.read_text(encoding="utf-8")
    return text[text.index("## Teil B"):text.index("## Die Mail, mit der Teil B rausgeht")]


def entries_by_heading(block: str) -> dict:
    result, current = {}, None
    for line in block.splitlines():
        heading = re.match(r"^## (Pflicht|Empfohlen|Optional)\s*$", line)
        if heading:
            current = heading.group(1)
            result[current] = []
        elif line.startswith("## "):
            current = None
        elif current and re.match(r"^\*\*(.+?)\*\*\s*$", line):
            result[current].append(line.strip("* ").strip())
    return result


class TestAccessPartB(unittest.TestCase):
    def test_customer_sources_stand_under_their_tier(self):
        found = entries_by_heading(part_b())
        for source in tiers.SOURCES:
            if source.provider in ("customer", "both"):
                self.assertIn(source.label, found.get(tiers.TIER_LABELS[source.tier], []),
                              source.key)

    def test_every_entry_is_tiered_or_explained(self):
        labels = {s.label for s in tiers.SOURCES}
        for heading, entries in entries_by_heading(part_b()).items():
            for entry in entries:
                self.assertTrue(entry in labels or entry in EXPLAINED, f"{heading}: {entry}")

    def test_no_request_for_sources_nothing_reads(self):
        for word in ("Judge.me", "Meta Business", "Was ihr sonst schon habt"):
            self.assertNotIn(word, part_b())

    def test_no_fixed_mail_address(self):
        self.assertNotRegex(part_b(), r"[\w.+-]+@[\w-]+\.[a-z]{2,}")


def mail() -> str:
    """Die Mail, mit der Teil B rausgeht, bis zum Ende der Datei."""
    text = ACCESS.read_text(encoding="utf-8")
    return text[text.index("## Die Mail, mit der Teil B rausgeht"):]


class TestOperatorName(unittest.TestCase):
    """Text und Mail tragen den Betreiber als Platzhalter (Spec 2026-09-11, B2).

    Bis zum 11.09.2026 war die Mail mit "Yves" unterschrieben. Ein fremder
    Betreiber, der die Vorlage kopiert, hätte das übersehen können.
    """

    def test_four_placeholders_are_named(self):
        intro = " ".join(part_b().split("# Zugänge für den Audit")[0].split())
        self.assertIn("vier Platzhalter", intro)
        self.assertIn("`<betreiber-name>`", intro)

    def test_the_list_names_exactly_the_placeholders_in_use(self):
        # Bis zum 11.09.2026 nannte die Liste `<datum>`, das nirgends vorkam.
        head, body = part_b().split("# Zugänge für den Audit", 1)
        self.assertEqual(set(re.findall(r"<([a-z-]+)>", head)),
                         set(re.findall(r"<([a-z-]+)>", body + mail())))

    def test_the_customer_text_is_signed_with_the_placeholder(self):
        self.assertTrue(part_b().rstrip().rstrip("-").rstrip().endswith("<betreiber-name>"))

    def test_the_mail_is_signed_with_the_placeholder(self):
        self.assertTrue(mail().rstrip().endswith("<betreiber-name>"))
        self.assertNotRegex(mail(), r"(?m)^Yves\s*$")


if __name__ == "__main__":
    unittest.main()
