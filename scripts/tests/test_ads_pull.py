"""Abfragen und Auswertung von pull-ads. Kein Test ruft die API."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(SKILLS / "pull-ads" / "scripts"))
import ads_pull  # noqa: E402


def row(date_, cost_micros, conversions=0.0, name="Brand DE", impressions="100",
        clicks="10", value=0.0, share=0.7):
    return {
        "campaign": {"id": "1", "name": name, "status": "ENABLED",
                      "advertisingChannelType": "SEARCH"},
        "metrics": {"impressions": impressions, "clicks": clicks,
                     "costMicros": str(cost_micros), "conversions": conversions,
                     "conversionsValue": value,
                     "searchImpressionShare": share,
                     "searchBudgetLostImpressionShare": 0.1,
                     "searchRankLostImpressionShare": 0.2},
        "segments": {"date": date_},
    }


class TestQueries(unittest.TestCase):
    def test_dates_are_quoted_in_the_where_clause(self):
        self.assertIn("BETWEEN '2026-01-01' AND '2026-08-31'",
                      ads_pull.query_campaigns("2026-01-01", "2026-08-31"))

    def test_campaign_query_asks_for_the_three_impression_share_metrics(self):
        query = ads_pull.query_campaigns("2026-01-01", "2026-08-31")
        for field in ("metrics.search_impression_share",
                      "metrics.search_budget_lost_impression_share",
                      "metrics.search_rank_lost_impression_share"):
            self.assertIn(field, query)

    def test_campaign_query_segments_by_date(self):
        # Ohne segments.date gibt es keine Monatsreihe, und die Baseline
        # verlangt Ausgaben je Monat.
        self.assertIn("segments.date", ads_pull.query_campaigns("a", "b"))

    def test_search_term_query_uses_the_search_term_view(self):
        self.assertIn("FROM search_term_view", ads_pull.query_search_terms("a", "b"))

    def test_history_probe_starts_far_before_any_account(self):
        # Der Historienanfang wird gemessen wie bei GSC und GA4, nicht
        # angenommen. Ein zu später Start kürzte die Baseline still.
        self.assertIn("'2010-01-01'", ads_pull.query_history())

    def test_customer_query_asks_for_the_currency(self):
        # Ein Betrag ohne Währung ist keine Zahl. Ein Euro-Betrag aus einem
        # Konto in Franken fällt niemandem auf.
        self.assertIn("customer.currency_code", ads_pull.query_customer())


class TestMonthly(unittest.TestCase):
    def test_aggregates_days_into_months(self):
        months = ads_pull.by_month([row("2026-08-01", 10_000_000),
                                     row("2026-08-30", 5_000_000),
                                     row("2026-09-02", 1_000_000)])
        self.assertEqual([m["month"] for m in months], ["2026-08", "2026-09"])
        self.assertAlmostEqual(months[0]["cost"], 15.0)

    def test_months_are_sorted_and_zero_padded(self):
        months = ads_pull.by_month([row("2026-10-01", 1), row("2026-09-01", 1)])
        self.assertEqual([m["month"] for m in months], ["2026-09", "2026-10"])

    def test_roas_is_value_over_cost(self):
        months = ads_pull.by_month([row("2026-08-01", 100_000_000,
                                         conversions=4.0, value=400.0)])
        self.assertAlmostEqual(months[0]["roas"], 4.0)

    def test_roas_without_cost_is_none_not_infinite(self):
        # Ein Monat ohne Ausgaben hat keinen ROAS. Eine 0 läse sich als
        # "nichts eingebracht", eine Division wäre ein Absturz.
        months = ads_pull.by_month([row("2026-08-01", 0, conversions=1.0, value=50.0)])
        self.assertIsNone(months[0]["roas"])

    def test_impression_share_is_weighted_by_impressions(self):
        # Der ungewichtete Mittelwert zweier Tage mit sehr verschiedener
        # Impression-Zahl ist eine Zahl, die es nicht gibt.
        rows = [row("2026-08-01", 1, impressions="1000", share=0.9),
                row("2026-08-02", 1, impressions="10", share=0.1)]
        self.assertAlmostEqual(ads_pull.by_month(rows)[0]["search_impression_share"],
                               (0.9 * 1000 + 0.1 * 10) / 1010, places=4)

    def test_month_without_impressions_has_no_share(self):
        # Keine Impressionen heisst kein Impression Share. Eine 0 stünde im
        # Report als "nie ausgeliefert", und das ist etwas anderes.
        rows = [row("2026-08-01", 0, impressions="0")]
        self.assertIsNone(ads_pull.by_month(rows)[0]["search_impression_share"])

    def test_row_without_a_date_is_skipped(self):
        broken = row("2026-08-01", 1)
        broken["segments"] = {}
        self.assertEqual(ads_pull.by_month([broken]), [])


class TestWaste(unittest.TestCase):
    def term(self, text, cost_micros, conversions=0.0, clicks="5"):
        return {"searchTermView": {"searchTerm": text}, "campaign": {"name": "Generisch"},
                "metrics": {"costMicros": str(cost_micros), "conversions": conversions,
                             "clicks": clicks, "impressions": "50"}}

    def test_sums_cost_of_terms_without_conversions(self):
        shaped = ads_pull.shape_search_terms([
            self.term("gratis muster", 30_000_000),
            self.term("brand kaufen", 10_000_000, conversions=3.0)])
        self.assertAlmostEqual(shaped["summary_search_terms"]["cost_without_conversion"], 30.0)
        self.assertEqual(shaped["summary_search_terms"]["terms_without_conversion"], 1)

    def test_terms_are_sorted_by_wasted_cost(self):
        shaped = ads_pull.shape_search_terms([self.term("klein", 1_000_000),
                                               self.term("gross", 50_000_000)])
        self.assertEqual(shaped["search_terms_without_conversion"][0]["term"], "gross")

    def test_list_is_capped_but_the_sum_is_complete(self):
        terms = [self.term(f"t{i}", 1_000_000) for i in range(ads_pull.MAX_TERMS + 50)]
        shaped = ads_pull.shape_search_terms(terms)
        self.assertEqual(len(shaped["search_terms_without_conversion"]), ads_pull.MAX_TERMS)
        self.assertTrue(shaped["search_terms_truncated"])
        self.assertAlmostEqual(shaped["summary_search_terms"]["cost_without_conversion"],
                               (ads_pull.MAX_TERMS + 50) * 1.0)

    def test_fractional_conversions_count_as_converted(self):
        # Google zählt Conversions als Bruchteile. 0,5 ist eine Conversion,
        # keine Verschwendung.
        shaped = ads_pull.shape_search_terms([self.term("halb", 10_000_000, conversions=0.5)])
        self.assertEqual(shaped["summary_search_terms"]["terms_without_conversion"], 0)


class TestHistory(unittest.TestCase):
    def test_history_start_is_the_earliest_day_with_data(self):
        self.assertEqual(ads_pull.history_start([row("2024-03-11", 1), row("2023-11-02", 1)]),
                         "2023-11-02")

    def test_no_rows_means_no_history(self):
        self.assertIsNone(ads_pull.history_start([]))


class TestCampaigns(unittest.TestCase):
    def test_campaigns_are_aggregated_over_the_period(self):
        rows = [row("2026-08-01", 10_000_000, name="Brand DE"),
                row("2026-09-01", 5_000_000, name="Brand DE"),
                row("2026-08-01", 2_000_000, name="Generisch DE")]
        campaigns = ads_pull.shape_campaigns(rows)["campaigns"]
        by_name = {c["name"]: c for c in campaigns}
        self.assertAlmostEqual(by_name["Brand DE"]["cost"], 15.0)
        self.assertAlmostEqual(by_name["Generisch DE"]["cost"], 2.0)

    def test_campaigns_are_sorted_by_cost(self):
        rows = [row("2026-08-01", 1_000_000, name="klein"),
                row("2026-08-01", 90_000_000, name="gross")]
        self.assertEqual(ads_pull.shape_campaigns(rows)["campaigns"][0]["name"], "gross")


class TestTokenLookup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name)
        self.central = self.ws / "central.env"
        old = ads_pull.operator_env.CENTRAL
        ads_pull.operator_env.CENTRAL = self.central
        self.addCleanup(setattr, ads_pull.operator_env, "CENTRAL", old)
        saved = os.environ.pop("PTAI_GOOGLE_ADS_TOKEN", None)
        if saved is not None:
            self.addCleanup(os.environ.__setitem__, "PTAI_GOOGLE_ADS_TOKEN", saved)

    def test_token_from_the_central_file(self):
        self.central.write_text("PTAI_GOOGLE_ADS_TOKEN=zentral\n", encoding="utf-8")
        self.assertEqual(ads_pull.resolve_token(self.ws), "zentral")

    def test_no_token_anywhere_gives_empty_string(self):
        self.assertEqual(ads_pull.resolve_token(self.ws), "")


if __name__ == "__main__":
    unittest.main()
