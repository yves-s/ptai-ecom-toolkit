"""Die Agent-Definitionen gegen das prüfen, was die Audit-Skill über sie sagt.

Am 06.09.2026 fiel auf, dass zwei der drei rechnenden Subagents das
`model: sonnet` nicht trugen, das die Skill ihnen ausdrücklich zuschreibt. Die
Modellwahl lief damit still anders als dokumentiert, und kein Test hat es
bemerkt: Frontmatter wurde bis dahin nirgends geprüft.

Am 07.09.2026 sind sechs Subagents dazugekommen, und mit ihnen die zweite
Fehlerklasse, die dieser Test seitdem abdeckt: ein Subagent, der eine
Eingabedatei unter einem Namen nennt, den kein Pull schreibt. Ein `Read` darauf
schlägt fehl, der Subagent meldet die Frage als blockiert, und im Report steht
eine Lücke, die es in Wahrheit nicht gibt. Der Tippfehler wäre in keiner
Ausgabe zu sehen.
"""
import re
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "agents"

#: Was die Audit-Skill in Phase 2 über jeden Subagenten behauptet.
#: `audit-data-quality` trägt bewusst kein Modell und erbt damit das
#: Session-Modell, weil er über die Gültigkeit der anderen entscheidet.
EXPECTED_MODEL = {
    "audit-commerce": "sonnet",
    "audit-competition": "sonnet",
    "audit-content-brand": "sonnet",
    "audit-conversion": "sonnet",
    "audit-geo": "sonnet",
    "audit-sea": "sonnet",
    "audit-seo-content": "sonnet",
    "audit-seo-technical": "sonnet",
    "audit-traffic": "sonnet",
    "audit-trust": "sonnet",
    "audit-data-quality": None,
}

#: Jeder Subagent liest grosse JSON-Snapshots und braucht dafür `jq`.
EXPECTED_TOOL = "Bash"

#: Die Snapshots, die Phase 1 tatsächlich nach `reporting/data/<run-id>/`
#: schreibt. Der Dateiname ist der Vertrag zwischen Pull und Analyse.
#: `reviews.json` steht hier bewusst mit: `pull-reviews` kommt erst in Stufe 3,
#: aber `audit-content-brand` nennt die Datei schon als bekannte Lücke.
DATA_SNAPSHOTS = {
    "ads.json", "catalog.json", "crawl.json", "cwv.json",
    "dfs-backlinks.json", "dfs-competitors.json", "dfs-keywords.json",
    "dfs-rankings.json", "dfs-shopping.json", "ga4.json", "geo.json",
    "gsc.json", "reviews.json", "shop-tech.json", "shopify.json",
}

#: Was unter `reporting/runs/<run-id>/` direkt liegt. Der Index der
#: Screenshots liegt dort und nicht in `data/`, weil die Bilder selbst im
#: Kundenordner liegen.
RUN_ARTIFACTS = {"screens.json"}

REFERENCE = re.compile(r"reporting/(data|runs)/<run-id>/([a-z0-9-]+\.json)")


def frontmatter(name: str) -> dict:
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError(f"{name}: kein Frontmatter")
    block = text.split("---", 2)[1]
    result = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


class TestAgentFrontmatter(unittest.TestCase):
    def test_the_model_matches_what_the_skill_claims(self):
        for name, expected in EXPECTED_MODEL.items():
            with self.subTest(agent=name):
                self.assertEqual(frontmatter(name).get("model"), expected)

    def test_every_analysis_agent_can_run_jq(self):
        for name in EXPECTED_MODEL:
            with self.subTest(agent=name):
                tools = frontmatter(name).get("tools", "")
                self.assertIn(EXPECTED_TOOL, tools,
                              f"{name} liest grosse Snapshots ohne {EXPECTED_TOOL}")

    def test_every_agent_declares_blocked_questions(self):
        for name in EXPECTED_MODEL:
            with self.subTest(agent=name):
                text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
                self.assertIn("blocked_questions", text)

    def test_every_agent_file_is_registered_here(self):
        """Ein neuer Agent, den niemand einträgt, wird von keinem Test geprüft."""
        on_disk = {path.stem for path in AGENTS.glob("*.md")}
        self.assertEqual(on_disk, set(EXPECTED_MODEL))

    def test_every_named_input_file_is_one_a_pull_writes(self):
        for name in EXPECTED_MODEL:
            text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
            for folder, filename in REFERENCE.findall(text):
                with self.subTest(agent=name, file=f"{folder}/{filename}"):
                    allowed = DATA_SNAPSHOTS if folder == "data" else RUN_ARTIFACTS
                    self.assertIn(filename, allowed,
                                  f"{name} nennt {filename} unter {folder}/, "
                                  "dort schreibt kein Pull diese Datei")


SKILLS = AGENTS.parent / "skills"
SKILL_LINE = re.compile(r"^Skill:\s*(\S+)\s*$", re.M)


class TestAgentSkills(unittest.TestCase):
    """Die Fachsprache kommt aus dem Plugin (Spec 2026-09-11 public release, A3, D5)."""

    def test_every_analysis_agent_loads_the_plugin_vocabulary(self):
        for name in EXPECTED_MODEL:
            with self.subTest(agent=name):
                text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
                self.assertIn("ptai-ecom:ecom-language", SKILL_LINE.findall(text))
                self.assertNotIn("workos:ecom-language", text)

    def test_every_plugin_skill_an_agent_names_exists(self):
        for path in sorted(AGENTS.glob("*.md")):
            for ref in SKILL_LINE.findall(path.read_text(encoding="utf-8")):
                if ref.startswith("ptai-ecom:"):
                    with self.subTest(agent=path.stem, skill=ref):
                        self.assertTrue((SKILLS / ref.split(":", 1)[1] / "SKILL.md").is_file())

    def test_the_plugin_copy_carries_no_anecdote(self):
        text = (SKILLS / "ecom-language" / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text.split("---", 2)[1], r"(?m)^name:\s*ecom-language\s*$")
        self.assertNotIn("Yves", text)
        self.assertNotIn("Der Fall, aus dem diese Skill entstanden ist", text)
        self.assertNotIn("ptai-ecom/reference", text)
        for dash in (chr(0x2013), chr(0x2014)):
            self.assertNotIn(dash, text)

    def test_qa_points_to_the_plugin_vocabulary(self):
        qa = (AGENTS.parent / "scripts" / "audit" / "qa.py").read_text(encoding="utf-8")
        self.assertNotIn("workos:ecom-language", qa)
        self.assertIn("ptai-ecom:ecom-language", qa)


if __name__ == "__main__":
    unittest.main()
