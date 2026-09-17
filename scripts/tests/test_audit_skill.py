"""Die Audit-Skill gegen das prüfen, was die Scripts wirklich anbieten.

Die Skill ist Prosa, und eine Sitzung folgt ihr wörtlich. Ein Pfad, den es
nicht gibt, ein Modul, das anders heißt, oder eine Methode am falschen Objekt
fallen deshalb erst mitten im Lauf auf, nach einer halben Stunde Pulls. Am
07.09.2026 stand in achtzehn Zeilen `state.set_source(...)`, obwohl das eine
Methode am geladenen Zustand ist und nicht am Modul.
"""
import importlib
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

MODULE = ("baseline", "state", "measures", "gates", "run", "window", "score",
          "report_build", "report_web", "charts", "config", "readability")


def skill() -> str:
    return (ROOT / "skills" / "audit" / "SKILL.md").read_text(encoding="utf-8")


class TestSkillGegenScripts(unittest.TestCase):
    def test_jeder_genannte_pfad_existiert(self):
        for rel in sorted(set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)",
                                         skill()))):
            with self.subTest(pfad=rel):
                self.assertTrue((ROOT / rel).exists(),
                                f"{rel} steht in der Skill, existiert aber nicht")

    def test_jedes_aufgerufene_modul_existiert(self):
        for name in sorted(set(re.findall(r"python3 -m (audit\.\w+)", skill()))):
            with self.subTest(modul=name):
                self.assertTrue(
                    (ROOT / "scripts" / f"{name.replace('.', '/')}.py").exists())

    def test_jede_modulfunktion_gibt_es_wirklich(self):
        """Ein `baseline.render()` in der Prosa, das im Modul fehlt, bricht
        den Lauf erst in Phase 4."""
        for mod, fn in sorted(set(re.findall(
                r"\b(" + "|".join(MODULE) + r")\.(\w+)\(", skill()))):
            with self.subTest(aufruf=f"{mod}.{fn}"):
                m = importlib.import_module(f"audit.{mod}")
                self.assertTrue(hasattr(m, fn),
                                f"{mod}.{fn}() steht in der Skill, im Modul "
                                "gibt es das nicht")

    def test_state_methods_are_called_on_the_loaded_object(self):
        """`state` ist das Modul, `run_state` das geladene Objekt.

        Gesucht wird `state.` mit Wortgrenze davor: `run_state.save()` ist
        richtig und enthält `state.save` als Teilzeichenkette. Bis Teil C prüfte
        der Test ohne Wortgrenze und hätte die Umbenennung verhindert.
        """
        from audit import state
        text = skill()
        for name in ("set_source", "set_phase", "save", "source_open"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(state.State, name))
                self.assertFalse(hasattr(state, name))
                self.assertIsNone(re.search(rf"(?<![\w.])state\.{name}\(", text))
                self.assertIn(f"run_state.{name}(", text)

    def test_die_pflichtfelder_der_textvorlage_stehen_in_der_skill(self):
        """Ein Feld, das das Script verlangt und die Skill nicht nennt, hält
        den Lauf in Phase 4 an, ohne dass jemand weiß warum."""
        from audit import report_build as rb
        text = skill()
        for feld in rb.TEXT_FIELDS + (rb.PROBLEM_FIELD, rb.KEY_MESSAGE):
            with self.subTest(feld=feld):
                self.assertIn(feld, text)

    def test_jede_sektion_mit_score_hat_einen_bereich(self):
        from audit import report_build as rb, score
        zugeordnet = {k for b in score.AREAS.values() for k in b["sektionen"]}
        ohne = set(rb.SECTION_TITLES) - zugeordnet - {"shop"}
        self.assertEqual(ohne, set(),
                         f"Diese Abschnitte speisen keinen Score: {ohne}")

    def test_die_agents_kennen_dieselben_disziplinen_wie_das_backlog(self):
        """Ein Agent, der eine unbekannte Disziplin schreibt, lässt
        measures.create() werfen, und der Befund fällt still aus."""
        from audit import measures
        erlaubt = set(measures.LABELS["discipline"])
        for filename in sorted((ROOT / "agents").glob("audit-*.md")):
            text = filename.read_text(encoding="utf-8")
            m = re.search(r'"discipline":\s*"(\w+)"', text)
            if not m:
                continue
            with self.subTest(agent=filename.stem):
                self.assertIn(m.group(1), erlaubt)


if __name__ == "__main__":
    unittest.main()
