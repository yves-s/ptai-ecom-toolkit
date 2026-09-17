"""Aufbereitung des GA4-Pulls.

Kein Test öffnet einen Socket: geprüft wird die Aufbereitung der Zeilen, so
wie `parse_rows` sie liefert, also `(dims, metrics)` mit dims in
Header-Reihenfolge und metrics als Dict der GA4-Metriknamen. Wo eine Funktion
selbst abfragt, ersetzt der Test `run_report`.
"""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "skills" / "pull-ga4" / "scripts"))
import ga4_pull  # noqa: E402


def row(month, channel, sessions, users=0, revenue=0.0, purchases=None):
    metrics = {"sessions": sessions, "totalUsers": users, "purchaseRevenue": revenue}
    if purchases is not None:
        metrics["ecommercePurchases"] = purchases
    return ([month, channel], metrics)


def fake_report(values, currency="EUR", calls=None):
    """Ersetzt run_report: eine Zeile für 09/2025, je angefragter Metrik der
    Wert aus `values`. So sieht der Test, welche Metrik abgefragt wurde."""
    def run_report(prop, token, body):
        if calls is not None:
            calls.append(body)
        names = [m["name"] for m in body["metrics"]]
        return {"metadata": {"currencyCode": currency},
                "dimensionHeaders": [{"name": d["name"]} for d in body.get("dimensions", [])],
                "metricHeaders": [{"name": n} for n in names],
                "rows": [{"dimensionValues": [{"value": "202509"}],
                          "metricValues": [{"value": values.get(n, "0")} for n in names]}]}
    return run_report


def http_error(code, message):
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError("https://example.invalid", code, "error", None,
                                  io.BytesIO(body))


class TestPurchaseMetric(unittest.TestCase):
    """Käufe kommen aus `ecommercePurchases`, nie aus `transactions`.

    GA4 zählt in `transactions` auch `refund`-Ereignisse mit, und
    serverseitige Connectoren senden Refunds. Am 11.09.2026 gegen echte
    Properties nachgeprüft: `ecommercePurchases` lag in jedem Monat exakt bei
    der Zahl der `purchase`-Ereignisse, `transactions` bei Käufen plus Refunds.
    """

    def test_no_call_asks_for_transactions(self):
        for metrics in (ga4_pull.CHANNEL_METRICS, ga4_pull.BREAKDOWN_METRICS,
                        ga4_pull.LANDING_METRICS):
            with self.subTest(metrics=metrics):
                self.assertNotIn("transactions", metrics)
                self.assertIn("ecommercePurchases", metrics)


