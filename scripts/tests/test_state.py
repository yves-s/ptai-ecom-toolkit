"""Phasenstand, Wiederaufnahme, Quellenstatus."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit import run, state


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_run_has_all_phases_open(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        self.assertEqual(s.phases["1-raw-data"], "open")
        self.assertEqual(s.run_id, "2026-10-01-audit")

    def test_save_and_load_yield_same_state(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_phase("1-raw-data", "done")
        s.save()
        reloaded = state.load(self.ws, "2026-10-01-audit")
        self.assertEqual(reloaded.phases["1-raw-data"], "done")

    def test_resume_names_the_next_open_phase(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_phase("0-setup", "done")
        s.set_phase("1-raw-data", "done")
        self.assertEqual(s.next_phase(), "2-analyses")

    def test_all_phases_done_returns_none(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        for p in state.PHASES:
            s.set_phase(p, "done")
        self.assertIsNone(s.next_phase())

    def test_failed_phase_is_the_next_one(self):
        # Ein Fehler hält den Lauf an dieser Phase, er springt nicht weiter.
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_phase("0-setup", "done")
        s.set_phase("1-raw-data", "failed")
        self.assertEqual(s.next_phase(), "1-raw-data")

    def test_done_source_is_not_pulled_again(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_source("dfs_rankings", "done", file="data/2026-10-01-audit/dfs-rankings.json")
        self.assertFalse(s.source_open("dfs_rankings"))

    def test_failed_source_is_open_again(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_source("ads", "failed", reason="kein Entwicklertoken")
        self.assertTrue(s.source_open("ads"))
        self.assertEqual(s.sources["ads"]["reason"], "kein Entwicklertoken")

    def test_unknown_phase_raises(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        with self.assertRaises(ValueError):
            s.set_phase("9-zauberei", "done")

    def test_unknown_source_counts_as_open(self):
        # Sicherheitsrichtung: was nie registriert wurde, wird gezogen.
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        self.assertTrue(s.source_open("nie_gesehen"))

    def test_unknown_phase_status_raises(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        with self.assertRaises(ValueError):
            s.set_phase("1-raw-data", "halbfertig")

    def test_unknown_source_status_raises(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        with self.assertRaises(ValueError):
            s.set_source("ga4", "halbfertig")

    def test_source_entry_survives_disk(self):
        # Genau dieses Feld liest ein Folgelauf, um die Fälligkeit zu rechnen.
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_source("gsc", "done", file="data/x/gsc.json", today=date(2026, 10, 1))
        s.save()
        reloaded = state.load(self.ws, "2026-10-01-audit").sources["gsc"]
        self.assertEqual(reloaded["pulled_at"], "2026-10-01")
        self.assertEqual(reloaded["file"], "data/x/gsc.json")

    def test_without_today_the_current_day_applies(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.set_source("ga4", "done")
        self.assertEqual(s.sources["ga4"]["pulled_at"], date.today().isoformat())

    def test_cadence_and_period_are_readable(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        self.assertEqual(s.cadence, "audit")
        self.assertIsNone(s.period)

    def test_save_leaves_no_temporary_file(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.save()
        self.assertEqual(list(s.path.parent.glob("*.tmp")), [])

    def test_corrupt_file_does_not_silently_start_a_new_run(self):
        # Ein halb geschriebener Stand darf keinen zweiten Lauf auslösen:
        # jede bereits bezahlte Abfrage würde noch einmal anfallen.
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.save()
        s.path.write_text('{"run_id": "2026-10-0')
        with self.assertRaises(ValueError):
            state.load_or_new(self.ws, "2026-10-01-audit", "audit")

    def test_file_lives_in_the_run_folder(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        s.save()
        path = self.ws / "reporting" / "runs" / "2026-10-01-audit" / "state.json"
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text())["run_id"], "2026-10-01-audit")


class TestPeriod(unittest.TestCase):
    """Die Form, in der `run.period()` und `state.json` denselben Zeitraum meinen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_block_from_run_period_survives_disk(self):
        # Bewusst gegen run.period() statt gegen einen getippten Block: die
        # beiden Module müssen dieselbe Form meinen, sonst fällt es erst im
        # ersten echten Report-Lauf auf.
        block = run.period("month", date(2026, 10, 5))
        s = state.new(self.ws, "2026-10-01-month", cadence="month", period=block)
        s.save()
        self.assertEqual(state.load(self.ws, "2026-10-01-month").period, block)

    def test_no_period_stays_none(self):
        s = state.new(self.ws, "2026-10-01-audit", cadence="audit",
                      period=run.period("audit", date(2026, 10, 1)))
        s.save()
        self.assertIsNone(state.load(self.ws, "2026-10-01-audit").period)

    def test_tuple_of_dates_is_refused_at_the_boundary(self):
        # Die alte Form. Sie überlebt json.dumps nicht, und ein Abbruch erst
        # in save() käme nach allen bezahlten Pulls.
        with self.assertRaises(ValueError):
            state.new(self.ws, "2026-10-01-month", cadence="month",
                      period=(date(2026, 9, 1), date(2026, 9, 30)))


if __name__ == "__main__":
    unittest.main()


class TestReopen(unittest.TestCase):
    """Analysen wiederholen, ohne die Rohdaten noch einmal zu ziehen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.s = state.new(self.ws, "2026-10-01-audit", cadence="audit")
        for phase in state.PHASES:
            self.s.set_phase(phase, "done")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reopening_returns_the_affected_phases(self):
        betroffen = self.s.reopen_from("2-analyses")
        self.assertEqual(betroffen,
                         ["2-analyses", "3-synthesis", "4-deliverables"])

    def test_earlier_phases_stay_done(self):
        self.s.reopen_from("2-analyses")
        self.assertEqual(self.s.phases["0-setup"], "done")
        self.assertEqual(self.s.phases["1-raw-data"], "done")

    def test_the_run_resumes_at_the_reopened_phase(self):
        self.s.reopen_from("2-analyses")
        self.assertEqual(self.s.next_phase(), "2-analyses")

    def test_sources_are_untouched(self):
        # Der ganze Sinn: eine bezahlte Quelle wird nicht ein zweites Mal
        # gezogen, nur weil die Auswertung darüber neu läuft.
        self.s.set_source("dfs_rankings", "done", file="x.json")
        self.s.reopen_from("2-analyses")
        self.assertFalse(self.s.source_open("dfs_rankings"))

    def test_an_unknown_phase_raises(self):
        with self.assertRaises(ValueError):
            self.s.reopen_from("7-nonsense")

    def test_reopening_survives_disk(self):
        self.s.reopen_from("3-synthesis")
        self.s.save()
        wieder = state.load(self.ws, "2026-10-01-audit")
        self.assertEqual(wieder.next_phase(), "3-synthesis")
        self.assertEqual(wieder.phases["2-analyses"], "done")
