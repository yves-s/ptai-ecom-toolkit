"""Der Befund-Index des Crawls.

Er existiert, weil `crawl.json > pages` bei einem größeren Shop nicht mehr in
das Kontextfenster des Analyse-Agents passt (gemessen rund 1750 Token je
Seite). Der Index trägt je Befundklasse die **echte** Anzahl plus eine
begrenzte Beispielliste, damit der Agent aus ihm arbeiten kann, statt die
Seitenliste zu lesen.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "skills" / "crawl-site" / "scripts"))
import crawl  # noqa: E402


def page(url, **kw):
    """Eine erfolgreich geparste Seite. `indexable` markiert sie als solche."""
    base = {"url": url, "status": 200, "indexable": True, "click_depth": 1,
            "title": "", "canonical": url, "canonical_count": 1,
            "schema_types": [], "internal_links": []}
    base.update(kw)
    return base


class TestCounts(unittest.TestCase):
    def test_count_is_the_true_number_not_the_length_of_the_examples(self):
        pages = [page(f"https://s.de/p/{i}", click_depth=None) for i in range(80)]
        idx = crawl.build_findings_index(pages, cap=25)
        self.assertEqual(idx["orphans"]["count"], 80)
        self.assertEqual(len(idx["orphans"]["examples"]), 25)

    def test_the_cap_is_written_into_the_file(self):
        self.assertEqual(crawl.build_findings_index([], cap=7)["cap"], 7)

    def test_an_empty_crawl_yields_zeros_not_none(self):
        idx = crawl.build_findings_index([])
        self.assertEqual(idx["orphans"]["count"], 0)
        self.assertEqual(idx["errors"]["count"], 0)
        self.assertEqual(idx["duplicate_titles"]["count"], 0)


class TestOrphans(unittest.TestCase):
    def test_only_pages_without_a_click_depth_count(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", click_depth=None),
            page("https://s.de/b", click_depth=0),
            page("https://s.de/c", click_depth=3),
        ])
        self.assertEqual(idx["orphans"]["count"], 1)
        self.assertEqual(idx["orphans"]["examples"], ["https://s.de/a"])

    def test_depth_zero_is_not_an_orphan(self):
        # Die Startseite hat Klicktiefe 0. Ein naiver Falsy-Test würde sie
        # als verwaist melden.
        idx = crawl.build_findings_index([page("https://s.de/", click_depth=0)])
        self.assertEqual(idx["orphans"]["count"], 0)


class TestErrors(unittest.TestCase):
    def test_non_2xx_and_error_entries_are_collected(self):
        idx = crawl.build_findings_index([
            page("https://s.de/ok"),
            {"url": "https://s.de/404", "status": 404},
            {"url": "https://s.de/500", "status": 500},
            {"url": "https://s.de/dead", "status": None, "error": "timeout"},
        ])
        self.assertEqual(idx["errors"]["count"], 3)
        self.assertEqual(idx["errors"]["by_status"], {"404": 1, "500": 1, "error": 1})

    def test_a_redirect_is_not_an_error(self):
        # 301 ist ein Befund für die Weiterleitungskette, kein Fehlerstatus.
        idx = crawl.build_findings_index([{"url": "https://s.de/r", "status": 301}])
        self.assertEqual(idx["errors"]["count"], 0)


class TestCanonicals(unittest.TestCase):
    def test_more_than_one_canonical_tag_is_collected(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", canonical_count=2),
            page("https://s.de/b", canonical_count=1),
        ])
        self.assertEqual(idx["multiple_canonicals"]["count"], 1)

    def test_canonical_pointing_elsewhere_is_collected(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", canonical="https://s.de/b"),
        ])
        self.assertEqual(idx["canonical_mismatch"]["count"], 1)

    def test_the_comparison_uses_the_end_url_after_a_redirect(self):
        # Nach einer Weiterleitung ist end_url die Seite. Gegen url zu
        # vergleichen würde jede weitergeleitete Seite falsch melden.
        idx = crawl.build_findings_index([
            page("https://s.de/a", end_url="https://s.de/a/", canonical="https://s.de/a/"),
        ])
        self.assertEqual(idx["canonical_mismatch"]["count"], 0)

    def test_a_page_without_a_canonical_is_not_a_mismatch(self):
        idx = crawl.build_findings_index([page("https://s.de/a", canonical=None)])
        self.assertEqual(idx["canonical_mismatch"]["count"], 0)


class TestDuplicateTitles(unittest.TestCase):
    def test_only_titles_appearing_more_than_once_are_grouped(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", title="Ohrstecker"),
            page("https://s.de/b", title="Ohrstecker"),
            page("https://s.de/c", title="Kette"),
        ])
        self.assertEqual(idx["duplicate_titles"]["count"], 1)
        group = idx["duplicate_titles"]["groups"][0]
        self.assertEqual(group["title"], "Ohrstecker")
        self.assertEqual(group["count"], 2)

    def test_pages_without_a_title_are_not_one_big_duplicate_group(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", title=""),
            page("https://s.de/b", title=None),
        ])
        self.assertEqual(idx["duplicate_titles"]["count"], 0)

    def test_the_largest_group_comes_first(self):
        pages = ([page(f"https://s.de/a{i}", title="Viele") for i in range(5)]
                 + [page(f"https://s.de/b{i}", title="Wenige") for i in range(2)])
        groups = crawl.build_findings_index(pages)["duplicate_titles"]["groups"]
        self.assertEqual([g["title"] for g in groups], ["Viele", "Wenige"])


class TestParameterUrls(unittest.TestCase):
    def test_urls_with_a_query_string_are_counted(self):
        idx = crawl.build_findings_index([
            page("https://s.de/c/ringe"),
            page("https://s.de/c/ringe?sort=price"),
        ])
        self.assertEqual(idx["parameter_urls"]["count"], 1)

    def test_indexable_parameter_urls_without_a_consolidating_canonical(self):
        idx = crawl.build_findings_index([
            # zeigt auf sich selbst, konsolidiert also nicht
            page("https://s.de/c?sort=price", canonical="https://s.de/c?sort=price"),
            # zeigt auf die parameterfreie Variante, das ist richtig
            page("https://s.de/c?sort=name", canonical="https://s.de/c"),
            # nicht indexierbar, damit kein Befund
            page("https://s.de/c?sort=x", canonical="https://s.de/c?sort=x", indexable=False),
        ])
        self.assertEqual(idx["parameter_urls"]["count"], 3)
        self.assertEqual(idx["parameter_urls"]["indexable"], 2)
        self.assertEqual(idx["parameter_urls"]["without_consolidating_canonical"], 1)


class TestDepthAndTypes(unittest.TestCase):
    def test_the_deepest_pages_come_first(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", click_depth=2),
            page("https://s.de/b", click_depth=5),
            page("https://s.de/c", click_depth=None),
        ])
        self.assertEqual(idx["deepest"][0], {"url": "https://s.de/b", "click_depth": 5})

    def test_schema_types_are_counted_over_all_pages(self):
        idx = crawl.build_findings_index([
            page("https://s.de/p/1", schema_types=["Product", "BreadcrumbList"]),
            page("https://s.de/p/2", schema_types=["Product"]),
        ])
        self.assertEqual(idx["schema_types"], {"Product": 2, "BreadcrumbList": 1})

    def test_pages_without_any_schema_are_counted(self):
        idx = crawl.build_findings_index([
            page("https://s.de/a", schema_types=[]),
            page("https://s.de/b", schema_types=["Product"]),
        ])
        self.assertEqual(idx["pages_without_schema"]["count"], 1)

    def test_the_first_path_segment_groups_the_page_types(self):
        idx = crawl.build_findings_index([
            page("https://s.de/products/a"),
            page("https://s.de/products/b"),
            page("https://s.de/collections/c"),
            page("https://s.de/"),
        ])
        self.assertEqual(idx["path_prefixes"],
                         {"/products/": 2, "/collections/": 1, "/": 1})


if __name__ == "__main__":
    unittest.main()


class TestInlineTagIds(unittest.TestCase):
    """Inline eingebaute Container-IDs, die in script_sources nie auftauchen."""

    HTML = """<html><head>
      <script src="https://cdn.example/app.js"></script>
      <script>window.dataLayer=window.dataLayer||[];gtag('config','G-AAAAAAAAAA');</script>
      <script>gtag('config','G-BBBBBBBBBB');gtag('config','AW-123456789');</script>
      <script>(function(w,d){})(window,document);// GTM-ABCD123
      </script>
    </head><body><h1>Titel</h1></body></html>"""

    def test_inline_ids_are_found(self):
        page = crawl.parse_page(self.HTML, "https://beispielshop.de/")
        self.assertEqual(
            page["inline_tag_ids"],
            ["AW-123456789", "G-AAAAAAAAAA", "G-BBBBBBBBBB", "GTM-ABCD123"])

    def test_the_src_attribute_stays_in_script_sources(self):
        page = crawl.parse_page(self.HTML, "https://beispielshop.de/")
        self.assertIn("https://cdn.example/app.js", page["script_sources"])

    def test_a_page_without_inline_ids_stays_empty(self):
        page = crawl.parse_page("<html><body><h1>x</h1></body></html>",
                                "https://beispielshop.de/")
        self.assertEqual(page["inline_tag_ids"], [])

    def test_two_ga4_ids_on_the_same_pages_are_countable(self):
        # Genau der Fall, den die Kernfrage "doppelte Tags" sucht und der aus
        # script_sources grundsätzlich nicht sichtbar ist.
        pages = []
        for i in range(3):
            page = crawl.parse_page(self.HTML, f"https://beispielshop.de/{i}")
            page["url"] = f"https://beispielshop.de/{i}"
            page["click_depth"] = 1
            pages.append(page)
        index = crawl.build_findings_index(pages)
        ga4 = [k for k in index["inline_tag_ids"] if k.startswith("G-")]
        self.assertEqual(len(ga4), 2)
        self.assertEqual(index["inline_tag_ids"]["G-AAAAAAAAAA"], 3)


class TestScriptHosts(unittest.TestCase):
    """Fremdskripte als Host-Tabelle im Index. Ohne sie muss jeder Leser
    `pages[]` durchgehen, und das sind bei 300 Seiten 2,7 MB."""

    def test_counts_pages_per_host(self):
        pages = [
            {"url": "https://x.example/", "indexable": True,
             "script_sources": ["https://static.example/a.js",
                                 "https://connect.example/pixel.js"]},
            {"url": "https://x.example/p", "indexable": True,
             "script_sources": ["https://connect.example/pixel.js"]},
        ]
        hosts = crawl._count_script_hosts(pages)
        self.assertEqual(hosts["connect.example"], 2)
        self.assertEqual(hosts["static.example"], 1)

    def test_sorted_by_frequency(self):
        pages = [{"url": "https://x.example/", "indexable": True,
                   "script_sources": ["https://selten.example/a.js"]}]
        pages += [{"url": f"https://x.example/{i}", "indexable": True,
                    "script_sources": ["https://haeufig.example/b.js"]} for i in range(3)]
        self.assertEqual(list(crawl._count_script_hosts(pages))[0], "haeufig.example")

    def test_relative_paths_are_ignored(self):
        # Relative Pfade gehören zum Theme und sagen nichts über Fremdtechnik.
        pages = [{"url": "https://x.example/", "indexable": True,
                   "script_sources": ["/theme.js", "", None]}]
        self.assertEqual(crawl._count_script_hosts(pages), {})

    def test_same_host_twice_on_one_page_counts_once(self):
        # Gezählt werden Seiten, nicht Einbindungen: zwei Snippets desselben
        # Anbieters auf einer Seite sind eine Seite.
        pages = [{"url": "https://x.example/", "indexable": True,
                   "script_sources": ["https://a.example/1.js", "https://a.example/2.js"]}]
        self.assertEqual(crawl._count_script_hosts(pages), {"a.example": 1})

    def test_index_carries_the_hosts(self):
        pages = [{"url": "https://x.example/", "indexable": True, "click_depth": 0,
                   "status": 200, "script_sources": ["https://a.example/1.js"]}]
        self.assertEqual(crawl.build_findings_index(pages)["script_hosts"], {"a.example": 1})