class TestByMonth(unittest.TestCase):
    def test_empty_rows_yield_an_empty_series(self):
        self.assertEqual(ga4_pull.build_by_month([]), [])

    def test_year_month_becomes_an_iso_month(self):
        series = ga4_pull.build_by_month([row("202501", "Organic Search", 10)])
        self.assertEqual(series[0]["month"], "2025-01")

    def test_months_are_sorted_chronologically(self):
        series = ga4_pull.build_by_month([
            row("202502", "Direct", 5),
            row("202412", "Direct", 5),
            row("202501", "Direct", 5),
        ])
        self.assertEqual([m["month"] for m in series], ["2024-12", "2025-01", "2025-02"])

    def test_sessions_revenue_and_purchases_sum_across_channels(self):
        series = ga4_pull.build_by_month([
            row("202501", "Organic Search", 100, revenue=500.0, purchases=4),
            row("202501", "Paid Search", 40, revenue=250.5, purchases=2),
        ])
        self.assertEqual(series[0]["sessions"], 140)
        self.assertEqual(series[0]["purchase_revenue"], 750.5)
        self.assertEqual(series[0]["purchases"], 6)

    def test_the_month_total_carries_no_user_count(self):
        # GA4 entdoppelt Nutzer je Dimensionskombination. Wer im selben Monat
        # über Organic und über E-Mail kommt, steht in beiden Kanalzeilen. Eine
        # Summe wäre deshalb größer als die tatsächliche Nutzerzahl, und
        # genau diese Summe steht heute fälschlich in build_block als
        # totals.total_users.
        series = ga4_pull.build_by_month([
            row("202501", "Organic Search", 100, users=80),
            row("202501", "Email", 40, users=30),
        ])
        self.assertNotIn("total_users", series[0])

    def test_users_stay_readable_per_channel(self):
        series = ga4_pull.build_by_month([row("202501", "Organic Search", 100, users=80)])
        self.assertEqual(series[0]["channels"][0]["total_users"], 80)

    def test_channels_are_sorted_by_sessions(self):
        series = ga4_pull.build_by_month([
            row("202501", "Direct", 10),
            row("202501", "Organic Search", 90),
            row("202501", "Email", 50),
        ])
        self.assertEqual([c["channel"] for c in series[0]["channels"]],
                         ["Organic Search", "Email", "Direct"])

    def test_missing_purchases_stay_none_instead_of_zero(self):
        # Der Fallback in run_channels nimmt die Metrik aus dem Call. Null hieße
        # "kein Kauf", None heisst "nicht gemessen".
        series = ga4_pull.build_by_month([row("202501", "Direct", 10)])
        self.assertIsNone(series[0]["purchases"])
        self.assertIsNone(series[0]["channels"][0]["purchases"])

    def test_a_month_with_some_purchases_does_not_lose_them(self):
        series = ga4_pull.build_by_month([
            row("202501", "Organic Search", 100, purchases=4),
            row("202501", "Direct", 10),
        ])
        self.assertEqual(series[0]["purchases"], 4)

    def test_transactions_are_never_read_as_purchases(self):
        # Ein Wert unter `transactions` enthält Refunds. Er wird nicht
        # umgedeutet, auch nicht als Ersatz, wenn die Käufe fehlen.
        series = ga4_pull.build_by_month([(["202501", "Direct"],
                                           {"sessions": 10, "transactions": 9})])
        self.assertIsNone(series[0]["purchases"])
        self.assertNotIn("transactions", series[0])
        self.assertNotIn("transactions", series[0]["channels"][0])

    def test_revenue_is_rounded_to_cents(self):
        series = ga4_pull.build_by_month([row("202501", "Direct", 1, revenue=1.005)])
        self.assertEqual(series[0]["purchase_revenue"], round(1.005, 2))

    def test_a_row_without_a_channel_is_kept_as_not_set(self):
        series = ga4_pull.build_by_month([(["202501"], {"sessions": 7})])
        self.assertEqual(series[0]["channels"][0]["channel"], "(not set)")
        self.assertEqual(series[0]["sessions"], 7)


class TestBlockPurchases(unittest.TestCase):
    """Jede Sicht mit Käufen trägt `purchases`, keine trägt `transactions`."""

    PERIOD = {"start": "a", "end": "b", "granularity": "month"}

    def test_channels_carry_purchases_not_transactions(self):
        rows = [(["Direct"], {"sessions": 10, "ecommercePurchases": 5, "transactions": 7})]
        block = ga4_pull.build_block(self.PERIOD, rows, [], [], [], [], [])
        self.assertEqual(block["channels"][0]["purchases"], 5)
        self.assertNotIn("transactions", block["channels"][0])

    def test_breakdowns_carry_purchases(self):
        items = ga4_pull.build_breakdown(
            [(["mobile"], {"sessions": 10, "ecommercePurchases": 2, "transactions": 3})],
            "device")
        self.assertEqual(items[0]["purchases"], 2)
        self.assertNotIn("transactions", items[0])

    def test_a_breakdown_without_the_metric_shows_none(self):
        items = ga4_pull.build_breakdown([(["mobile"], {"sessions": 10})], "device")
        self.assertIsNone(items[0]["purchases"])

    def test_landing_pages_carry_purchases(self):
        landing = [(["/"], {"sessions": 10, "engagementRate": 0.5,
                            "purchaseRevenue": 99.0, "ecommercePurchases": 1})]
        block = ga4_pull.build_block(self.PERIOD, [], landing, [], [], [], [])
        self.assertEqual(block["landing_pages"][0]["purchases"], 1)
        self.assertNotIn("transactions", block["landing_pages"][0])


