"""Bezeichner im Code der Skills und Agents sind englisch (CLAUDE.md, Sprache).

Eine Sitzung übernimmt den Code aus einer Skill wörtlich. Bis Teil C stand in
`skills/audit/SKILL.md` das geladene Zustandsobjekt als `zustand` und die Quelle
als `quelle`, in jedem Aufruf, den der Audit-Lauf abschreibt.

Geprüft werden Codeblöcke mit Sprache (python, bash, sh, shell, zsh) und
Inline-Code in Backticks, und dort nur Stellen, die eindeutig Bezeichner sind:
Zuweisung, Methodenaufruf, Schleifenvariable, Index, erstes Argument. Deutsche
Wörter in Zeichenketten und Platzhalter wie `<run-id>` bleiben außen vor.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from tests import repo_files  # noqa: E402

#: Deutsche Wortteile, die als Bezeichner vorkamen oder naheliegen. Ein Bezeichner
#: zählt, wenn einer seiner Teile zwischen Unterstrichen darin steht.
GERMAN = {"zustand", "quelle", "quell", "quellen", "eintrag", "herkunft", "schluessel",
          "lauf", "laeufe", "befund", "befunde", "massnahme", "massnahmen", "datei",
          "pfad", "ordner", "zeitraum", "ergebnis", "kunde", "marke", "zeile", "wert",
          "treffer", "muster", "seite", "seiten", "fehlt", "kaputt", "hinweis", "des",
          "retourenquote"}

#: Drei Backticks, zusammengesetzt, damit diese Datei in Markdown zitierbar bleibt.
TICKS = "`" * 3
FENCE = re.compile("^" + TICKS + r"(\w*)[^\n]*\n(.*?)^" + TICKS, re.M | re.S)
CODE_LANGUAGES = {"python", "py", "bash", "sh", "shell", "zsh"}
INLINE = re.compile(r"`([^`\n]+)`")
USES = (
    re.compile(r"\b([A-Za-z_]\w*)\s*=(?!=)"),
    re.compile(r"\b([A-Za-z_]\w*)\.\w+\s*\("),
    re.compile(r"\bfor\s+([A-Za-z_]\w*)(?:\s*,\s*([A-Za-z_]\w*))?\s+in\b"),
    re.compile(r"\bin\s+([A-Za-z_]\w*)\s*:"),
    re.compile(r"\[\s*([A-Za-z_]\w*)\s*\]"),
    re.compile(r"\w\(\s*([A-Za-z_]\w*)\s*[,)]"),
    re.compile(r'\(\s*"([a-z_]+)"\s*,\s*"([a-z_]+)"\s*\)'),
)


def identifiers(code: str) -> set[str]:
    found = set()
    for pattern in USES:
        for match in pattern.finditer(code):
            found.update(group for group in match.groups() if group)
    return found


def german(identifier: str) -> bool:
    return any(part in GERMAN for part in identifier.lower().split("_"))


def code_of(text: str) -> list[str]:
    blocks = [body for lang, body in FENCE.findall(text) if lang.lower() in CODE_LANGUAGES]
    return blocks + INLINE.findall(FENCE.sub("", text))


class TestSkillCodeIsEnglish(unittest.TestCase):
    def test_the_check_catches_what_stood_there(self):
        sample = ("zustand = state.load('.', run_id)\nfor quelle in quell_schluessel_des_blocks:\n"
                  "    eintrag = zustand.sources[quelle]\n"
                  'known_gaps=("repeat_rate", "retourenquote")\n')
        self.assertEqual({i for i in identifiers(sample) if german(i)},
                         {"zustand", "quelle", "quell_schluessel_des_blocks", "eintrag", "retourenquote"})
        self.assertFalse(any(german(i) for i in identifiers('status = "Datei fehlt"')))

    def test_skills_and_agents_use_english_identifiers(self):
        hits = []
        for name in repo_files.tracked(ROOT):
            if not (re.fullmatch(r"skills/[^/]+/SKILL\.md", name) or re.fullmatch(r"agents/[^/]+\.md", name)):
                continue
            for code in code_of((ROOT / name).read_text(encoding="utf-8")):
                hits += [f"{name}: {identifier}" for identifier in sorted(identifiers(code)) if german(identifier)]
        self.assertEqual(sorted(set(hits)), [])


if __name__ == "__main__":
    unittest.main()
