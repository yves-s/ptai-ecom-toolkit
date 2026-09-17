"""Shop-Technik-Snapshot: CLI-Antwort plus die Fremdtechnik aus dem Crawl."""
import sys
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
sys.path.insert(0, str(SKILLS / "pull-shopify-tech" / "scripts"))
import shop_tech_build  # noqa: E402


class TestScriptHosts(unittest.TestCase):
    def test_reads_the_findings_index(self):
        # Der Index ist die kleine Form. pages[] ist bei 300 Seiten 2,7 MB.
        crawl = {"findings_index": {"script_hosts": {"connect.example": 300}},
                 "pages": []}
        self.assertEqual(shop_tech_build.script_hosts(crawl), {"connect.example": 300})

    def test_falls_back_to_pages_for_older_crawls(self):
        # Das Feld heißt script_sources, nicht scripts. Ein Crawl aus der Zeit
        # vor dem Index hat keinen findings_index.
        crawl = {"pages": [
            {"script_sources": ["https://a.example/1.js", "https://b.example/2.js"]},
            {"script_sources": ["https://a.example/1.js"]}]}
        self.assertEqual(shop_tech_build.script_hosts(crawl), {"a.example": 2, "b.example": 1})

    def test_relative_paths_are_ignored(self):
        crawl = {"pages": [{"script_sources": ["/theme.js", "", None]}]}
        self.assertEqual(shop_tech_build.script_hosts(crawl), {})

    def test_missing_crawl_is_not_an_error(self):
        # Der Crawl kann in diesem Lauf ausgefallen sein. Dann fehlt der
        # Storefront-Teil, der Rest des Snapshots bleibt gültig.
        self.assertEqual(shop_tech_build.script_hosts(None), {})


class TestInlineTagIds(unittest.TestCase):
    def test_reads_the_findings_index(self):
        crawl = {"findings_index": {"inline_tag_ids": {"GTM-ABC": 300, "G-XYZ": 300}}}
        self.assertEqual(shop_tech_build.inline_tag_ids(crawl),
                         {"GTM-ABC": 300, "G-XYZ": 300})

    def test_falls_back_to_pages(self):
        crawl = {"pages": [{"inline_tag_ids": ["G-XYZ"]},
                            {"inline_tag_ids": ["G-XYZ", "GTM-ABC"]}]}
        self.assertEqual(shop_tech_build.inline_tag_ids(crawl), {"G-XYZ": 2, "GTM-ABC": 1})

    def test_two_measurement_ids_stay_visible_as_a_pair(self):
        # Zwei GA4-IDs auf denselben Seiten heißen doppelte Messung. Ohne die
        # Seitenzahl je ID ist das aus dem Snapshot nicht zu erkennen.
        crawl = {"findings_index": {"inline_tag_ids": {"G-AAA": 300, "G-BBB": 300}}}
        self.assertEqual(len(shop_tech_build.inline_tag_ids(crawl)), 2)


class TestTruncation(unittest.TestCase):
    def test_host_list_is_capped_and_marked(self):
        # Eine gekappte Liste, die sich nicht als gekappt zu erkennen gibt,
        # erzeugt eine falsche Zahl: der Leser hält 100 für alles.
        hosts = {f"h{i}.example": 300 for i in range(shop_tech_build.MAX_HOSTS + 5)}
        built = shop_tech_build.build({}, {"findings_index": {"script_hosts": hosts}})
        self.assertEqual(len(built["storefront_script_hosts"]), shop_tech_build.MAX_HOSTS)
        self.assertTrue(built["storefront_script_hosts_truncated"])
        # Der Zähler nennt die volle Menge, nicht die gekappte.
        self.assertEqual(built["summary"]["third_party_script_hosts"],
                         shop_tech_build.MAX_HOSTS + 5)

    def test_short_list_is_not_marked(self):
        built = shop_tech_build.build({}, {"findings_index": {"script_hosts": {"a.example": 1}}})
        self.assertFalse(built["storefront_script_hosts_truncated"])


class TestBuild(unittest.TestCase):
    def test_reads_theme_name_and_role(self):
        answer = {"data": {"themes": {"nodes": [
            {"name": "Dawn", "role": "MAIN", "updatedAt": "2026-08-01T10:00:00Z"},
            {"name": "Alt", "role": "UNPUBLISHED", "updatedAt": "2025-01-01T10:00:00Z"}]}}}
        built = shop_tech_build.build(answer, None)
        self.assertEqual(built["theme"]["name"], "Dawn")
        self.assertEqual(built["summary"]["themes_total"], 2)

    def test_missing_block_becomes_a_note_not_a_zero(self):
        # Ein fehlender Scope liefert null statt eines Fehlers. Ohne Vermerk
        # läse die Analyse "keine Skript-Tags installiert".
        built = shop_tech_build.build({"data": {"themes": None}}, None)
        self.assertIsNone(built["theme"])
        self.assertIn("themes", " ".join(built["notes"]))

    def test_present_but_empty_block_is_no_note(self):
        # Leer ist eine Aussage, fehlend ist keine.
        built = shop_tech_build.build({"data": {"scriptTags": {"nodes": []}}}, None)
        self.assertEqual(built["summary"]["script_tags_total"], 0)
        self.assertNotIn("scriptTags", " ".join(built["notes"]))

    def test_counts_locales_and_markets(self):
        answer = {"data": {
            "shopLocales": [{"locale": "de", "primary": True},
                             {"locale": "en", "primary": False}],
            "markets": {"nodes": [{"name": "DE", "enabled": True}]}}}
        summary = shop_tech_build.build(answer, None)["summary"]
        self.assertEqual(summary["locales_total"], 2)
        self.assertEqual(summary["markets_total"], 1)

    def test_crawl_pages_scanned_is_none_without_a_crawl(self):
        # 0 hieße "gecrawlt und nichts gefunden", None heißt "nicht gemessen".
        self.assertIsNone(shop_tech_build.build({}, None)["summary"]["crawl_pages_scanned"])

    def test_crawl_pages_scanned_from_the_summary(self):
        crawl = {"summary": {"pages_crawled": 300}, "pages": []}
        self.assertEqual(shop_tech_build.build({}, crawl)["summary"]["crawl_pages_scanned"], 300)

    def test_storefront_parts_land_in_the_snapshot(self):
        crawl = {"findings_index": {"script_hosts": {"a.example": 5},
                                     "inline_tag_ids": {"G-X": 5}},
                 "summary": {"pages_crawled": 5}}
        built = shop_tech_build.build({}, crawl)
        self.assertEqual(built["storefront_script_hosts"], {"a.example": 5})
        self.assertEqual(built["storefront_inline_tag_ids"], {"G-X": 5})
        self.assertEqual(built["summary"]["third_party_script_hosts"], 1)
        self.assertEqual(built["summary"]["inline_tag_ids"], 1)


if __name__ == "__main__":
    unittest.main()