class TestReadCompare(unittest.TestCase):
    """Die Vergleichsreihe beantwortet, welche Property zum Shop passt. Sie
    darf dafür keine Refunds als Käufe zählen."""

    VALUES = {"sessions": "1200", "ecommercePurchases": "30", "transactions": "41",
              "purchaseRevenue": "2500.5"}

    def compare(self, currency="EUR", calls=None):
        with mock.patch.object(ga4_pull, "run_report",
                               fake_report(self.VALUES, currency, calls)):
            return ga4_pull.read_compare(["1"], "token", "2025-09-01", "2025-09-30")[0]

    def test_asks_for_purchases_not_transactions(self):
        calls = []
        self.compare(calls=calls)
        names = [m["name"] for m in calls[0]["metrics"]]
        self.assertIn("ecommercePurchases", names)
        self.assertNotIn("transactions", names)

    def test_a_month_carries_sessions_purchases_and_revenue(self):
        self.assertEqual(self.compare()["by_month"],
                         [{"month": "2025-09", "sessions": 1200, "purchases": 30,
                           "purchase_revenue": 2500.5}])

    def test_the_block_names_the_property_currency(self):
        # Umsatz einer Property in Dollar gegen einen Shop in Euro ist kein
        # Vergleich. Die Währung steht deshalb neben der Reihe.
        self.assertEqual(self.compare(currency="USD")["currency"], "USD")


class TestResponseCurrency(unittest.TestCase):
    def test_the_currency_comes_from_the_response_metadata(self):
        self.assertEqual(
            ga4_pull.response_currency({"metadata": {"currencyCode": "USD"}}), "USD")

    def test_without_metadata_the_currency_is_none(self):
        self.assertIsNone(ga4_pull.response_currency({}))


class TestRunChannelsFallback(unittest.TestCase):
    BODY = {"metrics": [{"name": "sessions"}, {"name": "ecommercePurchases"}]}

    def test_a_rejected_purchase_metric_is_dropped_once_with_a_note(self):
        calls = []

        def run_report(prop, token, body):
            calls.append(body)
            if len(calls) == 1:
                raise http_error(400, "Field ecommercePurchases is not a valid metric.")
            return {}

        with mock.patch.object(ga4_pull, "run_report", run_report):
            _, note = ga4_pull.run_channels("1", "token", self.BODY)
        self.assertEqual([m["name"] for m in calls[1]["metrics"]], ["sessions"])
        self.assertIn("ecommercePurchases", note)

    def test_any_other_rejection_is_raised(self):
        with mock.patch.object(ga4_pull, "run_report",
                               mock.Mock(side_effect=http_error(400, "Field sessions is broken."))):
            with self.assertRaises(RuntimeError):
                ga4_pull.run_channels("1", "token", self.BODY)


