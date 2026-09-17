"""Das Plugin läuft ohne Yves' WorkOS (Spec 2026-09-11 public release, Teil A).

Drei Arten von Resten standen bis 11.09.2026 im Plugin: eine WorkOS-Skill, die
als Pflicht geladen wurde, obwohl ein fremder Betreiber sie nicht hat; ein Pfad
in den WorkOS-Ordner; und ein Verweis auf eine Datei aus dessen Wissensablage.
Jede davon lässt einen Lauf mittendrin ins Leere laufen, und keine fällt beim
Lesen der eigenen Änderung auf.

Geprüft wird nur, was zum Plugin gehört: im privaten Repo, was git kennt (eine
unversionierte Skill einer anderen Sitzung gehört nicht dazu), in der
öffentlichen Fassung ohne `.git` jede Datei (`tests/repo_files.py`).
"""
import fnmatch
import re
import unittest
from pathlib import Path

from audit import report_build
from tests import repo_files

ROOT = Path(__file__).resolve().parents[2]

#: Eine WorkOS-Skill im Text, etwa `workos:report`.
WORKOS_SKILL = re.compile(r"\bworkos:[a-z]")


def tracked(*patterns: str) -> list[tuple[str, str]]:
    """Name und Inhalt jeder Datei des Plugins, die auf eines der Muster passt."""
    return [(name, (ROOT / name).read_text(encoding="utf-8"))
            for name in repo_files.tracked(ROOT)
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)]


def skill_and_agent_texts() -> list[tuple[str, str]]:
    return tracked("skills/*/SKILL.md", "agents/*.md")


class TestWorkosSkillsAreOptional(unittest.TestCase):
    def test_every_paragraph_naming_a_workos_skill_makes_it_optional(self):
        hits = []
        for name, text in skill_and_agent_texts():
            for block in re.split(r"\n[ \t]*\n", text):
                if WORKOS_SKILL.search(block) and "installiert" not in block:
                    hits.append(f"{name}: {block.strip().splitlines()[0][:80]}")
        self.assertEqual(hits, [])

    def test_the_cover_hint_makes_the_pitch_gate_optional(self):
        hint = report_build.TEMPLATE_HINTS["cover_headline"]
        self.assertIn("workos:voice", hint)
        self.assertIn("installiert", hint)


class TestNoWorkosKnowledgeBase(unittest.TestCase):
    def test_no_skill_or_agent_sends_the_reader_to_a_workos_file(self):
        pattern = re.compile(r"00-kontext/|playbook-reports-schreiben|\bPlaybook\b")
        hits = [f"{name}:{number}" for name, text in skill_and_agent_texts()
                for number, line in enumerate(text.splitlines(), 1) if pattern.search(line)]
        self.assertEqual(hits, [])


class TestNoWorkosFolderInSkills(unittest.TestCase):
    #: Pfade und Namen, die nur in Yves' WorkOS-Ordner einen Sinn ergeben.
    PATTERN = re.compile(r"02-accounts|WORKOS|WorkOS|pathtoai-drive|CloudStorage|06-wissen/")

    def test_skills_and_agents_name_no_workos_folder(self):
        hits = [f"{name}:{number}" for name, text in skill_and_agent_texts()
                for number, line in enumerate(text.splitlines(), 1)
                if self.PATTERN.search(line)]
        self.assertEqual(hits, [])


class TestNoWorkosPathInThePlugin(unittest.TestCase):
    """Kein Pfad in Yves' WorkOS-Ordner, in keiner getrackten Datei außerhalb von docs/."""

    #: Muster einer Abhängigkeit, nicht einer Erwähnung: die alte Konstante und
    #: ihr Platzhalter, der Ordner der Kunden, der Alias und der Mount. Das Wort
    #: "WorkOS" in einem Kommentar ist keine Abhängigkeit und bleibt erlaubt.
    PATTERN = re.compile(r"02-accounts|WORKOS|pathtoai-drive|CloudStorage")

    #: Diese Datei nennt die Muster selbst. `test_audit_light_skill.py` und
    #: `test_check_env.py` sind dabei, weil beide die Abwesenheit dieser
    #: Zeichenketten prüfen: ihre eigenen `assertNotIn`-Zeilen tragen die Muster
    #: als Text. `test_no_customer_data.py` stand bis Teil C hier, weil es die
    #: Kundennamen aus dem Drive las; seit Teil C liest es über
    #: `release/customer_terms.py` und geht mit in die öffentliche Fassung.
    EXEMPT = {"scripts/tests/test_no_workos.py",
              "scripts/tests/test_audit_light_skill.py", "scripts/tests/test_check_env.py"}

    SUFFIXES = (".py", ".md", ".sh", ".json", ".html", ".css", ".mjs", ".txt")

    def test_the_pattern_catches_what_stood_there(self):
        for sample in ('WORKOS_ROOT = os.environ.get("WORKOS_ROOT")',
                       "<WORKOS>/02-accounts/<slug>/audit-runs", "~/.claude/pathtoai-drive"):
            with self.subTest(sample=sample):
                self.assertTrue(self.PATTERN.search(sample))

    def test_no_tracked_file_points_into_workos(self):
        hits = []
        for name in repo_files.tracked(ROOT):
            if name.startswith("docs/") or name in self.EXEMPT or not name.endswith(self.SUFFIXES):
                continue
            try:
                text = (ROOT / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            hits += [f"{name}:{number}" for number, line in enumerate(text.splitlines(), 1)
                     if self.PATTERN.search(line)]
        self.assertEqual(hits, [])
