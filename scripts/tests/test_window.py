"""Das Auswertungsfenster gegen Snapshots auf der Platte.

Geprüft wird, woher die Käufe aus Analytics kommen. Bis zum 11.09.2026 las das
Fenster `transactions`, und darin zählt GA4 auch Refunds mit.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import window  # noqa: E402

#: Zwei volle Jahre bis August 2026: Fenster 09/2025 bis 08/2026, Vorjahr davor.
MONTHS = window.months("2026-08", 24)


def build(tmp, ga4_month, orders=100):
    """Schreibt shopify.json und ga4.json und baut das Fenster.

    `ga4_month(month)` liefert die Analytics-Zeile eines Monats ohne den
    Monatsschlüssel, oder None, wenn der Monat in Analytics fehlt."""
    d = Path(tmp)
    shop = {"period": {"start": "2024-09-01", "end": "2026-08-31"},
            "by_month": [{"month": m, "total_sales": 10_000.0, "net_sales": 8_000.0,
                          "orders": orders} for m in MONTHS]}
    rows = []
    for m in MONTHS:
        values = ga4_month(m)
        if values is not None:
            rows.append({"month": m, **values})
    (d / "shopify.json").write_text(json.dumps(shop), encoding="utf-8")
    (d / "ga4.json").write_text(json.dumps({"by_month": rows}), encoding="utf-8")
    return window.build(d)


class TestAnalyticsPurchases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_purchases_come_from_the_purchases_field(self):
        f = build(self.tmp.name, lambda m: {"sessions": 5_000, "purchases": 90,
                                            "transactions": 120,
                                            "purchase_revenue": 9_000.0})
        self.assertEqual(f["jetzt"]["ga4_kaeufe"], 90 * 12)

    def test_a_snapshot_with_only_transactions_yields_none_not_zero(self):
        # Ältere Snapshots tragen nur `transactions`, und darin stecken
        # Refunds. Null hieße "kein einziger Kauf gemessen" und ergäbe im
        # Report eine Lücke von 100 Prozent.
        f = build(self.tmp.name, lambda m: {"sessions": 5_000, "transactions": 120,
                                            "purchase_revenue": 9_000.0})
        self.assertIsNone(f["jetzt"]["ga4_kaeufe"])

    def test_unmeasured_purchases_are_no_missing_measurement(self):
        # Hat die Property die Kaufmetrik abgelehnt, steht `purchases: null`.
        # Das ist "nicht abgefragt", nicht "keine Kaufmessung".
        f = build(self.tmp.name, lambda m: {"sessions": 5_000, "purchases": None,
                                            "purchase_revenue": 9_000.0})
        self.assertEqual(f["stoerungen"], [])

    def test_a_month_missing_in_analytics_is_reported(self):
        f = build(self.tmp.name, lambda m: None if m == "2026-03" else
                  {"sessions": 5_000, "purchases": 95, "purchase_revenue": 9_000.0})
        self.assertEqual(f["stoerungen"], [("2026-03", "keine Kaufmessung in Analytics")])

    def test_a_month_with_zero_purchases_is_reported(self):
        f = build(self.tmp.name, lambda m: {"sessions": 5_000,
                                            "purchases": 0 if m == "2026-04" else 95,
                                            "purchase_revenue": 9_000.0})
        self.assertEqual(f["stoerungen"], [("2026-04", "keine Kaufmessung in Analytics")])

    def test_a_low_share_of_purchases_is_reported(self):
        f = build(self.tmp.name, lambda m: {"sessions": 5_000,
                                            "purchases": 40 if m == "2026-05" else 95,
                                            "purchase_revenue": 9_000.0})
        self.assertEqual(f["stoerungen"], [("2026-05", "nur 40% der Bestellungen zugeordnet")])


if __name__ == "__main__":
    unittest.main()