class TestChannelTotals(unittest.TestCase):
    """`totals` kommt von der API, nicht aus einer Summe über die Kanäle.

    GA4 entdoppelt Nutzer je Dimensionskombination. Wer über Organic und über
    E-Mail kommt, steht in beiden Kanalzeilen, die Summe ist also zu hoch. Die
    API liefert mit `metricAggregations: ["TOTAL"]` die entdoppelte Zeile.
    """

    def channel(self, name, sessions, users, revenue=0.0):
        return ([name], {"sessions": sessions, "totalUsers": users,
                         "purchaseRevenue": revenue})

    def block(self, rows, totals=None):
        return ga4_pull.build_block({"start": "a", "end": "b", "granularity": "month"},
                                    rows, [], [], [], [], [], channel_totals=totals)

    def test_the_api_total_wins_over_the_channel_sum(self):
        rows = [self.channel("Organic Search", 100, 80), self.channel("Email", 40, 30)]
        block = self.block(rows, {"sessions": 140, "totalUsers": 95, "purchaseRevenue": 0.0})
        # 80 + 30 wären 110, tatsächlich sind es 95 verschiedene Menschen.
        self.assertEqual(block["totals"]["total_users"], 95)

    def test_sessions_and_revenue_also_come_from_the_api(self):
        rows = [self.channel("Direct", 10, 8, 100.0)]
        block = self.block(rows, {"sessions": 10, "totalUsers": 8, "purchaseRevenue": 100.0})
        self.assertEqual(block["totals"]["sessions"], 10)
        self.assertEqual(block["totals"]["purchase_revenue"], 100.0)

    def test_without_an_api_total_the_user_count_is_none_not_a_sum(self):
        # Lieber keine Zahl als eine zu hohe: eine fehlende Zahl fällt auf,
        # eine um Prozente zu hohe nicht.
        rows = [self.channel("Organic Search", 100, 80), self.channel("Email", 40, 30)]
        block = self.block(rows, None)
        self.assertIsNone(block["totals"]["total_users"])

    def test_without_an_api_total_sessions_and_revenue_still_add_up(self):
        rows = [self.channel("Organic Search", 100, 80, 12.0),
                self.channel("Email", 40, 30, 8.0)]
        block = self.block(rows, None)
        self.assertEqual(block["totals"]["sessions"], 140)
        self.assertEqual(block["totals"]["purchase_revenue"], 20.0)

    def test_the_funnel_base_follows_the_totals(self):
        rows = [self.channel("Direct", 10, 8)]
        block = self.block(rows, {"sessions": 10, "totalUsers": 8, "purchaseRevenue": 0.0})
        self.assertEqual(block["funnel"]["sessions"], 10)


class TestParseTotals(unittest.TestCase):
    def test_totals_are_split_by_date_range_like_the_rows(self):
        resp = {
            "dimensionHeaders": [{"name": "sessionDefaultChannelGroup"}, {"name": "dateRange"}],
            "metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}],
            "totals": [
                {"dimensionValues": [{"value": "RESERVED_TOTAL"}, {"value": "date_range_0"}],
                 "metricValues": [{"value": "140"}, {"value": "95"}]},
                {"dimensionValues": [{"value": "RESERVED_TOTAL"}, {"value": "date_range_1"}],
                 "metricValues": [{"value": "70"}, {"value": "50"}]},
            ],
        }
        totals = ga4_pull.parse_totals(resp)
        self.assertEqual(totals["date_range_0"]["totalUsers"], 95)
        self.assertEqual(totals["date_range_1"]["totalUsers"], 50)

    def test_a_single_range_lands_under_date_range_zero(self):
        resp = {
            "dimensionHeaders": [{"name": "sessionDefaultChannelGroup"}],
            "metricHeaders": [{"name": "sessions"}],
            "totals": [{"dimensionValues": [{"value": "RESERVED_TOTAL"}],
                        "metricValues": [{"value": "12"}]}],
        }
        self.assertEqual(ga4_pull.parse_totals(resp)["date_range_0"]["sessions"], 12)

    def test_a_response_without_totals_yields_an_empty_dict(self):
        self.assertEqual(ga4_pull.parse_totals({"rows": []}), {})


from audit import bots, senders  # noqa: E402

BOT = {"screenResolution": "1440x1440", "operatingSystem": "Windows",
       "deviceCategory": "desktop", "browser": "Chrome"}
RANGE = {"startDate": "2026-03-01", "endDate": "2026-03-30"}


