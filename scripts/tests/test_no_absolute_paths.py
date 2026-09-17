"""Keine Pfade eines einzelnen Rechners in Skills, Agents, Referenz und README.

Am 11.09.2026 standen drei davon im Plugin, und bei jedem anderen Nutzer brach
der Audit in Phase 2 ab (Spec 2026-09-11, Abschnitt 7.3). `${CLAUDE_PLUGIN_ROOT}`
wird laut Plugin-Referenz in Skill- und Agent-Inhalten gleichermaßen ersetzt.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MACHINE_PATH = re.compile(r"/(Users|home)/")


class TestNoAbsolutePaths(unittest.TestCase):
    def test_skills_and_agents_carry_no_machine_paths(self):
        files = (sorted(ROOT.glob("skills/**/SKILL.md")) + sorted(ROOT.glob("agents/*.md"))
                 + sorted(ROOT.glob("reference/*.md")) + [ROOT / "README.md"])
        self.assertTrue(files)
        hits = [f"{path.relative_to(ROOT)}:{number}"
                for path in files
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if MACHINE_PATH.search(line)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
