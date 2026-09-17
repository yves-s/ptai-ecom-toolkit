"""Der gemeinsame Rahmen der fünf DataForSEO-Pulls: Geld, Ledger, Snapshot."""
import argparse
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import dfs_client
from audit import dfs_pull, ledger
from audit import env as operator_env


def envelope(cost=0.02, result=None):
    return {"status_code": 20000, "status_message": "Ok.", "cost": cost,
            "tasks": [{"status_code": 20000, "status_message": "Ok.", "cost": cost,
                        "data": {"tag": "beispielshop/2026-10-01/dfs_rankings"},
                        "result": result if result is not None else [{"row": 1}]}]}


class Recorder:
    """Ein Client-Ersatz, der jeden Aufruf merkt statt ihn zu senden."""

    def __init__(self, payload=None, error=None):
        self.calls = []
        self.payload = payload if payload is not None else envelope()
        self.error = error
        self.is_sandbox = False

    def post(self, path, tasks):
        self.calls.append((path, tasks))
        if self.error:
            raise self.error
        return self.payload


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.out = self.ws / "reporting" / "data" / "2026-10-01-audit"

    def execute(self, client, **kwargs):
        options = dict(
            workspace=self.ws, out=self.out, run_id="2026-10-01-audit",
            run_date=date(2026, 10, 1), account_slug="beispielshop",
            pull="dfs_rankings", endpoint="dataforseo_labs/google/ranked_keywords/live",
            task={"target": "beispielshop.example"},
            shape=lambda rows, meta: {"rows": rows}, cap=1.0, estimate=0.05)
        options.update(kwargs)
        return dfs_pull.execute(client, **options)

    def snapshot(self, name="dfs-rankings.json"):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def ledger_lines(self):
        path = ledger.ledger_path(self.ws)
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


class TestHappyPath(Base):
    def test_sends_the_task_with_the_tag(self):
        client = Recorder()
        self.execute(client)
        path, tasks = client.calls[0]
        self.assertEqual(path, "dataforseo_labs/google/ranked_keywords/live")
        self.assertEqual(tasks[0]["tag"], "beispielshop/2026-10-01/dfs_rankings")

    def test_the_task_fields_survive_the_tag(self):
        client = Recorder()
        self.execute(client)
        self.assertEqual(client.calls[0][1][0]["target"], "beispielshop.example")

    def test_writes_the_snapshot_to_the_run_folder(self):
        self.execute(Recorder())
        self.assertEqual(self.snapshot()["rows"], [{"row": 1}])

    def test_snapshot_carries_source_cost_and_time(self):
        self.execute(Recorder())
        snap = self.snapshot()
        self.assertEqual(snap["source"], "dfs_rankings")
        self.assertAlmostEqual(snap["cost_usd"], 0.02)
        self.assertIn("pulled_at", snap)

    def test_appends_exactly_one_ledger_line(self):
        self.execute(Recorder())
        lines = self.ledger_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["run_id"], "2026-10-01-audit")
        self.assertEqual(lines[0]["pull"], "dfs_rankings")
        self.assertEqual(lines[0]["endpoint"], "dataforseo_labs/google/ranked_keywords/live")

    def test_ledger_records_the_real_cost_not_the_estimate(self):
        self.execute(Recorder(envelope(cost=0.31)), estimate=0.05)
        self.assertAlmostEqual(self.ledger_lines()[0]["cost_usd"], 0.31)

    def test_ledger_notes_the_returned_tag(self):
        # Ob die Live-Endpunkte den Tag spiegeln, ist offen. Die Zeile hält
        # beides: den gesendeten und den zurückgekommenen.
        self.execute(Recorder())
        line = self.ledger_lines()[0]
        self.assertEqual(line["tag"], "beispielshop/2026-10-01/dfs_rankings")
        self.assertEqual(line["tag_returned"], "beispielshop/2026-10-01/dfs_rankings")


class TestBudget(Base):
    def test_refuses_before_calling_when_the_cap_is_reached(self):
        ledger.append(self.ws, {"run_id": "2026-10-01-audit", "cost_usd": 0.99})
        client = Recorder()
        with self.assertRaises(ledger.BudgetExceeded):
            self.execute(client, cap=1.0, estimate=0.05)
        self.assertEqual(client.calls, [], "kein Aufruf, wenn der Deckel steht")

    def test_writes_no_snapshot_when_refused(self):
        ledger.append(self.ws, {"run_id": "2026-10-01-audit", "cost_usd": 0.99})
        with self.assertRaises(ledger.BudgetExceeded):
            self.execute(Recorder(), cap=1.0, estimate=0.05)
        self.assertFalse((self.out / "dfs-rankings.json").exists())

    def test_estimate_falls_back_to_the_table(self):
        client = Recorder()
        self.execute(client, estimate=None, cap=99.0)
        self.assertEqual(len(client.calls), 1)


class TestFailure(Base):
    def test_api_error_is_passed_up(self):
        with self.assertRaises(dfs_client.DfsError):
            self.execute(Recorder(error=dfs_client.DfsError("HTTP 500")))

    def test_failed_call_writes_no_ledger_line(self):
        # Ein Aufruf, der nie eine Antwort brachte, hat keinen belegbaren
        # Betrag. Eine geschätzte Zeile im Ledger wäre eine erfundene Zahl.
        with self.assertRaises(dfs_client.DfsError):
            self.execute(Recorder(error=dfs_client.DfsError("HTTP 500")))
        self.assertFalse(ledger.ledger_path(self.ws).exists())