def response(dims, metrics, rows, totals=None, metadata=None):
    """Eine runReport-Antwort aus (Dimensionswerte, Metrikwerte)-Paaren."""
    resp = {"dimensionHeaders": [{"name": d} for d in dims],
            "metricHeaders": [{"name": m} for m in metrics],
            "rows": [{"dimensionValues": [{"value": v} for v in d],
                      "metricValues": [{"value": str(x)} for x in m]} for d, m in rows],
            "metadata": metadata or {}}
    if totals is not None:
        resp["totals"] = [{"dimensionValues": [{"value": "RESERVED_TOTAL"}],
                           "metricValues": [{"value": str(x)} for x in totals]}]
    return resp


class FakeGA4:
    """Ersetzt run_report und antwortet je nach angefragten Dimensionen."""

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, prop, token, body):
        self.calls.append(body)
        dims = tuple(d["name"] for d in body.get("dimensions", []))
        return self.handlers[dims](body)

    def calls_with(self, *dims):
        return [b for b in self.calls if tuple(d["name"] for d in b.get("dimensions", [])) == dims]


def ga4_date(n):
    return f"202603{n + 1:02d}"


def filter_values(expression):
    """Alle (Feld, Werte) in einem dimensionFilter, egal wie verschachtelt."""
    found = []
    if isinstance(expression, dict):
        leaf = expression.get("filter")
        if leaf:
            values = (leaf.get("inListFilter") or {}).get("values") or [
                (leaf.get("stringFilter") or {}).get("value")]
            found.append((leaf["fieldName"], tuple(values)))
        for value in expression.values():
            if isinstance(value, (dict, list)):
                found += filter_values(value)
    elif isinstance(expression, list):
        for item in expression:
            found += filter_values(item)
    return found


class TestProfileExclusion(unittest.TestCase):
    """Der Vorschlag aus bots.filter_proposal() lässt sich als Config-Regel anwenden."""

    def test_a_profile_rule_becomes_one_negated_and_group(self):
        assessed = bots.assess_profile(
            BOT, {"sessions": 480, "engaged_sessions": 20, "purchases": 0}, 1_000)
        proposal = dict(bots.filter_proposal({"profiles": [assessed]}), enabled=True)
        flt, applied = ga4_pull.build_exclusion_filter(proposal)
        conditions = flt["notExpression"]["andGroup"]["expressions"]
        self.assertEqual({c["filter"]["fieldName"] for c in conditions},
                         {"screenResolution", "operatingSystem", "deviceCategory", "browser"})
        self.assertEqual(len(applied), 1)

    def test_an_existing_rule_keeps_its_shape(self):
        flt, _ = ga4_pull.build_exclusion_filter({"enabled": True, "exclude": [
            {"country_not_in": ["Germany"], "channel_in": ["Direct"], "reason": "x"}]})
        conditions = flt["notExpression"]["andGroup"]["expressions"]
        self.assertEqual(conditions[0], {"notExpression": {"filter": {
            "fieldName": "country", "inListFilter": {"values": ["Germany"]}}}})
        self.assertEqual(conditions[1]["filter"]["fieldName"], "sessionDefaultChannelGroup")


class TestBlockBodies(unittest.TestCase):
    FILTER = {"filter": {"fieldName": "country", "inListFilter": {"values": ["X"]}}}

    def test_every_view_carries_the_filter(self):
        bodies = ga4_pull.block_bodies([RANGE], self.FILTER)
        self.assertEqual(set(bodies), {"channels", "campaigns", "devices", "countries",
                                       "landing_pages", "funnel"})
        for name, body in bodies.items():
            with self.subTest(view=name):
                self.assertIn(("country", ("X",)), filter_values(body["dimensionFilter"]))

    def test_the_funnel_keeps_its_event_filter(self):
        funnel = ga4_pull.block_bodies([RANGE], self.FILTER)["funnel"]
        self.assertIn(("eventName", tuple(ga4_pull.FUNNEL_EVENTS)),
                      filter_values(funnel["dimensionFilter"]))

    def test_without_a_filter_only_the_funnel_filters(self):
        bodies = ga4_pull.block_bodies([RANGE], None)
        self.assertEqual([n for n, b in bodies.items() if "dimensionFilter" in b], ["funnel"])

    def test_landing_pages_use_the_first_range_only(self):
        other = {"startDate": "2026-02-01", "endDate": "2026-02-28"}
        bodies = ga4_pull.block_bodies([RANGE, other], None)
        self.assertEqual(bodies["landing_pages"]["dateRanges"], [RANGE])
        self.assertEqual(bodies["channels"]["dateRanges"], [RANGE, other])


