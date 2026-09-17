"""Kostenzuordnung und Budgetdeckel für DataForSEO. Kein Test ruft eine API."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit import ledger


class TestTag(unittest.TestCase):
    def test_builds_tag_from_account_date_and_pull(self):
        self.assertEqual(
            ledger.build_tag("beispielshop", date(2026, 10, 1), "dfs_rankings"),
            "beispielshop/2026-10-01/dfs_rankings",
        )

    def test_empty_part_raises(self):
        # Ein leerer Teil macht den Tag mehrdeutig: "beispielshop//rankings"
        # ist in der Abrechnung von einem Tag mit Datum nicht mehr zu trennen.
        with self.assertRaises(ValueError):
            ledger.build_tag("", date(2026, 10, 1), "dfs_rankings")

    def test_whitespace_only_part_raises(self):
        with self.assertRaises(ValueError):
            ledger.build_tag("   ", date(2026, 10, 1), "dfs_rankings")

    def test_too_long_tag_raises(self):
        # DataForSEO nimmt bis 255 Zeichen. Ein längerer käme gekürzt oder gar
        # nicht zurück, und die Zeile im Ledger zeigte auf nichts.
        with self.assertRaises(ValueError):
            ledger.build_tag("x" * 300, date(2026, 10, 1), "dfs_rankings")


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)

    def test_path_sits_next_to_the_data_folder(self):
        self.assertEqual(ledger.ledger_path(self.ws),
                         self.ws / "reporting" / "dfs-ledger.jsonl")

    def test_appends_one_line_per_call(self):
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.01})
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.02})
        lines = ledger.ledger_path(self.ws).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["cost_usd"], 0.02)

    def test_never_rewrites_earlier_lines(self):
        ledger.append(self.ws, {"run_id": "a", "cost_usd": 0.01})
        first = ledger.ledger_path(self.ws).read_text(encoding="utf-8")
        ledger.append(self.ws, {"run_id": "b", "cost_usd": 0.02})
        self.assertTrue(
            ledger.ledger_path(self.ws).read_text(encoding="utf-8").startswith(first))

    def test_timestamp_is_added_when_missing(self):
        # Eine Zeile ohne Zeit ist als Beleg wertlos.
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.01})
        entry = json.loads(ledger.ledger_path(self.ws).read_text(encoding="utf-8"))
        self.assertIn("ts", entry)

    def test_given_timestamp_is_kept(self):
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.01, "ts": "2026-10-01T09:00:00+00:00"})
        entry = json.loads(ledger.ledger_path(self.ws).read_text(encoding="utf-8"))
        self.assertEqual(entry["ts"], "2026-10-01T09:00:00+00:00")


class TestSpent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        for cost, run in ((0.01, "2026-10-01-audit"), (0.02, "2026-10-01-audit"),
                          (5.00, "2026-11-01-month")):
            ledger.append(self.ws, {"run_id": run, "cost_usd": cost})

    def test_sums_only_the_given_run(self):
        self.assertAlmostEqual(ledger.spent(self.ws, "2026-10-01-audit"), 0.03)

    def test_missing_ledger_means_nothing_spent(self):
        empty = Path(tempfile.mkdtemp())
        self.assertEqual(ledger.spent(empty, "2026-10-01-audit"), 0.0)

    def test_broken_line_raises_instead_of_undercounting(self):
        # Eine unlesbare Zeile stillschweigend zu überspringen senkt die Summe
        # und hebt damit den Deckel an. Genau das darf nie passieren.
        with ledger.ledger_path(self.ws).open("a", encoding="utf-8") as handle:
            handle.write("{kaputt\n")
        with self.assertRaises(ValueError):
            ledger.spent(self.ws, "2026-10-01-audit")

    def test_line_without_cost_raises(self):
        with ledger.ledger_path(self.ws).open("a", encoding="utf-8") as handle:
            handle.write('{"run_id": "2026-10-01-audit"}\n')
        with self.assertRaises(ValueError):
            ledger.spent(self.ws, "2026-10-01-audit")

    def test_blank_lines_are_ignored(self):
        with ledger.ledger_path(self.ws).open("a", encoding="utf-8") as handle:
            handle.write("\n\n")
        self.assertAlmostEqual(ledger.spent(self.ws, "2026-10-01-audit"), 0.03)

    def test_remaining_is_never_negative(self):
        self.assertEqual(ledger.remaining(self.ws, "2026-11-01-month", cap=1.0), 0.0)


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)

    def test_allows_a_call_that_fits(self):
        ledger.check_budget(self.ws, "r", cap=1.0, estimate=0.10)

    def test_refuses_when_the_estimate_would_break_the_cap(self):
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.95})
        with self.assertRaises(ledger.BudgetExceeded):
            ledger.check_budget(self.ws, "r", cap=1.0, estimate=0.10)

    def test_refuses_when_the_cap_is_already_spent(self):
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 1.20})
        with self.assertRaises(ledger.BudgetExceeded):
            ledger.check_budget(self.ws, "r", cap=1.0, estimate=0.0)

    def test_message_names_cap_spent_and_estimate(self):
        ledger.append(self.ws, {"run_id": "r", "cost_usd": 0.95})
        with self.assertRaises(ledger.BudgetExceeded) as caught:
            ledger.check_budget(self.ws, "r", cap=1.0, estimate=0.10)
        text = str(caught.exception)
        for part in ("1.0", "0.95", "0.1"):
            self.assertIn(part, text)

    def test_cap_zero_refuses_everything(self):
        # Ein Deckel von 0 heißt "kein DataForSEO in diesem Lauf", nicht
        # "unbegrenzt". Der Unterschied ist bares Geld.
        with self.assertRaises(ledger.BudgetExceeded):
            ledger.check_budget(self.ws, "r", cap=0.0, estimate=0.01)

    def test_another_run_does_not_count_against_this_cap(self):
        ledger.append(self.ws, {"run_id": "anderer-lauf", "cost_usd": 99.0})
        ledger.check_budget(self.ws, "r", cap=1.0, estimate=0.10)


if __name__ == "__main__":
    unittest.main()
