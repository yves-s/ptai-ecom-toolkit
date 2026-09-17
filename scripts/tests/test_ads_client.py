"""Der Google-Ads-Client: Header, Paging, Micros, Fehler.

Kein Test ruft die API: das Entwicklertoken existiert zum Zeitpunkt dieser
Tests nicht. Die Fixtures sind von Hand aus der REST-Referenz gebaut, siehe
fixtures/ads/HERKUNFT.md. Sie beweisen, dass der Code die dokumentierte
Struktur richtig liest, nicht dass die echte Antwort so aussieht.
"""
import json
import unittest
import urllib.error
from pathlib import Path

import ads_client

FIX = Path(__file__).parent / "fixtures" / "ads"


def pages(*names):
    """Ein Transport, der die Fixtures der Reihe nach liefert."""
    queue = [(FIX / name).read_bytes() for name in names]
    seen = []

    def transport(url, headers, body, timeout):
        seen.append({"url": url, "headers": headers, "body": json.loads(body)})
        return queue.pop(0)

    return transport, seen


class TestHeaders(unittest.TestCase):
    def test_developer_token_and_bearer_are_sent(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("TOKEN", "1234567890", access_token="ya29.x",
                           transport=transport).search("SELECT campaign.id FROM campaign")
        self.assertEqual(seen[0]["headers"]["developer-token"], "TOKEN")
        self.assertEqual(seen[0]["headers"]["Authorization"], "Bearer ya29.x")

    def test_login_customer_id_is_omitted_when_not_given(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", transport=transport).search("q")
        self.assertNotIn("login-customer-id", seen[0]["headers"])

    def test_login_customer_id_is_sent_when_given(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", login_customer_id="999-888-7777",
                           transport=transport).search("q")
        self.assertEqual(seen[0]["headers"]["login-customer-id"], "9998887777")

    def test_customer_id_dashes_are_stripped(self):
        # Google Ads zeigt die Kundennummer mit Bindestrichen an, die API
        # nimmt sie nicht. Ein Copy-Paste aus der Oberfläche scheiterte sonst
        # mit einer nichtssagenden 400.
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123-456-7890", access_token="a",
                           transport=transport).search("q")
        self.assertIn("/customers/1234567890/", seen[0]["url"])

    def test_url_carries_the_api_version(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", version="v21",
                           transport=transport).search("q")
        self.assertIn("/v21/", seen[0]["url"])

    def test_default_version_is_a_constant_not_a_guess(self):
        # Google stellt Versionen nach rund einem Jahr ab. Der Wert steht als
        # Konstante und ist per Schalter uebersteuerbar.
        self.assertRegex(ads_client.DEFAULT_VERSION, r"^v\d+$")


class TestPaging(unittest.TestCase):
    def test_follows_the_next_page_token(self):
        transport, seen = pages("campaigns_page1.json", "campaigns_page2.json")
        rows = ads_client.Client("T", "123", access_token="a",
                                  transport=transport).search("SELECT campaign.id FROM campaign")
        self.assertEqual(len(rows), 3)
        self.assertEqual(seen[1]["body"]["pageToken"], "PAGE2")

    def test_repeats_the_identical_query_on_the_next_page(self):
        # Die API verlangt dieselbe Query zum Token, sonst antwortet sie mit
        # einem Fehler statt mit der naechsten Seite.
        transport, seen = pages("campaigns_page1.json", "campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", transport=transport).search("Q")
        self.assertEqual(seen[0]["body"]["query"], seen[1]["body"]["query"])

    def test_first_page_carries_no_token(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", transport=transport).search("q")
        self.assertNotIn("pageToken", seen[0]["body"])

    def test_stops_without_a_token(self):
        transport, seen = pages("campaigns_page2.json")
        ads_client.Client("T", "123", access_token="a", transport=transport).search("q")
        self.assertEqual(len(seen), 1)


class TestValues(unittest.TestCase):
    def test_micros_become_currency_units(self):
        self.assertAlmostEqual(ads_client.from_micros("450000000"), 450.0)

    def test_micros_none_stays_none(self):
        # 0 und "kein Wert" sind zwei Aussagen. Eine 0 stuende im Report als
        # "nichts ausgegeben".
        self.assertIsNone(ads_client.from_micros(None))

    def test_micros_are_rounded_to_cents(self):
        self.assertAlmostEqual(ads_client.from_micros("1234567"), 1.23)

    def test_micros_zero_is_zero_not_none(self):
        self.assertEqual(ads_client.from_micros("0"), 0.0)

    def test_unreadable_micros_are_none_not_zero(self):
        self.assertIsNone(ads_client.from_micros("keine Zahl"))


class TestErrors(unittest.TestCase):
    def test_transport_failure_is_wrapped(self):
        def failing(url, headers, body, timeout):
            raise OSError("connection reset")
        with self.assertRaises(ads_client.AdsError) as caught:
            ads_client.Client("T", "123", access_token="a", transport=failing).search("q")
        self.assertIn("connection reset", str(caught.exception))

    def test_invalid_json_is_wrapped(self):
        def broken(url, headers, body, timeout):
            return b"not json"
        with self.assertRaises(ads_client.AdsError):
            ads_client.Client("T", "123", access_token="a", transport=broken).search("q")

    def test_http_error_carries_the_code(self):
        def failing(url, headers, body, timeout):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        with self.assertRaises(ads_client.AdsError) as caught:
            ads_client.Client("T", "123", access_token="a", transport=failing).search("q")
        self.assertIn("401", str(caught.exception))

    def test_missing_developer_token_is_named(self):
        with self.assertRaises(ValueError) as caught:
            ads_client.Client("", "123", access_token="a")
        self.assertIn("PTAI_GOOGLE_ADS_TOKEN", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