class TestPagination(unittest.TestCase):
    def test_all_pages_are_read(self):
        pages = []

        def run_report(prop, token, body):
            pages.append(body.get("offset", 0))
            start = body.get("offset", 0)
            rows = [([str(i)], [1]) for i in range(start, min(start + 2, 5))]
            resp = response(["date"], ["sessions"], rows)
            resp["rowCount"] = 5
            return resp

        with mock.patch.object(ga4_pull, "run_report", run_report):
            resp = ga4_pull.run_report_all("1", "t", {"limit": 2})
        self.assertEqual(len(resp["rows"]), 5)
        self.assertEqual(pages, [0, 2, 4])


def profile_ga4(purchases_on_bot=0):
    """30 Tage: ein Telefon-Profil kauft, ein Desktop-Profil läuft vom 11. bis
    20. in einer Welle und kauft nie."""
    def daily_totals(body):
        return response(["date"], ["sessions"], [([ga4_date(n)], [1_000]) for n in range(30)])

    def daily_profiles(body):
        rows = []
        for n in range(30):
            rows.append(([ga4_date(n), "390x844", "iOS", "mobile", "Safari"], [300, 170, 6]))
            rows.append(([ga4_date(n)] + list(BOT.values()), [600 if 10 <= n < 20 else 20, 30, 0]))
        return response(["date"] + list(bots.PROFILE_DIMENSIONS),
                        ["sessions", "engagedSessions", "ecommercePurchases"], rows)

    def verification(body):
        return response(["sessionDefaultChannelGroup"],
                        ["sessions", "engagedSessions", "ecommercePurchases", "totalUsers"],
                        [(["Direct"], [5_500, 800, purchases_on_bot, 5_400]),
                         (["Unassigned"], [900, 100, 0, 890])],
                        totals=[6_400, 900, purchases_on_bot, 6_300])

    return FakeGA4({("date",): daily_totals,
                    ("date",) + bots.PROFILE_DIMENSIONS: daily_profiles,
                    ("sessionDefaultChannelGroup",): verification})


class TestReadBotProfiles(unittest.TestCase):
    BASE = {"filter": {"fieldName": "country", "inListFilter": {"values": ["X"]}}}

    def read(self, fake, base=None):
        with mock.patch.object(ga4_pull, "run_report", fake):
            return ga4_pull.read_bot_profiles("1", "t", RANGE, 30_000, base)

    def test_the_wave_profile_is_flagged_with_its_window_and_channels(self):
        section = self.read(profile_ga4())
        self.assertTrue(section["checked"])
        self.assertTrue(section["flagged"])
        profile = [p for p in section["profiles"] if p["flagged"]][0]
        self.assertEqual(profile["profile"], BOT)
        self.assertEqual(profile["sessions"], 6_400)
        self.assertEqual(profile["channels"][0]["channel"], "Direct")
        self.assertEqual([(w["start"], w["end"]) for w in profile["windows"]],
                         [("2026-03-11", "2026-03-20")])
        self.assertFalse(section["filter_proposal"]["enabled"])

    def test_the_daily_query_skips_rows_below_the_floor(self):
        fake = profile_ga4()
        self.read(fake)
        body = fake.calls_with("date", *bots.PROFILE_DIMENSIONS)[0]
        numeric = body["metricFilter"]["filter"]["numericFilter"]
        self.assertEqual(numeric["operation"], "GREATER_THAN_OR_EQUAL")
        self.assertEqual(numeric["value"]["int64Value"], str(bots.daily_floor(30_000, 30)))

    def test_the_count_uses_the_profile_and_the_base_filter(self):
        fake = profile_ga4()
        self.read(fake, self.BASE)
        values = filter_values(fake.calls_with("sessionDefaultChannelGroup")[0]["dimensionFilter"])
        self.assertIn(("screenResolution", ("1440x1440",)), values)
        self.assertIn(("country", ("X",)), values)

    def test_purchases_in_the_full_count_clear_the_profile(self):
        """Die Tagesreihe sieht nur Tage über der Schwelle. Kauft das Profil an
        den übrigen, entscheidet die Nachzählung."""
        section = self.read(profile_ga4(purchases_on_bot=40))
        self.assertFalse(section["flagged"])
        self.assertIsNone(section["filter_proposal"])

    def test_a_failing_query_leaves_a_note_instead_of_an_abort(self):
        fake = mock.Mock(side_effect=http_error(403, "User does not have access"))
        section = self.read(fake)
        self.assertFalse(section["checked"])
        self.assertFalse(section["flagged"])
        self.assertIn("User does not have access", section["note"])


