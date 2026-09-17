"""Mehrere Absender je GA4-Mess-ID erkennen: was anschlagen muss, was nicht."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit import senders  # noqa: E402

APP = "Shopify Online Store"
HOST = "shop.example"
NOT_SET = "(not set)"


def day(n):
    return (date(2026, 3, 1) + timedelta(days=n)).isoformat()


class Stream:
    """Baut Tageszeilen, wie der Pull sie liefert: je Tag und Ereignis eine
    Gesamtzeile und je Absender-Merkmal eine Zeile."""

    def __init__(self, stream_id="1"):
        self.stream_id = stream_id
        self.totals = {}
        self.signatures = []

    def add(self, n, event, app_name, host_name, events, sessions):
        self.signatures.append({"date": day(n), "stream_id": self.stream_id, "event": event,
                                "app_name": app_name, "host_name": host_name,
                                "events": events, "sessions": sessions})

    def total(self, n, event, events, sessions):
        self.totals[(n, event)] = {"date": day(n), "stream_id": self.stream_id, "event": event,
                                   "events": events, "sessions": sessions}

    def event_rows(self):
        return list(self.totals.values())


def doubled(stream_id="1", onset=20, days=40):
    """Ein clientseitiger und ein serverseitiger Absender, ab `onset` kommt
    ein Web-Pixel dazu, das dieselben Besuche noch einmal meldet."""
    s = Stream(stream_id)
    for n in range(days):
        second = n >= onset
        s.add(n, "view_item", APP, HOST, 1_000, 600)
        if second:
            s.add(n, "view_item", NOT_SET, HOST, 700, 500)
        s.total(n, "view_item", 1_700 if second else 1_000, 620 if second else 600)
        s.add(n, "purchase", APP, NOT_SET, 50, 50)
        if second:
            s.add(n, "purchase", NOT_SET, HOST, 35, 35)
        s.total(n, "purchase", 85 if second else 50, 52 if second else 50)
        s.add(n, "view_cart", APP, HOST, 200, 150)
        s.total(n, "view_cart", 200, 150)
    return s


def analyze(*streams):
    return senders.analyze([r for s in streams for r in s.event_rows()],
                           [r for s in streams for r in s.signatures])


def event_of(section, event, stream_id="1"):
    stream = [s for s in section["streams"] if s["stream_id"] == stream_id][0]
    return stream["events"][event]


class TestDoubleCounting(unittest.TestCase):
    def test_a_second_sender_in_the_same_sessions_is_double_counting(self):
        r = analyze(doubled())
        view_item = event_of(r, "view_item")
        self.assertEqual(view_item["status"], "duplicated")
        self.assertEqual(view_item["onset"], day(20))
        self.assertEqual(view_item["overlap"]["ratio"], 0.96)
        self.assertEqual(view_item["uplift"], 0.7)
        self.assertEqual(r["double_counted_events"], ["view_item", "purchase"])
        self.assertTrue(r["multiple_senders"])

    def test_every_funnel_stage_counts_not_only_purchases(self):
        r = analyze(doubled())
        self.assertEqual(event_of(r, "purchase")["status"], "duplicated")
        self.assertEqual(event_of(r, "view_item")["status"], "duplicated")

    def test_the_first_sender_is_the_primary(self):
        r = analyze(doubled())
        self.assertEqual(event_of(r, "view_item")["primary"],
                         {"app_name": "set", "host_name": "set"})
        self.assertEqual(event_of(r, "purchase")["primary"],
                         {"app_name": "set", "host_name": NOT_SET})
        self.assertEqual(event_of(r, "purchase")["second"],
                         {"app_name": NOT_SET, "host_name": "set"})

    def test_the_onset_is_the_first_day_of_the_second_sender(self):
        self.assertEqual(analyze(doubled(onset=12))["onset"], day(12))

    def test_a_second_sender_with_its_own_sessions_is_not_a_duplicate(self):
        """Bringt der zweite Absender eigene Sitzungen mit, zählt er nicht
        dieselben Besuche doppelt. Ein Absender allein ist es trotzdem nicht."""
        s = Stream()
        for n in range(40):
            second = n >= 20
            s.add(n, "add_to_cart", NOT_SET, NOT_SET, 100, 90)
            if second:
                s.add(n, "add_to_cart", NOT_SET, HOST, 80, 80)
            s.total(n, "add_to_cart", 180 if second else 100, 165 if second else 90)
        r = analyze(s)
        self.assertEqual(event_of(r, "add_to_cart")["status"], "separate_sessions")
        self.assertEqual(r["double_counted_events"], [])
        self.assertTrue(r["multiple_senders"])


class TestOneSender(unittest.TestCase):
    def test_a_single_sender_is_not_flagged(self):
        r = analyze(doubled())
        view_cart = event_of(r, "view_cart")
        self.assertEqual(view_cart["status"], "single")
        self.assertEqual(len(view_cart["senders"]), 1)

    def test_a_short_blip_is_not_a_sender(self):
        s = Stream()
        for n in range(40):
            blip = 10 <= n < 15
            s.add(n, "view_item", APP, HOST, 1_000, 600)
            if blip:
                s.add(n, "view_item", NOT_SET, HOST, 400, 300)
            s.total(n, "view_item", 1_400 if blip else 1_000, 610 if blip else 600)
        self.assertEqual(event_of(analyze(s), "view_item")["status"], "single")

    def test_a_minor_signature_is_not_a_sender(self):
        """Einzelne Käufe aus einem anderen Verkaufskanal tragen andere
        Merkmale, sind aber kein zweiter Absender."""
        s = Stream()
        for n in range(40):
            s.add(n, "purchase", APP, NOT_SET, 50, 50)
            s.add(n, "purchase", NOT_SET, NOT_SET, 1, 1)
            s.total(n, "purchase", 51, 51)
        r = analyze(s)
        self.assertEqual(event_of(r, "purchase")["status"], "single")
        self.assertFalse(r["multiple_senders"])

    def test_several_shop_domains_are_one_sender(self):
        """Mehrere Domains eines Shops sind kein zweiter Absender."""
        s = Stream()
        for n in range(40):
            s.add(n, "view_item", APP, HOST, 600, 400)
            s.add(n, "view_item", APP, "shop.example.de", 400, 300)
            s.total(n, "view_item", 1_000, 700)
        self.assertEqual(event_of(analyze(s), "view_item")["status"], "single")


class TestWithoutAppName(unittest.TestCase):
    def test_the_host_name_still_separates_a_server_side_sender(self):
        """Ist `customEvent:app_name` in der Property nicht registriert, trennt
        der Hostname weiter serverseitig von clientseitig."""
        s = doubled()
        for row in s.signatures:
            row["app_name"] = None
        r = analyze(s)
        self.assertEqual(event_of(r, "purchase")["status"], "duplicated")
        self.assertEqual(event_of(r, "view_item")["status"], "single")
        self.assertEqual(event_of(r, "purchase")["primary"],
                         {"app_name": None, "host_name": NOT_SET})


class TestStreams(unittest.TestCase):
    def test_every_measurement_id_is_judged_on_its_own(self):
        other = Stream("2")
        for n in range(40):
            other.add(n, "view_item", APP, HOST, 300, 200)
            other.total(n, "view_item", 300, 200)
        r = analyze(doubled("1"), other)
        by_id = {s["stream_id"]: s for s in r["streams"]}
        self.assertTrue(by_id["1"]["multiple_senders"])
        self.assertFalse(by_id["2"]["multiple_senders"])

    def test_without_rows_nothing_is_measurable(self):
        r = senders.analyze([], [])
        self.assertFalse(r["measurable"])
        self.assertFalse(r["multiple_senders"])


class TestPrimarySender(unittest.TestCase):
    def test_the_primary_sender_names_its_stream_and_signatures(self):
        p = senders.primary_sender(analyze(doubled()))
        self.assertEqual(p["stream_id"], "1")
        self.assertEqual(set(p["signatures"]), {"view_item", "purchase"})
        self.assertEqual(p["signatures"]["purchase"], {"app_name": "set", "host_name": NOT_SET})

    def test_without_a_second_sender_there_is_no_primary_block(self):
        s = Stream()
        for n in range(40):
            s.add(n, "view_item", APP, HOST, 1_000, 600)
            s.total(n, "view_item", 1_000, 600)
        self.assertIsNone(senders.primary_sender(analyze(s)))


class TestItemIdFormats(unittest.TestCase):
    def test_item_ids_are_classified_by_format(self):
        cases = {
            "1234567890123": "shopify_id",
            "shopify_DE_1234567890123_1234567890124": "merchant_center_id",
            "shopify_ZZ_undefined_undefined": "merchant_center_id",
            "AB-1234": "other",
            "12345": "other",
            NOT_SET: "not_set",
        }
        for item_id, expected in cases.items():
            with self.subTest(item_id=item_id):
                self.assertEqual(senders.item_id_format(item_id), expected)

    def item(self, item_id, viewed, purchased=0):
        return {"item_id": item_id, "items_viewed": viewed, "items_added_to_cart": 0,
                "items_checked_out": 0, "items_purchased": purchased}

    def test_two_weighty_formats_mean_two_senders(self):
        r = senders.item_formats([self.item("1234567890123", 700),
                                  self.item("shopify_DE_1234567890123_1234567890124", 300)])
        self.assertTrue(r["multiple_formats"])
        self.assertEqual(r["formats"]["shopify_id"]["share"], 0.7)
        self.assertEqual(r["basis"], "items_viewed")

    def test_a_single_format_is_one_sender(self):
        r = senders.item_formats([self.item("1234567890123", 700),
                                  self.item("1234567890124", 300),
                                  self.item("AB-1234", 5)])
        self.assertFalse(r["multiple_formats"])

    def test_without_item_views_the_purchases_decide(self):
        r = senders.item_formats([self.item("1234567890123", 0, 60),
                                  self.item("shopify_DE_1234567890123_1234567890124", 0, 40)])
        self.assertEqual(r["basis"], "items_purchased")
        self.assertTrue(r["multiple_formats"])


if __name__ == "__main__":
    unittest.main()
