"""Monatsreihe aus der GSC-Tagesreihe. Kein Test ruft die API."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent
                       / "skills" / "pull-gsc" / "scripts"))
import gsc_pull  # noqa: E402


def day(date, clicks=10, impressions=100, position=5.0):
    return {"date": date, "clicks": clicks, "impressions": impressions,
            "ctr": round(clicks / impressions, 4) if impressions else 0,
            "position": position}


class TestByMonth(unittest.TestCase):
    def test_groups_days_into_months(self):
        rows = [day("2026-08-01"), day("2026-08-31"), day("2026-09-02")]
        months = gsc_pull.build_by_month(rows)
        self.assertEqual([m["month"] for m in months], ["2026-08", "2026-09"])

    def test_months_are_sorted_and_zero_padded(self):
        # "2026-9" sortiert als Text vor "2026-10" und macht jeden späteren
        # Vergleich gegen denselben Kalendermonat der Baseline kaputt.
        rows = [day("2026-10-01"), day("2026-09-01")]
        self.assertEqual([m["month"] for m in gsc_pull.build_by_month(rows)],
                         ["2026-09", "2026-10"])

    def test_clicks_and_impressions_are_summed(self):
        rows = [day("2026-08-01", clicks=10, impressions=100),
                day("2026-08-02", clicks=5, impressions=50)]
        month = gsc_pull.build_by_month(rows)[0]
        self.assertEqual((month["clicks"], month["impressions"]), (15, 150))

    def test_ctr_is_recomputed_not_averaged(self):
        # Der Mittelwert zweier Tages-CTR ist nicht die CTR des Monats,
        # sobald die Tage verschieden viele Impressionen haben.
        rows = [day("2026-08-01", clicks=10, impressions=100),
                day("2026-08-02", clicks=1, impressions=900)]
        month = gsc_pull.build_by_month(rows)[0]
        self.assertAlmostEqual(month["ctr"], 11 / 1000, places=4)

    def test_position_is_weighted_by_impressions(self):
        # Ein Tag mit 10 Impressionen darf nicht so viel wiegen wie einer mit
        # 1000. Der ungewichtete Mittelwert wäre eine Zahl, die es nicht gibt.
        rows = [day("2026-08-01", impressions=1000, position=2.0),
                day("2026-08-02", impressions=10, position=90.0)]
        month = gsc_pull.build_by_month(rows)[0]
        self.assertAlmostEqual(month["position"], (2.0 * 1000 + 90.0 * 10) / 1010, places=2)

    def test_month_without_impressions_has_no_position(self):
        # Keine Impressionen heisst keine Position. Eine 0 stünde im Report
        # als Platz 0, also besser als Platz 1.
        rows = [day("2026-08-01", clicks=0, impressions=0, position=0.0)]
        month = gsc_pull.build_by_month(rows)[0]
        self.assertIsNone(month["position"])
        self.assertEqual(month["ctr"], 0)

    def test_empty_series_gives_an_empty_list(self):
        self.assertEqual(gsc_pull.build_by_month([]), [])

    def test_broken_date_is_skipped_not_counted_into_a_wrong_month(self):
        # Eine Zeile ohne brauchbares Datum in irgendeinen Monat zu werfen
        # verfälscht genau diesen Monat.
        rows = [day("2026-08-01"), {"date": "", "clicks": 99, "impressions": 99}]
        months = gsc_pull.build_by_month(rows)
        self.assertEqual(len(months), 1)
        self.assertEqual(months[0]["clicks"], 10)


if __name__ == "__main__":
    unittest.main()