def sender_ga4(app_name_registered=True):
    """30 Tage, ab dem 11. schickt ein Pixel view_item und purchase ein zweites Mal."""
    def events(body):
        rows = []
        for n in range(30):
            second = n >= 10
            rows.append(([ga4_date(n), "7", "view_item"], [1_700 if second else 1_000, 620 if second else 600]))
            rows.append(([ga4_date(n), "7", "purchase"], [85 if second else 50, 52 if second else 50]))
        return response(["date", "streamId", "eventName"], ["eventCount", "sessions"], rows)

    def signatures(body):
        dims = [d["name"] for d in body["dimensions"]]
        if "customEvent:app_name" in dims and not app_name_registered:
            raise http_error(400, "Field customEvent:app_name is not a valid dimension.")
        rows = []
        for n in range(30):
            second = n >= 10
            found = [("view_item", "Shopify Online Store", "shop.example", 1_000, 600),
                     ("purchase", "Shopify Online Store", "(not set)", 50, 50)]
            if second:
                found += [("view_item", "(not set)", "shop.example", 700, 500),
                          ("purchase", "(not set)", "shop.example", 35, 35)]
            for event, app, host, count, sessions in found:
                values = {"date": ga4_date(n), "streamId": "7", "eventName": event,
                          "customEvent:app_name": app, "hostName": host}
                rows.append(([values[d] for d in dims], [count, sessions]))
        return response(dims, ["eventCount", "sessions"], rows)

    def items(body):
        return response(["itemId"], ["itemsViewed", "itemsAddedToCart", "itemsCheckedOut",
                                     "itemsPurchased"],
                        [(["1234567890123"], [30_000, 900, 400, 150]),
                         (["shopify_DE_1234567890123_1234567890124"], [14_000, 300, 200, 70])])

    handlers = {("date", "streamId", "eventName"): events,
                ("date", "streamId", "eventName", "customEvent:app_name", "hostName"): signatures,
                ("date", "streamId", "eventName", "hostName"): signatures,
                ("itemId",): items}
    return FakeGA4(handlers)


class TestReadSenders(unittest.TestCase):
    def read(self, fake, streams=None):
        with mock.patch.object(ga4_pull, "run_report", fake):
            return ga4_pull.read_senders("1", "t", RANGE, None, streams)

    def test_double_counting_is_found_on_every_stage(self):
        section = self.read(sender_ga4())
        self.assertEqual(section["double_counted_events"], ["view_item", "purchase"])
        self.assertEqual(section["onset"], "2026-03-11")
        self.assertTrue(section["item_ids"]["multiple_formats"])

    def test_the_stream_names_its_measurement_id(self):
        section = self.read(sender_ga4(), [{"stream_id": "7", "measurement_id": "G-TEST"}])
        self.assertEqual(section["streams"][0]["measurement_id"], "G-TEST")

    def test_an_unregistered_app_name_falls_back_to_the_host_name(self):
        fake = sender_ga4(app_name_registered=False)
        section = self.read(fake)
        self.assertEqual(section["double_counted_events"], ["purchase"])
        self.assertTrue(any("app_name" in note for note in section["notes"]))
        self.assertEqual(len(fake.calls_with("date", "streamId", "eventName", "hostName")), 1)

    def test_a_failing_query_leaves_a_note_instead_of_an_abort(self):
        section = self.read(mock.Mock(side_effect=http_error(403, "no access")))
        self.assertFalse(section["measurable"])
        self.assertIn("no access", section["note"])


