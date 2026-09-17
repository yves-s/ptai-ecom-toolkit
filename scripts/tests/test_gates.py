"""Die Sperren vor dem Einfrieren eines Blocks."""
import unittest

from audit import gates


class TestPriceTestSignals(unittest.TestCase):
    def test_known_tool_in_the_inline_tags_is_a_signal(self):
        crawl = {"findings_index": {"inline_tag_ids": {"intelligems-abc123": 312}}}
        signals = gates.price_test_signals(crawl)
        self.assertEqual(len(signals), 1)
        self.assertIn("intelligems", signals[0].lower())
        self.assertIn("312", signals[0])

    def test_known_tool_as_a_script_host_is_a_signal(self):
        crawl = {"findings_index": {"script_hosts": {"cdn.intelligems.io": 300}}}
        self.assertEqual(len(gates.price_test_signals(crawl)), 1)

    def test_unrelated_tags_are_no_signal(self):
        crawl = {"findings_index": {"inline_tag_ids": {"G-ABC": 300, "GTM-XYZ": 300}}}
        self.assertEqual(gates.price_test_signals(crawl), [])

    def test_missing_crawl_is_no_signal_and_no_crash(self):
        self.assertEqual(gates.price_test_signals(None), [])
        self.assertEqual(gates.price_test_signals({}), [])

    def test_match_is_case_insensitive(self):
        crawl = {"findings_index": {"inline_tag_ids": {"Intelligems-XYZ": 5}}}
        self.assertEqual(len(gates.price_test_signals(crawl)), 1)

    def test_falls_back_to_pages_when_the_index_is_missing(self):
        crawl = {"pages": [{"inline_tag_ids": ["intelligems-abc"]}]}
        self.assertEqual(len(gates.price_test_signals(crawl)), 1)


class TestFindingSignals(unittest.TestCase):
    def test_a_price_test_finding_is_a_signal(self):
        # Ein server-seitig ausgespielter Test hinterlässt im Seitenquelltext
        # nichts. Dann ist der Analyse-Befund die einzige Quelle.
        findings = [{"title": "Preistest läuft site-weit",
                     "evidence": "Angebotstest über den gesamten Zeitraum"}]
        self.assertEqual(len(gates.finding_signals(findings)), 1)

    def test_unrelated_findings_are_no_signal(self):
        self.assertEqual(gates.finding_signals([{"title": "Consent-Banner blockt GA4"}]), [])

    def test_no_findings_is_no_signal(self):
        self.assertEqual(gates.finding_signals(None), [])

    def test_verdict_combines_crawl_and_findings(self):
        verdict = gates.price_test_verdict(
            {}, [{"title": "Preistest aktiv", "evidence": "Variante A und B"}])
        self.assertTrue(verdict["running"])

    def test_findings_alone_count_as_checked(self):
        verdict = gates.price_test_verdict(None, [{"title": "nichts Auffälliges"}])
        self.assertTrue(verdict["checked"])


class TestVerdict(unittest.TestCase):
    def test_verdict_without_signals_is_not_running(self):
        verdict = gates.price_test_verdict({})
        self.assertFalse(verdict["running"])
        self.assertTrue(verdict["checked"])
        self.assertIn("kein bekanntes", verdict["evidence"].lower())

    def test_verdict_with_signals_is_running_and_names_them(self):
        crawl = {"findings_index": {"inline_tag_ids": {"intelligems-abc": 312}}}
        verdict = gates.price_test_verdict(crawl)
        self.assertTrue(verdict["running"])
        self.assertIn("intelligems", verdict["evidence"].lower())

    def test_verdict_says_the_check_is_not_proof_of_absence(self):
        # Ein negativer Befund heißt "kein bekanntes Werkzeug gefunden", nicht
        # "kein Preistest". Steht das nicht im Beleg, liest der nächste Leser
        # eine Sicherheit, die die Prüfung nicht hergibt.
        self.assertIn("bekannt", gates.price_test_verdict({})["evidence"].lower())

    def test_verdict_without_a_crawl_is_not_checked(self):
        # Ohne Crawl wurde nicht geprüft. Das ist etwas anderes als "nichts
        # gefunden", und der Conversion-Block darf darauf nicht bauen.
        verdict = gates.price_test_verdict(None)
        self.assertFalse(verdict["checked"])
        self.assertFalse(verdict["running"])


if __name__ == "__main__":
    unittest.main()