class TestSandbox(Base):
    def test_sandbox_run_is_marked_in_the_snapshot_and_the_ledger(self):
        # Ein Sandbox-Snapshot enthält Dummy-Werte. Ohne die Markierung läge
        # er ununterscheidbar neben echten Zahlen im Kundenordner.
        client = Recorder()
        client.is_sandbox = True
        self.execute(client)
        self.assertTrue(self.snapshot()["sandbox"])
        self.assertTrue(self.ledger_lines()[0]["sandbox"])

    def test_production_run_says_so_too(self):
        self.execute(Recorder())
        self.assertFalse(self.snapshot()["sandbox"])


class TestMerge(Base):
    def test_second_call_merges_instead_of_overwriting(self):
        self.execute(Recorder(), shape=lambda rows, meta: {"a": 1})
        self.execute(Recorder(), shape=lambda rows, meta: {"b": 2}, merge=True)
        snap = self.snapshot()
        self.assertEqual((snap["a"], snap["b"]), (1, 2))

    def test_merge_sums_the_cost_of_all_calls(self):
        # Der Snapshot nennt, was er gekostet hat. Bei zwei Aufrufen ist das
        # die Summe, nicht der letzte Betrag.
        self.execute(Recorder(envelope(cost=0.02)), shape=lambda r, m: {"a": 1})
        self.execute(Recorder(envelope(cost=0.03)), shape=lambda r, m: {"b": 2}, merge=True)
        self.assertAlmostEqual(self.snapshot()["cost_usd"], 0.05)

    def test_without_merge_the_second_call_replaces(self):
        self.execute(Recorder(), shape=lambda rows, meta: {"a": 1})
        self.execute(Recorder(), shape=lambda rows, meta: {"b": 2})
        self.assertNotIn("a", self.snapshot())


class TestBuildClient(unittest.TestCase):
    """`build_client` reicht args.workspace an dfs_client.credentials() weiter.

    Bis 11.09.2026 las dfs_client.credentials() nur die Umgebung; ein Zugang,
    der nur in der Workspace-.env stand, ließ den Client ohne Zugangsdaten
    entstehen. Client.__init__ ruft auth_header() auf, das ohne Login und
    Passwort einen ValueError wirft, noch bevor irgendein Netzaufruf passiert.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name) / "ws"
        self.ws.mkdir()
        central = Path(tmp.name) / "central.env"
        central.write_text("", encoding="utf-8")
        old = operator_env.CENTRAL
        operator_env.CENTRAL = central
        self.addCleanup(setattr, operator_env, "CENTRAL", old)
        for name in (dfs_client.ENV_LOGIN, dfs_client.ENV_PASSWORD):
            saved = os.environ.pop(name, None)
            if saved is not None:
                self.addCleanup(os.environ.__setitem__, name, saved)

    def test_workspace_env_reaches_the_client_without_a_valueerror(self):
        (self.ws / ".env").write_text(
            "PTAI_DFS_LOGIN=kunde@example.com\nPTAI_DFS_PASSWORD=geheim\n",
            encoding="utf-8")
        args = argparse.Namespace(workspace=self.ws, sandbox=False)
        client = dfs_pull.build_client(args)
        self.assertIsInstance(client, dfs_client.Client)


class TestFilename(unittest.TestCase):
    def test_pull_key_becomes_a_kebab_case_filename(self):
        self.assertEqual(dfs_pull.snapshot_name("dfs_rankings"), "dfs-rankings.json")
        self.assertEqual(dfs_pull.snapshot_name("backlinks"), "dfs-backlinks.json")

    def test_unknown_pull_raises(self):
        # Ein vertippter Pull-Name schriebe eine Datei, die keine Analyse
        # liest, und niemand bemerkte es.
        with self.assertRaises(ValueError):
            dfs_pull.snapshot_name("dfs_rankngs")

    def test_every_pull_has_an_estimate(self):
        self.assertEqual(set(dfs_pull.SNAPSHOT_NAMES), set(dfs_pull.ESTIMATE_USD))


class TestUnwrap(unittest.TestCase):
    def test_reads_the_single_result_block(self):
        # Die Labs-Endpunkte liefern result als Liste mit einem Block, die
        # Zeilen liegen darin unter items. Wer über result iteriert und dort
        # schon die Zeilen erwartet, schreibt null Zeilen in den Snapshot.
        rows = [{"total_count": 396, "items_count": 20, "items": [{"a": 1}]}]
        self.assertEqual(dfs_pull.unwrap(rows)["total_count"], 396)

    def test_empty_result_gives_an_empty_block(self):
        empty = dfs_pull.unwrap([])
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["total_count"], 0)

    def test_unexpected_shape_does_not_raise(self):
        self.assertEqual(dfs_pull.unwrap(["kaputt"])["items"], [])


class TestTruncate(unittest.TestCase):
    def test_marks_a_cut_list(self):
        listed, cut = dfs_pull.truncate([1, 2, 3], 2)
        self.assertEqual((listed, cut), ([1, 2], True))

    def test_short_list_is_not_marked(self):
        self.assertEqual(dfs_pull.truncate([1], 2), ([1], False))


if __name__ == "__main__":
    unittest.main()