class TestPrimarySenderFilters(unittest.TestCase):
    PRIMARY = {"stream_id": "7", "signatures": {
        "purchase": {"app_name": "set", "host_name": "(not set)"},
        "view_item": {"app_name": "set", "host_name": "set"}}}

    def test_a_server_side_signature_asks_for_a_missing_host_and_a_set_app_name(self):
        expr = ga4_pull.signature_expression(self.PRIMARY["signatures"]["purchase"])
        host, app = expr["andGroup"]["expressions"]
        self.assertEqual(host["filter"]["fieldName"], "hostName")
        self.assertEqual(host["filter"]["stringFilter"]["value"], "(not set)")
        self.assertEqual(app["notExpression"]["filter"]["fieldName"], "customEvent:app_name")

    def test_without_app_name_only_the_host_filters(self):
        expr = ga4_pull.signature_expression({"app_name": None, "host_name": "set"})
        self.assertEqual(expr["notExpression"]["filter"]["fieldName"], "hostName")

    def test_the_funnel_filter_covers_every_stage(self):
        flt = ga4_pull.primary_funnel_filter(self.PRIMARY)
        events = [v[0] for f, v in filter_values(flt) if f == "eventName"]
        self.assertEqual(events, ga4_pull.FUNNEL_EVENTS)

    def test_other_streams_are_left_untouched(self):
        flt = ga4_pull.primary_funnel_filter(self.PRIMARY)
        self.assertIn(("streamId", ("7",)), filter_values(flt))
        self.assertIn('"notExpression": {"filter": {"fieldName": "streamId"',
                      json.dumps(flt))

    def test_purchases_by_channel_and_device_come_from_the_primary_sender(self):
        calls = []

        def run_report(prop, token, body):
            calls.append(body)
            dim = body["dimensions"][0]["name"]
            if dim == "eventName":
                return response(["eventName"], ["eventCount", "sessions"],
                                [(["view_item"], [1_000, 600]), (["purchase"], [50, 50])])
            return response([dim], ["ecommercePurchases", "purchaseRevenue"],
                            [(["Direct" if dim == "sessionDefaultChannelGroup" else "mobile"],
                              [40, 1234.5])])

        with mock.patch.object(ga4_pull, "run_report", run_report):
            block = ga4_pull.read_primary_sender("1", "t", RANGE, None, self.PRIMARY)
        self.assertEqual(block["funnel"]["purchase"], {"events": 50, "sessions": 50})
        self.assertEqual(block["funnel"]["add_to_cart"], {"events": 0, "sessions": 0})
        self.assertEqual(block["channels"], [{"channel": "Direct", "purchases": 40,
                                              "purchase_revenue": 1234.5}])
        self.assertEqual(block["devices"][0]["device"], "mobile")
        metrics = {m["name"] for b in calls[1:] for m in b["metrics"]}
        self.assertNotIn("transactions", metrics)


class TestStreams(unittest.TestCase):
    def test_stream_ids_come_from_the_resource_name(self):
        payload = {"dataStreams": [
            {"name": "properties/1/dataStreams/77", "webStreamData": {"measurementId": "G-A"}},
            {"name": "properties/1/dataStreams/78"}]}
        self.assertEqual(ga4_pull.parse_streams(payload),
                         [{"stream_id": "77", "measurement_id": "G-A"},
                          {"stream_id": "78", "measurement_id": None}])


if __name__ == "__main__":
    unittest.main()
