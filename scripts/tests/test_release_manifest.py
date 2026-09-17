"""README, Manifeste und Lizenz der öffentlichen Fassung (Spec 2026-09-11 public release, C4, D8)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from audit import tiers  # noqa: E402
from tests import repo_files  # noqa: E402

#: Das öffentliche Repo. Wählt Yves im Halt einen anderen Namen, ändert er sich
#: hier, in der README und in plugin.json.
PUBLIC_REPO = "yves-s/ptai-ecom-toolkit"

#: Skills, die im Plugin liegen, in der README aber bewusst nicht stehen.
#: `audit-light-send` ist der Anfrage-Ablauf von Path to AI und braucht
#: fremde Konten bei Supabase und Resend. Yves am 15.09.2026: auffindbar,
#: aber nicht beworben.
UNLISTED_SKILLS = {"audit-light-send"}


def load(name):
    return json.loads((ROOT / ".claude-plugin" / name).read_text(encoding="utf-8"))


class TestManifests(unittest.TestCase):
    def test_versions_agree_and_look_like_semver(self):
        plugin, market = load("plugin.json"), load("marketplace.json")
        self.assertRegex(plugin["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(plugin["version"], market["metadata"]["version"])

    def test_the_marketplace_entry_carries_no_version(self):
        """Steht sie im Eintrag und in plugin.json, gewinnt plugin.json ohne Warnung."""
        for entry in load("marketplace.json")["plugins"]:
            self.assertNotIn("version", entry)

    def test_descriptions_name_audit_audit_light_and_report(self):
        market = load("marketplace.json")
        for description in (load("plugin.json")["description"], market["metadata"]["description"],
                            market["plugins"][0]["description"]):
            for word in ("Audit", "audit-light", "Report"):
                with self.subTest(word=word):
                    self.assertIn(word, description)

    def test_links_point_to_the_public_repo(self):
        plugin = load("plugin.json")
        for field in ("homepage", "repository"):
            self.assertEqual(plugin[field], f"https://github.com/{PUBLIC_REPO}")
        self.assertEqual(plugin["license"], "MIT")


class TestLicense(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    def test_mit_and_the_exceptions(self):
        self.assertTrue(self.text.startswith("MIT License"))
        for word in ("Exceptions", '"Path to AI"', "assets/brand/logo.svg", "assets/brand/logo-reversed.svg",
                     "SIL Open Font License 1.1"):
            with self.subTest(word=word):
                self.assertIn(word, self.text)

    def test_no_portrait_exception(self):
        # Das Porträt hat das Plugin am 15.09.2026 verlassen, die Ausnahme mit ihm.
        self.assertNotIn("portrait", self.text.lower())

    def test_every_path_in_the_license_exists(self):
        for path in re.findall(r"assets/brand/[\w./-]*[\w/]", self.text):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).exists(), path)


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_install_lines(self):
        marketplace = load("marketplace.json")["name"]
        self.assertIn(f"/plugin marketplace add {PUBLIC_REPO}", self.text)
        self.assertIn(f"/plugin install ptai-ecom@{marketplace}", self.text)

    def test_sections(self):
        for heading in ("## Was drin ist", "## Voraussetzungen", "## Installation",
                        "## Setup in zwei Teilen", "## Einstufung der Quellen",
                        "## Was nicht passiert", "## Eigene Marke", "## Lizenz"):
            with self.subTest(heading=heading):
                self.assertIn(f"\n{heading}\n", self.text)

    def test_every_skill_and_agent_is_listed(self):
        names = repo_files.tracked(ROOT)
        skills = sorted({n.split("/")[1] for n in names if re.fullmatch(r"skills/[^/]+/SKILL\.md", n)})
        agents = sorted({Path(n).stem for n in names if re.fullmatch(r"agents/[^/]+\.md", n)})
        self.assertTrue(skills and agents)
        for skill in skills:
            if skill in UNLISTED_SKILLS:
                continue
            with self.subTest(skill=skill):
                self.assertIn(f"`ptai-ecom:{skill}`", self.text)
        for agent in agents:
            with self.subTest(agent=agent):
                self.assertIn(f"`{agent}`", self.text)

    def test_unlisted_skills_exist_and_stay_out_of_the_readme(self):
        # Die Ausnahme darf nicht veralten: die Skill muss es geben, und die
        # README nennt sie an keiner Stelle.
        names = set(repo_files.tracked(ROOT))
        for skill in sorted(UNLISTED_SKILLS):
            with self.subTest(skill=skill):
                self.assertIn(f"skills/{skill}/SKILL.md", names)
                self.assertNotIn(skill, self.text)

    def test_the_tier_table_follows_tiers_py(self):
        for source in tiers.SOURCES:
            with self.subTest(source=source.key):
                self.assertIn(f"| {tiers.TIER_LABELS[source.tier]} | {source.label} | {source.without} |",
                              self.text)

    def test_nothing_that_only_exists_here(self):
        for word in ("docs/", "ln -s", "/Users/", "WorkOS", "CLAUDE.md"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.text)
