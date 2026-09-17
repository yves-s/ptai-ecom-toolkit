"""Eine Fassung beiseitelegen, bevor eine neue Analyse darüber schreibt."""
import json
import tempfile
import unittest
from pathlib import Path

from audit import revision


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        self.run = self.ws / "reporting" / "runs" / self.run_id
        (self.run / "findings").mkdir(parents=True)
        (self.ws / "reporting" / "measures.json").write_text(
            json.dumps({"next_id": 2, "measures": []}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _fassung(self):
        (self.run / "findings").mkdir(exist_ok=True)
        (self.run / "findings" / "cro.json").write_text('{"findings": []}',
                                                        encoding="utf-8")
        (self.run / "audit.pdf").write_bytes(b"%PDF")
        (self.run / "report-text.json").write_text('{"cover": "x"}',
                                                   encoding="utf-8")

    def test_the_first_archive_is_number_one(self):
        self._fassung()
        ziel = revision.archive(self.ws, self.run_id)
        self.assertEqual(ziel.name, "01")

    def test_findings_and_report_move_away(self):
        self._fassung()
        revision.archive(self.ws, self.run_id)
        self.assertFalse((self.run / "findings").exists())
        self.assertFalse((self.run / "audit.pdf").exists())

    def test_the_archive_holds_them(self):
        self._fassung()
        ziel = revision.archive(self.ws, self.run_id)
        self.assertTrue((ziel / "findings" / "cro.json").exists())
        self.assertTrue((ziel / "audit.pdf").exists())

    def test_the_written_text_stays_put(self):
        # Cover-Headline und Kernaussagen hat ein Mensch geschrieben. Sie
        # gelten dem Lauf, nicht der Fassung, und wer sie mitnimmt, lässt sie
        # ein zweites Mal schreiben.
        self._fassung()
        revision.archive(self.ws, self.run_id)
        self.assertTrue((self.run / "report-text.json").exists())

    def test_the_backlog_is_copied_not_moved(self):
        self._fassung()
        ziel = revision.archive(self.ws, self.run_id)
        self.assertTrue((ziel / "measures.json").exists())
        self.assertTrue((self.ws / "reporting" / "measures.json").exists())

    def test_a_second_archive_counts_up(self):
        self._fassung()
        revision.archive(self.ws, self.run_id)
        self._fassung()
        self.assertEqual(revision.archive(self.ws, self.run_id).name, "02")

    def test_nothing_to_archive_returns_none(self):
        self.assertIsNone(revision.archive(self.ws, self.run_id))

    def test_nothing_to_archive_creates_no_folder(self):
        revision.archive(self.ws, self.run_id)
        self.assertFalse(revision.revisions_dir(self.ws, self.run_id).exists())


class TestResetMeasures(unittest.TestCase):
    def _measure(self, ident, status="open", history=1):
        return {"id": ident, "status": status,
                "history": [{"status": "open"}] * history}

    def test_an_untouched_measure_is_removed(self):
        neu, entfernt, behalten = revision.reset_measures(
            {"next_id": 2, "measures": [self._measure("M-01")]})
        self.assertEqual((entfernt, behalten), (1, 0))
        self.assertEqual(neu["measures"], [])

    def test_a_measure_with_a_status_stays(self):
        neu, entfernt, behalten = revision.reset_measures(
            {"next_id": 2, "measures": [self._measure("M-01", "in_progress")]})
        self.assertEqual((entfernt, behalten), (0, 1))

    def test_a_measure_with_history_stays(self):
        neu, entfernt, behalten = revision.reset_measures(
            {"next_id": 2, "measures": [self._measure("M-01", history=2)]})
        self.assertEqual((entfernt, behalten), (0, 1))

    def test_next_id_continues_behind_what_stays(self):
        # Sonst bekäme eine neue Maßnahme die Kennung einer behaltenen.
        backlog = {"next_id": 4, "measures": [
            self._measure("M-01", "implemented"),
            self._measure("M-02"),
            self._measure("M-03", "rejected"),
        ]}
        neu, entfernt, behalten = revision.reset_measures(backlog)
        self.assertEqual((entfernt, behalten), (1, 2))
        self.assertEqual(neu["next_id"], 3)

    def test_an_empty_backlog_survives(self):
        neu, entfernt, behalten = revision.reset_measures({"measures": []})
        self.assertEqual(neu, {"next_id": 1, "measures": []})


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.run_id = "2026-10-01-audit"
        run = self.ws / "reporting" / "runs" / self.run_id
        (run / "findings").mkdir(parents=True)
        (run / "findings" / "cro.json").write_text("{}", encoding="utf-8")
        (self.ws / "reporting" / "measures.json").write_text(json.dumps(
            {"next_id": 3, "measures": [
                {"id": "M-01", "status": "open", "history": [{"status": "open"}]},
                {"id": "M-02", "status": "implemented",
                 "history": [{"status": "open"}, {"status": "implemented"}]},
            ]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _backlog(self):
        return json.loads((self.ws / "reporting" / "measures.json")
                          .read_text(encoding="utf-8"))

    def test_the_cli_archives_and_resets(self):
        code = revision.main(["--workspace", str(self.ws), "--run-id", self.run_id])
        self.assertEqual(code, 0)
        self.assertEqual([m["id"] for m in self._backlog()["measures"]], ["M-02"])

    def test_keep_measures_leaves_the_backlog_alone(self):
        revision.main(["--workspace", str(self.ws), "--run-id", self.run_id,
                       "--keep-measures"])
        self.assertEqual(len(self._backlog()["measures"]), 2)


if __name__ == "__main__":
    unittest.main()
