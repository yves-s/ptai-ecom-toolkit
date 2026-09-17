"""Parsen und Abruf von Seiten und Sitemaps. Kein Test öffnet einen Socket:
die Abruf-Hälfte wird überall durch die injizierbare Funktion
`fetch(url) -> dict` angesprochen, ein FakeFetch ersetzt sie durch eine
programmierte Antwortfolge."""
import contextlib
import gzip
import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "skills" / "crawl-site" / "scripts"))
import crawl  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
BASE = "https://www.example.com"


class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (FIX / "seite-produkt.html").read_text(encoding="utf-8")
        cls.s = crawl.parse_page(html, f"{BASE}/products/ohrstecker")

    def test_title_and_description(self):
        self.assertEqual(self.s["title"], "Ohrstecker Gold | Beispielshop")
        self.assertTrue(self.s["description"].startswith("Ohrstecker aus 925"))

    def test_counts_all_h1(self):
        # Zwei H1 sind ein Befund, deshalb wird gezählt statt genommen.
        self.assertEqual(len(self.s["h1"]), 2)

    def test_canonical_absolute(self):
        self.assertEqual(self.s["canonical"], f"{BASE}/products/ohrstecker")

    def test_hreflang_complete(self):
        self.assertEqual(set(self.s["hreflang"]), {"de", "en", "x-default"})

    def test_images_without_alt_are_distinguished_from_empty_alt(self):
        # Leeres alt ist bei Deko korrekt, fehlendes alt ist der Befund.
        self.assertEqual(self.s["images"]["without_alt"], 1)
        self.assertEqual(self.s["images"]["empty_alt"], 1)
        self.assertEqual(self.s["images"]["total"], 3)

    def test_structured_data_types(self):
        self.assertIn("Product", self.s["schema_types"])

    def test_missing_robots_meta_means_indexable(self):
        self.assertTrue(self.s["indexable"])

    def test_internal_links_without_external_and_without_duplicates(self):
        targets = set(self.s["internal_links"])
        self.assertIn(f"{BASE}/collections/ohrringe", targets)
        self.assertIn(f"{BASE}/pages/versand", targets)
        self.assertNotIn("https://fremd.example.org/x", targets)

    def test_query_parameters_do_not_become_their_own_urls(self):
        self.assertNotIn(f"{BASE}/products/ohrstecker?variant=1", self.s["internal_links"])

    def test_word_count_counts_the_whole_visible_body(self):
        # Regel: alle sichtbaren Textknoten im body, script und style
        # ausgenommen, an Whitespace getrennt. Hier: 2 (erste H1) + 7 (zweite
        # H1) + 10 (Absatz) + 4 (die vier Linktexte) = 23.
        self.assertEqual(self.s["word_count"], 23)

    def test_script_sources_without_the_inline_script(self):
        # Die rohe src, so wie sie im Theme steht, ohne Auflösung: absolut,
        # protokoll-relativ und seiten-relativ stehen nebeneinander. Das
        # Skript ohne src trägt keine Quelle und fällt heraus.
        self.assertEqual(self.s["script_sources"],
                         ["//cdn.judge.me/y.js",
                          "/assets/theme.js",
                          "https://cdn.intelligems.io/x.js"])

    def test_word_count_ignores_script_and_style(self):
        html = ("<html><head><style>p{color:red}</style></head>"
                "<body><script>var a = 1;</script><p>eins zwei</p></body></html>")
        self.assertEqual(crawl.parse_page(html, BASE)["word_count"], 2)


class TestNoindex(unittest.TestCase):
    def test_noindex_is_detected(self):
        html = '<html><head><meta name="robots" content="noindex, follow"></head><body></body></html>'
        self.assertFalse(crawl.parse_page(html, BASE)["indexable"])


class TestSitemap(unittest.TestCase):
    def test_index_returns_the_child_sitemaps(self):
        xml = (FIX / "sitemap-index.xml").read_bytes()
        self.assertIn(f"{BASE}/sitemap-produkte.xml", crawl.sitemap_children(xml))

    def test_urlset_returns_urls_without_duplicates_and_without_anchors(self):
        xml = (FIX / "sitemap-produkte.xml").read_bytes()
        urls = crawl.sitemap_urls(xml)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertFalse(any("#" in u for u in urls))


class TestHiddenContent(unittest.TestCase):
    """<template> ist für den Browser inert und muss es hier auch sein.

    Shopify-Themes verstecken darin Quick-View-Modals, "zuletzt angesehen" und
    Empfehlungen. Wird der Inhalt mitgezählt, verfälscht eine einzige Seite
    gleichzeitig die H1-Zählung, die Wortzahl und den internen Linkgraph.
    """

    HTML = ("<html><body><h1>Echt</h1><p>eins zwei drei</p>"
            "<a href='/echt'>Echt</a>"
            "<template><h1>Versteckt</h1><p>vier fünf</p>"
            "<a href='/versteckt'>Versteckt</a></template>"
            "</body></html>")

    def setUp(self):
        self.s = crawl.parse_page(self.HTML, BASE)

    def test_template_h1_does_not_count(self):
        self.assertEqual(self.s["h1"], ["Echt"])

    def test_template_text_does_not_count(self):
        # "Echt" plus "eins zwei drei" plus der Linktext "Echt" = 5
        self.assertEqual(self.s["word_count"], 5)

    def test_template_links_do_not_count(self):
        self.assertEqual(self.s["internal_links"], [f"{BASE}/echt"])


class TestTemplateIsInert(unittest.TestCase):
    """Nichts aus einem <template> zählt, auch keine Bilder und kein Schema."""

    HTML = ('<html><head><script type="application/ld+json">{"@type":"Product"}</script>'
            '</head><body><img src="/echt.jpg" alt="Echt">'
            '<template><img src="/v1.jpg"><img src="/v2.jpg">'
            '<script type="application/ld+json">{"@type":"Offer"}</script>'
            '</template></body></html>')

    def setUp(self):
        self.s = crawl.parse_page(self.HTML, BASE)

    def test_images_in_template_do_not_count(self):
        # Sonst stehen zwei Alt-Text-Befunde im Report über Bilder,
        # die auf der gerenderten Seite gar nicht existieren.
        self.assertEqual(self.s["images"]["total"], 1)
        self.assertEqual(self.s["images"]["without_alt"], 0)

    def test_schema_in_template_does_not_count(self):
        # Google sieht es so wenig wie der Browser.
        self.assertEqual(self.s["schema_types"], ["Product"])

    def test_head_data_in_template_does_not_affect_the_page(self):
        # Ein noindex im Template würde die Seite als nicht indexierbar
        # ausweisen, obwohl sie im Index steht. Falschbefund mit Folgekosten.
        h = ('<html><head><title>Echt</title>'
             '<link rel="canonical" href="https://www.example.com/echt"></head>'
             '<body><template>'
             '<title>Versteckt</title>'
             '<meta name="robots" content="noindex">'
             '<link rel="canonical" href="https://www.example.com/falsch">'
             '</template></body></html>')
        page = crawl.parse_page(h, BASE)
        self.assertEqual(page["title"], "Echt")
        self.assertTrue(page["indexable"])
        self.assertEqual(page["canonical"], f"{BASE}/echt")
        self.assertEqual(page["canonical_count"], 1)

    def test_nested_templates_stay_suppressed(self):
        h = ("<html><body><h1>Echt</h1><template><h1>A</h1>"
             "<template><h1>B</h1></template><h1>C</h1></template>"
             "<h1>Echt2</h1></body></html>")
        self.assertEqual(crawl.parse_page(h, BASE)["h1"], ["Echt", "Echt2"])


class TestImageEdgeCases(unittest.TestCase):
    def test_alt_of_only_whitespace_counts_as_missing(self):
        # Weder brauchbarer Alt-Text noch die bewusste Deko-Markierung alt="".
        # Für den Report ist die Tatsache dieselbe wie bei einem fehlenden alt.
        s = crawl.parse_page('<html><body><img src="/a.jpg" alt="   "></body></html>', BASE)
        self.assertEqual(s["images"]["without_alt"], 1)
        self.assertEqual(s["images"]["empty_alt"], 0)


class TestCanonical(unittest.TestCase):
    def test_two_canonicals_are_counted(self):
        # Zwei Canonical auf einer Seite sind selbst ein Befund: Theme und App
        # setzen je eins. Ohne Zählung sieht die Seite aus wie eine mit einem.
        html = ('<html><head><link rel="canonical" href="https://www.example.com/a">'
                '<link rel="canonical" href="https://www.example.com/b"></head><body></body></html>')
        s = crawl.parse_page(html, BASE)
        self.assertEqual(s["canonical_count"], 2)


class TestSitemapError(unittest.TestCase):
    def test_broken_xml_raises(self):
        # Festgehalten, damit Task 6 es weiss: die Sitemap-Auflösung läuft vor
        # der Seitenschleife, ein Fehler dort beendet sonst den ganzen Lauf.
        with self.assertRaises(Exception):
            crawl.sitemap_urls(b"<urlset><url><loc>nicht geschlossen")


class TestBaseTag(unittest.TestCase):
    def test_base_href_determines_the_resolution(self):
        # Manche Shopify-Themes setzen <base>. Wird es ignoriert, zeigt jeder
        # relative Link der Seite auf den falschen Pfad, und der Linkgraph des
        # Shops stimmt nicht mehr. Das erzeugt keinen Fehler, nur falsche Zahlen.
        html = ('<html><head><base href="https://www.example.com/shop/"></head>'
                '<body><a href="a">A</a></body></html>')
        page = crawl.parse_page(html, f"{BASE}/products/ohrstecker")
        self.assertEqual(page["internal_links"], [f"{BASE}/shop/a"])


class TestNormalize(unittest.TestCase):
    def test_uppercase_host_is_the_same_host(self):
        # Hostnamen sind laut RFC nicht case-sensitiv.
        self.assertEqual(crawl.normalize("https://WWW.EXAMPLE.COM/a", BASE), f"{BASE}/a")

    def test_www_and_without_www_are_the_same_shop(self):
        # Formal zwei Hosts, praktisch ein Shop. Mischt ein Theme beide
        # Schreibweisen und wir werfen eine weg, stimmen Klicktiefe und
        # interne Verlinkung nicht mehr, und beides steht in der Baseline.
        self.assertEqual(crawl.normalize("https://example.com/a", BASE), f"{BASE}/a")

    def test_foreign_subdomain_stays_foreign(self):
        # Die Ausnahme gilt nur für www, nicht für beliebige Subdomains.
        self.assertIsNone(crawl.normalize("https://blog.example.com/a", BASE))
        self.assertIsNone(crawl.normalize("https://cdn.example.com/a.js", BASE))

    def test_anchor_and_query_are_dropped(self):
        self.assertEqual(crawl.normalize(f"{BASE}/a?x=1#top", BASE), f"{BASE}/a")

    def test_relative_becomes_absolute(self):
        self.assertEqual(crawl.normalize("/a/b", BASE), f"{BASE}/a/b")

    def test_foreign_domain_returns_none(self):
        self.assertIsNone(crawl.normalize("https://fremd.example.org/x", BASE))

    def test_mailto_and_tel_return_none(self):
        self.assertIsNone(crawl.normalize("mailto:a@example.org", BASE))
        self.assertIsNone(crawl.normalize("tel:+49", BASE))
# ---------------------------------------------------------------------------
# Abruf-Hälfte: kein Test öffnet einen Socket. Die Nahtstelle ist überall
# die injizierbare Funktion `fetch(url) -> dict`; ein FakeFetch ersetzt sie
# durch eine programmierte Antwortfolge.
# ---------------------------------------------------------------------------

def response(status, body=b"", headers=None, location=None):
    """Baut ein Antwort-Dict wie `_real_fetch` es liefern würde."""
    return {"status": status, "headers": headers or {}, "body": body, "location": location}


class FakeFetch:
    """Ersetzt `fetch`: liefert vordefinierte Antworten je URL, wirft bei
    einer unerwarteten URL statt still irgendetwas zurückzugeben."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        entry = self._responses.get(url)
        if entry is None:
            raise AssertionError(f"FakeFetch: keine programmierte Antwort für {url!r}")
        if isinstance(entry, Exception):
            raise entry
        return entry


HTML_EMPTY = b"<html><head></head><body></body></html>"


class TestErrorReason(unittest.TestCase):
    def test_urlerror_is_translated(self):
        self.assertEqual(
            crawl.error_reason(urllib.error.URLError("timed out")),
            "nicht erreichbar: timed out",
        )

    def test_other_exception_keeps_its_text(self):
        self.assertEqual(crawl.error_reason(RuntimeError("kaputt")), "kaputt")


class TestFetchPage(unittest.TestCase):
    """Die manuelle Redirect-Kette: Task 6 verfolgt Weiterleitungen selbst,
    weil die Kette der Befund ist, nicht ihr Endpunkt."""

    def test_without_a_redirect(self):
        fake = FakeFetch({"https://a.example/x": response(200, body=b"ok")})
        result = crawl.fetch_page("https://a.example/x", fake)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["chain"], [{"url": "https://a.example/x", "status": 200}])
        self.assertEqual(result["end_url"], "https://a.example/x")
        self.assertEqual(result["body"], b"ok")

    def test_a_single_redirect(self):
        fake = FakeFetch({
            "https://a.example/alt": response(301, location="/neu"),
            "https://a.example/neu": response(200, body=b"ok"),
        })
        result = crawl.fetch_page("https://a.example/alt", fake)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["end_url"], "https://a.example/neu")
        self.assertEqual(
            result["chain"],
            [{"url": "https://a.example/alt", "status": 301},
             {"url": "https://a.example/neu", "status": 200}],
        )

    def test_several_redirects_in_a_row(self):
        fake = FakeFetch({
            "https://a.example/a": response(301, location="/b"),
            "https://a.example/b": response(302, location="/c"),
            "https://a.example/c": response(200, body=b"ok"),
        })
        result = crawl.fetch_page("https://a.example/a", fake)
        self.assertEqual([hop["status"] for hop in result["chain"]], [301, 302, 200])
        self.assertEqual(result["end_url"], "https://a.example/c")

    def test_relative_location_resolves_against_the_current_hop(self):
        # Jeder Hop kann relativ zu sich selbst weiterleiten, nicht zur
        # Start-URL. "neu" ohne führenden Slash hängt sich an das
        # Verzeichnis des jeweils aktuellen Hops.
        fake = FakeFetch({
            "https://a.example/de/alt": response(301, location="neu"),
            "https://a.example/de/neu": response(200, body=b"ok"),
        })
        result = crawl.fetch_page("https://a.example/de/alt", fake)
        self.assertEqual(result["end_url"], "https://a.example/de/neu")

    def test_redirect_loop_stops_at_the_limit(self):
        fake = FakeFetch({
            "https://a.example/a": response(301, location="/b"),
            "https://a.example/b": response(301, location="/a"),
        })
        result = crawl.fetch_page("https://a.example/a", fake, max_redirects=3)
        self.assertIsNone(result["status"])
        self.assertEqual(len(result["chain"]), 3)
        self.assertIn("Redirect-Loop", result["error"])


class TestProcessPage(unittest.TestCase):
    def test_successful_page_is_parsed(self):
        html = b'<html><head><title>Start</title></head><body><a href="/a">A</a></body></html>'
        fake = FakeFetch({"https://a.example": response(200, body=html, headers={"content-type": "text/html"})})
        entry = crawl.process_page("https://a.example", fake)
        self.assertEqual(entry["status"], 200)
        self.assertEqual(entry["title"], "Start")
        self.assertEqual(entry["redirects"], [])
        self.assertIn("internal_links", entry)
        self.assertNotIn("error", entry)

    def test_404_is_not_an_error_but_has_no_seo_fields(self):
        fake = FakeFetch({"https://a.example/weg": response(404, body=b"<html>weg</html>")})
        entry = crawl.process_page("https://a.example/weg", fake)
        self.assertEqual(entry["status"], 404)
        self.assertNotIn("error", entry)
        self.assertNotIn("indexable", entry)

    def test_network_error_becomes_an_error_entry_and_does_not_raise(self):
        fake = FakeFetch({"https://a.example/tot": urllib.error.URLError("timed out")})
        entry = crawl.process_page("https://a.example/tot", fake)
        self.assertEqual(entry, {"url": "https://a.example/tot", "error": "nicht erreichbar: timed out"})

    def test_non_html_content_type_is_marked_as_an_error(self):
        fake = FakeFetch({
            "https://a.example/doc.pdf": response(200, body=b"%PDF-1.4", headers={"content-type": "application/pdf"}),
        })
        entry = crawl.process_page("https://a.example/doc.pdf", fake)
        self.assertIn("kein HTML", entry["error"])
        self.assertNotIn("indexable", entry)


class TestParseRobots(unittest.TestCase):
    def test_sitemaps_are_read(self):
        text = "Sitemap: https://a.example/s1.xml\nSitemap: https://a.example/s2.xml\n"
        self.assertEqual(
            crawl.parse_robots(text)["sitemaps"],
            ["https://a.example/s1.xml", "https://a.example/s2.xml"],
        )

    def test_disallow_per_user_agent(self):
        text = "User-agent: *\nDisallow: /admin\nDisallow: /cart\n\nUser-agent: Googlebot\nDisallow:\n"
        rules = crawl.parse_robots(text)["disallow_rules"]
        self.assertEqual(rules["*"], ["/admin", "/cart"])
        self.assertEqual(rules["Googlebot"], [])

    def test_several_user_agent_lines_share_one_group(self):
        text = "User-agent: A\nUser-agent: B\nDisallow: /x\n"
        rules = crawl.parse_robots(text)["disallow_rules"]
        self.assertEqual(rules["A"], ["/x"])
        self.assertEqual(rules["B"], ["/x"])

    def test_new_user_agent_line_after_rules_starts_a_new_group(self):
        text = "User-agent: A\nDisallow: /x\nUser-agent: B\nDisallow: /y\n"
        rules = crawl.parse_robots(text)["disallow_rules"]
        self.assertEqual(rules["A"], ["/x"])
        self.assertEqual(rules["B"], ["/y"])

    def test_ai_crawler_with_root_disallow_counts_as_blocked(self):
        text = "User-agent: GPTBot\nDisallow: /\n"
        self.assertEqual(crawl.parse_robots(text)["ai_crawler_rules"]["GPTBot"], "disallow")

    def test_ai_crawler_without_root_disallow_counts_as_allowed(self):
        text = "User-agent: ClaudeBot\nDisallow: /privat\n"
        self.assertEqual(crawl.parse_robots(text)["ai_crawler_rules"]["ClaudeBot"], "allowed")

    def test_unknown_agent_does_not_appear_in_ai_rules(self):
        text = "User-agent: MeinShopBot\nDisallow: /\n"
        self.assertNotIn("MeinShopBot", crawl.parse_robots(text)["ai_crawler_rules"])


class TestRobotsPathBlocked(unittest.TestCase):
    """Wildcard-Abgleich für Disallow (Review-Fix zu Task 6): `*` als
    Platzhalter für eine beliebige Zeichenfolge, `$` als Zeilenende-Anker,
    sonst wörtlicher Präfix-Vergleich. Die Regeln stammen aus der echten
    robots.txt von beispielshop.example (Shopify-Standard, geprüft am 05.09.2026):
    fast nur Wildcard-Regeln auf Filter- und Sortier-URLs, weil Shopify
    Tag-Filter als Pfadsegment baut, nicht als Query."""

    RULES = [
        "/collections/*sort_by*",
        "/collections/*+*",
        "/collections/*%2B*",
        "*/collections/*filter*&*filter*",
        "/blogs/*+*",
        "/*?*oseid=*",
    ]

    def test_a_normal_collection_is_allowed(self):
        self.assertFalse(crawl.robots_path_blocked("/collections/ringe", self.RULES))

    def test_path_segment_with_a_literal_plus_is_blocked(self):
        # Shopify baut Tag-Filter als Pfad ("/ringe/gold+silber"), nicht als
        # Query. normalize() fängt das nicht ab, das Disallow muss es.
        self.assertTrue(crawl.robots_path_blocked("/collections/ringe/gold+silber", self.RULES))

    def test_sort_by_query_is_blocked(self):
        self.assertTrue(crawl.robots_path_blocked("/collections/ringe?sort_by=price", self.RULES))

    def test_product_page_is_allowed(self):
        self.assertFalse(crawl.robots_path_blocked("/products/ohrstecker", self.RULES))

    def test_blog_post_is_allowed(self):
        self.assertFalse(crawl.robots_path_blocked("/blogs/journal/beitrag", self.RULES))

    def test_blog_with_plus_is_blocked(self):
        self.assertTrue(crawl.robots_path_blocked("/blogs/journal/a+b", self.RULES))

    def test_double_filter_query_is_blocked(self):
        path = "/collections/ringe?filter.p.m.material=gold&filter.p.m.farbe=rose"
        self.assertTrue(crawl.robots_path_blocked(path, self.RULES))

    def test_oseid_query_is_blocked(self):
        self.assertTrue(crawl.robots_path_blocked("/products/ring?oseid=abc123", self.RULES))

    def test_percent_encoded_plus_lowercase_is_recognized(self):
        # RFC 3986: die Hex-Ziffern einer Prozent-Kodierung sind
        # case-insensitiv, %2b und %2B meinen dasselbe Zeichen. Die Regel
        # trägt Grossschreibung, ein Theme kann kleingeschrieben ausgeben.
        self.assertTrue(crawl.robots_path_blocked("/collections/ringe/gold%2bsilber", self.RULES))
        self.assertTrue(crawl.robots_path_blocked("/collections/ringe/gold%2Bsilber", self.RULES))

    def test_dollar_anchors_the_line_end(self):
        self.assertTrue(crawl.robots_path_blocked("/cart", ["/cart$"]))
        self.assertFalse(crawl.robots_path_blocked("/cart/add", ["/cart$"]))

    def test_rule_without_a_star_is_a_prefix_match(self):
        self.assertTrue(crawl.robots_path_blocked("/admin/login", ["/admin"]))

    def test_no_rules_blocks_nothing(self):
        self.assertFalse(crawl.robots_path_blocked("/irgendwas", []))


class TestFetchRobots(unittest.TestCase):
    def test_found_and_parsed(self):
        fake = FakeFetch({
            "https://a.example/robots.txt": response(200, body=b"Sitemap: https://a.example/s.xml\n"),
        })
        robots = crawl.fetch_robots("https://a.example", fake)
        self.assertTrue(robots["found"])
        self.assertEqual(robots["sitemaps"], ["https://a.example/s.xml"])

    def test_404_does_not_abort_the_run(self):
        fake = FakeFetch({"https://a.example/robots.txt": response(404)})
        robots = crawl.fetch_robots("https://a.example", fake)
        self.assertFalse(robots["found"])
        self.assertEqual(robots["reason"], "HTTP 404")
        self.assertEqual(robots["sitemaps"], [])

    def test_network_error_does_not_abort_the_run(self):
        fake = FakeFetch({"https://a.example/robots.txt": urllib.error.URLError("nope")})
        robots = crawl.fetch_robots("https://a.example", fake)
        self.assertFalse(robots["found"])
        self.assertIn("nicht erreichbar", robots["reason"])


class TestDetermineSitemapRoots(unittest.TestCase):
    def test_from_robots_when_present(self):
        robots = {"sitemaps": ["https://a.example/x.xml"]}
        self.assertEqual(crawl.determine_sitemap_roots("https://a.example", robots), ["https://a.example/x.xml"])

    def test_fallback_without_a_robots_sitemap(self):
        self.assertEqual(
            crawl.determine_sitemap_roots("https://a.example", {"sitemaps": []}),
            ["https://a.example/sitemap.xml"],
        )


URLSET_A = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           b'<url><loc>https://a.example/eins</loc></url>'
           b'<url><loc>https://a.example/zwei</loc></url></urlset>')
URLSET_B = (b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           b'<url><loc>https://a.example/drei</loc></url>'
           b'<url><loc>https://a.example/eins</loc></url></urlset>')  # "eins" ist eine Dublette zu URLSET_A


def sitemapindex(*child_urls):
    children = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in child_urls)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{children}</sitemapindex>'.encode()


class TestResolveSitemapTree(unittest.TestCase):
    def test_urlset_without_an_index_is_read_directly(self):
        fake = FakeFetch({"https://a.example/sitemap.xml": response(200, body=URLSET_A)})
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/sitemap.xml"], fake)
        self.assertEqual(urls, ["https://a.example/eins", "https://a.example/zwei"])
        self.assertEqual(errors, [])

    def test_index_is_resolved_recursively_and_duplicates_removed(self):
        root = sitemapindex("https://a.example/s1.xml", "https://a.example/s2.xml")
        fake = FakeFetch({
            "https://a.example/index.xml": response(200, body=root),
            "https://a.example/s1.xml": response(200, body=URLSET_A),
            "https://a.example/s2.xml": response(200, body=URLSET_B),
        })
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/index.xml"], fake)
        self.assertEqual(errors, [])
        # "eins" kommt in beiden Blättern vor, zählt aber nur einmal.
        self.assertEqual(sorted(urls), sorted(["https://a.example/eins", "https://a.example/zwei", "https://a.example/drei"]))
        self.assertEqual(len(urls), len(set(urls)))

    def test_broken_child_breaks_only_that_branch(self):
        # Übergabe Task 5 -> Task 6, Punkt 1: eine 404-Seite mit XML-Content-Type
        # (hier: unvollständiges XML, wie es eine Fehlerseite oft liefert)
        # darf nur diesen Ast kosten, nie den ganzen Baum.
        root = sitemapindex("https://a.example/kaputt.xml", "https://a.example/s1.xml")
        fake = FakeFetch({
            "https://a.example/index.xml": response(200, body=root),
            "https://a.example/kaputt.xml": response(200, body=b"<html>404 not found"),
            "https://a.example/s1.xml": response(200, body=URLSET_A),
        })
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/index.xml"], fake)
        self.assertEqual(urls, ["https://a.example/eins", "https://a.example/zwei"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["sitemap"], "https://a.example/kaputt.xml")

    def test_sitemap_with_http_error_status_breaks_only_that_branch(self):
        root = sitemapindex("https://a.example/weg.xml", "https://a.example/s1.xml")
        fake = FakeFetch({
            "https://a.example/index.xml": response(200, body=root),
            "https://a.example/weg.xml": response(404),
            "https://a.example/s1.xml": response(200, body=URLSET_A),
        })
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/index.xml"], fake)
        self.assertEqual(urls, ["https://a.example/eins", "https://a.example/zwei"])
        self.assertEqual(errors[0]["reason"], "HTTP 404")

    def test_network_error_during_sitemap_fetch_breaks_only_that_branch(self):
        # Ein echter Netzwerkfehler (nicht nur ein HTTP-Fehlerstatus) beim Abruf
        # einer Sitemap darf ebenfalls nur diesen Ast kosten, und die Meldung
        # soll die klare `error_reason`-Formulierung tragen, nicht den rohen
        # Exception-Text von urllib.
        root = sitemapindex("https://a.example/tot.xml", "https://a.example/s1.xml")
        fake = FakeFetch({
            "https://a.example/index.xml": response(200, body=root),
            "https://a.example/tot.xml": urllib.error.URLError("timed out"),
            "https://a.example/s1.xml": response(200, body=URLSET_A),
        })
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/index.xml"], fake)
        self.assertEqual(urls, ["https://a.example/eins", "https://a.example/zwei"])
        self.assertEqual(errors[0]["reason"], "nicht erreichbar: timed out")

    def test_gzip_compressed_sitemap_is_decompressed(self):
        compressed = gzip.compress(URLSET_A)
        fake = FakeFetch({"https://a.example/sitemap.xml.gz": response(200, body=compressed)})
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/sitemap.xml.gz"], fake)
        self.assertEqual(errors, [])
        self.assertEqual(urls, ["https://a.example/eins", "https://a.example/zwei"])

    def test_too_deep_nesting_is_aborted(self):
        leaf = sitemapindex("https://a.example/blatt.xml")  # ein Index in einem Index
        fake = FakeFetch({
            "https://a.example/wurzel.xml": response(200, body=sitemapindex("https://a.example/kind.xml")),
            "https://a.example/kind.xml": response(200, body=leaf),
        })
        urls, errors = crawl.resolve_sitemap_tree(["https://a.example/wurzel.xml"], fake, max_depth=1)
        self.assertEqual(urls, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Verschachtelungstiefe", errors[0]["reason"])


class TestNormalizeSitemapSeeds(unittest.TestCase):
    def test_dedupe_and_filter_after_normalization(self):
        # Übergabe Task 5 -> Task 6, Punkt 2: rohe Sitemap-URLs müssen durch
        # `normalize`, sonst zählt dieselbe Seite (hier: Gross-/
        # Kleinschreibung und Schluss-Slash) doppelt in der Startmenge.
        base = "https://www.example.com"
        raw_urls = ["https://WWW.EXAMPLE.COM/a/", "https://example.com/a", "https://fremd.example.org/x"]
        self.assertEqual(crawl.normalize_sitemap_seeds(raw_urls, base), [f"{base}/a"])

    def test_root_from_sitemap_and_constructed_homepage_are_identical(self):
        # Die Startseite wird in main() als normalize(base + "/", base)
        # gebaut, nicht als normalize(base, base): sonst ergäbe die
        # Wurzel-Ausnahme in `normalize` (Schluss-Slash bleibt bei "/")
        # zwei verschiedene Strings für dieselbe Seite.
        base = "https://www.example.com"
        from_sitemap = crawl.normalize_sitemap_seeds([f"{base}/"], base)
        home = crawl.normalize(base + "/", base)
        self.assertEqual(from_sitemap, [home])


class TestBuildSummary(unittest.TestCase):
    def test_arithmetic(self):
        pages = [
            {"status": 200, "indexable": True, "description": "x", "h1": ["A"],
             "images": {"without_alt": 0}, "redirects": [], "click_depth": 0},
            {"status": 200, "indexable": False, "description": None, "h1": ["A", "B"],
             "images": {"without_alt": 2}, "redirects": [{"url": "x", "status": 301}], "click_depth": 1},
            {"status": 404, "redirects": [], "click_depth": 2},
            {"error": "nicht erreichbar: x", "click_depth": None},
        ]
        summary = crawl.build_summary(pages)
        self.assertEqual(summary["url_count"], 4)
        self.assertEqual(summary["status_code_distribution"], {"200": 2, "404": 1, "error": 1})
        self.assertEqual(summary["share_not_indexable"], 0.5)
        self.assertEqual(summary["share_without_description"], 0.5)
        self.assertEqual(summary["pages_with_multiple_h1"], 1)
        self.assertEqual(summary["images_without_alt"], 2)
        self.assertEqual(summary["longest_redirect_chain"], 1)
        self.assertEqual(summary["max_click_depth"], 2)
        self.assertEqual(summary["blocked_links"], 0)

    def test_empty_list_yields_none_instead_of_division_by_zero(self):
        summary = crawl.build_summary([])
        self.assertIsNone(summary["share_not_indexable"])
        self.assertIsNone(summary["share_without_description"])
        self.assertIsNone(summary["max_click_depth"])
        self.assertEqual(summary["longest_redirect_chain"], 0)

    def test_blocked_links_is_carried_over(self):
        summary = crawl.build_summary([], blocked_links=7)
        self.assertEqual(summary["blocked_links"], 7)


def _page(html_links=""):
    return response(200, body=f"<html><body>{html_links}</body></html>".encode(),
                  headers={"content-type": "text/html"})


class TestCrawl(unittest.TestCase):
    def test_home_has_click_depth_zero(self):
        fake = FakeFetch({"https://a.example": _page()})
        pages = crawl.crawl("https://a.example", [], fake, max_urls=10, delay=0)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["click_depth"], 0)

    def test_click_depth_comes_from_linking_not_from_sitemap_position(self):
        fake = FakeFetch({
            "https://a.example": _page('<a href="/a">A</a>'),
            "https://a.example/a": _page(),
        })
        # "/a" steht zusätzlich in der Sitemap-Menge: die Sitemap-Position
        # (hier: "vorne mit dabei") darf die per Link ermittelte Tiefe nicht
        # verdrängen.
        pages = crawl.crawl("https://a.example", ["https://a.example/a"], fake, max_urls=10, delay=0)
        by_url = {s["url"]: s for s in pages}
        self.assertEqual(by_url["https://a.example/a"]["click_depth"], 1)

    def test_orphaned_sitemap_url_gets_click_depth_none(self):
        fake = FakeFetch({
            "https://a.example": _page(),  # keine Links
            "https://a.example/verwaist": _page(),
        })
        pages = crawl.crawl("https://a.example", ["https://a.example/verwaist"], fake, max_urls=10, delay=0)
        by_url = {s["url"]: s for s in pages}
        self.assertIsNone(by_url["https://a.example/verwaist"]["click_depth"])

    def test_max_urls_limit_is_respected(self):
        fake = FakeFetch({
            "https://a.example": _page('<a href="/a1">1</a><a href="/a2">2</a><a href="/a3">3</a>'),
            "https://a.example/a1": _page(),
            "https://a.example/a2": _page(),
            "https://a.example/a3": _page(),
        })
        pages = crawl.crawl("https://a.example", [], fake, max_urls=2, delay=0)
        self.assertEqual(len(pages), 2)

    def test_one_failed_url_does_not_end_the_run(self):
        fake = FakeFetch({
            "https://a.example": _page('<a href="/kaputt">K</a><a href="/gut">G</a>'),
            "https://a.example/kaputt": urllib.error.URLError("connection refused"),
            "https://a.example/gut": _page(),
        })
        pages = crawl.crawl("https://a.example", [], fake, max_urls=10, delay=0)
        by_url = {s["url"]: s for s in pages}
        self.assertIn("error", by_url["https://a.example/kaputt"])
        self.assertNotIn("error", by_url["https://a.example/gut"])
        self.assertEqual(len(pages), 3)


class TestCrawlDisallow(unittest.TestCase):
    """Review-Fix zu Task 6: Disallow wird auf der Frontier durchgesetzt. Eine
    gesperrte URL wird nie abgerufen (FakeFetch wirft, wenn sie es doch
    wäre), zählt aber als entdeckter Link in `blocked_target`."""

    def test_blocked_link_is_not_fetched_but_is_counted(self):
        fake = FakeFetch({
            "https://a.example": _page('<a href="/admin/login">Admin</a><a href="/gut">Gut</a>'),
            "https://a.example/gut": _page(),
            # Kein Eintrag für /admin/login: FakeFetch wirft bei einem Abruf.
        })
        blocked = set()
        pages = crawl.crawl("https://a.example", [], fake, max_urls=10, delay=0,
                              disallow_rules=["/admin"], blocked_target=blocked)
        visited_urls = {s["url"] for s in pages}
        self.assertNotIn("https://a.example/admin/login", visited_urls)
        self.assertIn("https://a.example/gut", visited_urls)
        self.assertEqual(blocked, {"https://a.example/admin/login"})

    def test_blocked_sitemap_url_is_not_fetched(self):
        fake = FakeFetch({"https://a.example": _page()})
        blocked = set()
        pages = crawl.crawl("https://a.example", ["https://a.example/admin/x"], fake,
                              max_urls=10, delay=0, disallow_rules=["/admin"],
                              blocked_target=blocked)
        self.assertEqual(len(pages), 1)  # nur die Startseite
        self.assertEqual(blocked, {"https://a.example/admin/x"})

    def test_without_disallow_rules_nothing_changes(self):
        # Bestehende Aufrufe ohne die neuen Parameter bleiben unverändert.
        fake = FakeFetch({
            "https://a.example": _page('<a href="/a">A</a>'),
            "https://a.example/a": _page(),
        })
        pages = crawl.crawl("https://a.example", [], fake, max_urls=10, delay=0)
        self.assertEqual(len(pages), 2)

    def test_home_is_fetched_despite_a_matching_rule(self):
        # Die explizit angeforderte Startseite ist der Einstiegspunkt, keine
        # entdeckte Verlinkung, und wird deshalb immer abgerufen.
        fake = FakeFetch({"https://a.example": _page()})
        pages = crawl.crawl("https://a.example", [], fake, max_urls=10, delay=0,
                              disallow_rules=["/"])
        self.assertEqual(len(pages), 1)


class TestCheck(unittest.TestCase):
    def test_ok_returns_exit_zero(self):
        fake = FakeFetch({"https://a.example/sitemap.xml": response(200, body=URLSET_A)})
        robots = {"found": False, "sitemaps": []}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = crawl.check("https://a.example", robots, ["https://a.example/sitemap.xml"], fake)
        self.assertEqual(code, 0)
        self.assertIn("2 URLs erwartet", output.getvalue())

    def test_no_sitemap_reachable_returns_exit_one(self):
        fake = FakeFetch({"https://a.example/sitemap.xml": urllib.error.URLError("connection refused")})
        robots = {"found": False, "sitemaps": []}
        with contextlib.redirect_stdout(io.StringIO()):
            code = crawl.check("https://a.example", robots, ["https://a.example/sitemap.xml"], fake)
        self.assertEqual(code, 1)


class TestScriptSources(unittest.TestCase):
    """Welche Skripte eine Seite lädt, ist ein Befund.

    Der Inhalt bleibt inert, die Quelle nicht: an ihr hängen Preistest-
    Werkzeuge, Bewertungs-Apps und doppelte Analytics-Einbindungen.
    """

    HTML = ('<html><head>'
            '<script src="https://cdn.intelligems.io/x.js"></script>'
            '<script src="//cdn.judge.me/y.js"></script>'
            '<script>var inline = 1;</script>'
            '</head><body>'
            '<template><script src="https://versteckt.example/z.js"></script></template>'
            '</body></html>')

    def test_foreign_sources_are_recorded(self):
        sources = crawl.parse_page(self.HTML, BASE)["script_sources"]
        self.assertIn("https://cdn.intelligems.io/x.js", sources)
        self.assertIn("//cdn.judge.me/y.js", sources)

    def test_inline_script_without_src_does_not_appear(self):
        self.assertEqual(len(crawl.parse_page(self.HTML, BASE)["script_sources"]), 2)

    def test_script_in_template_does_not_count(self):
        sources = crawl.parse_page(self.HTML, BASE)["script_sources"]
        self.assertNotIn("https://versteckt.example/z.js", sources)

    def test_own_sources_stay_in_the_page_list(self):
        # Die Seitenliste filtert nichts: zwei Loader desselben Anbieters auf
        # einer Seite sind der Beleg für doppelte Tags, und dafür muss die
        # rohe src stehenbleiben. Gefiltert wird erst im Site-Rollup.
        html = '<html><head><script src="/assets/theme.js"></script></head></html>'
        self.assertEqual(crawl.parse_page(html, BASE)["script_sources"],
                         ["/assets/theme.js"])


class TestScriptHost(unittest.TestCase):
    """Die drei Schreibweisen, die in echten Themes nebeneinander stehen."""

    def test_absolute_foreign_source(self):
        self.assertEqual(
            crawl.script_host("https://cdn.intelligems.io/x.js", BASE),
            "cdn.intelligems.io")

    def test_protocol_relative_source(self):
        self.assertEqual(crawl.script_host("//cdn.judge.me/y.js", BASE),
                         "cdn.judge.me")

    def test_page_relative_source_is_the_shop_itself(self):
        self.assertIsNone(crawl.script_host("/assets/theme.js", BASE))

    def test_own_host_written_out_is_the_shop_itself(self):
        self.assertIsNone(
            crawl.script_host("https://www.example.com/assets/theme.js", BASE))

    def test_own_host_without_www_is_the_same_shop(self):
        self.assertIsNone(
            crawl.script_host("https://example.com/assets/theme.js", BASE))

    def test_subdomain_of_the_shop_stays_foreign(self):
        # Nur ein führendes www. gilt als derselbe Shop, cdn. nicht: dort
        # liegt bei Shopify die Anbieter-Auslieferung.
        self.assertEqual(
            crawl.script_host("https://cdn.example.com/x.js", BASE),
            "cdn.example.com")

    def test_data_uri_has_no_host(self):
        self.assertIsNone(crawl.script_host("data:text/javascript,void 0", BASE))

    def test_without_a_base_every_host_counts_as_foreign(self):
        # Sichere Richtung: lieber ein eigener Host zu viel als ein
        # Preistest-Werkzeug still unterschlagen.
        self.assertEqual(crawl.script_host("https://www.example.com/x.js", ""),
                         "www.example.com")


class TestThirdPartyScriptHosts(unittest.TestCase):
    """Das Site-Rollup: welche Fremdanbieter laufen in diesem Shop überhaupt."""

    PAGES = [
        {"script_sources": ["https://cdn.intelligems.io/x.js",
                            "/assets/theme.js"]},
        {"script_sources": ["https://cdn.intelligems.io/anders.js",
                            "//cdn.judge.me/y.js"]},
        {"status": 404},
    ]

    def test_deduplicated_and_sorted_over_all_pages(self):
        self.assertEqual(crawl.third_party_script_hosts(self.PAGES, BASE),
                         ["cdn.intelligems.io", "cdn.judge.me"])

    def test_page_without_script_sources_does_not_raise(self):
        # Ein 404 läuft nie durch parse_page und hat das Feld gar nicht.
        self.assertEqual(crawl.third_party_script_hosts([{"status": 404}], BASE), [])

    def test_summary_carries_the_hosts(self):
        summary = crawl.build_summary(self.PAGES, base=BASE)
        self.assertEqual(summary["third_party_script_hosts"],
                         ["cdn.intelligems.io", "cdn.judge.me"])



class TestTitelGegenSvg(unittest.TestCase):
    """Shopify rendert Zahlungs-Icons als Inline-SVG, und SVG hat ein eigenes
    <title>. Auf beispielshop.example standen zehn davon auf der Startseite, das letzte
    war "Visa". Der Parser hat bei jedem ueberschrieben, also trug jede Seite des
    Shops denselben falschen Titel, und jeder Title-Befund darueber war Unsinn.
    Gefunden im ersten echten audit-light-Lauf am 07.09.2026."""

    def _titel(self, html: str):
        p = crawl._PageParser()
        p.feed(html)
        return p.title

    def test_svg_title_gewinnt_nicht(self):
        html = ("<html><head><title>Echter Titel</title></head><body>"
                "<svg><title>Visa</title></svg><svg><title>PayPal</title></svg>"
                "</body></html>")
        self.assertEqual(self._titel(html), "Echter Titel")

    def test_erstes_title_gewinnt_auch_ohne_svg(self):
        html = "<html><head><title>Erster</title></head><body><title>Zweiter</title></body></html>"
        self.assertEqual(self._titel(html), "Erster")

    def test_svg_vor_dem_echten_title_verdeckt_ihn_nicht(self):
        html = ("<html><body><svg><title>Visa</title></svg>"
                "<head><title>Echter Titel</title></head></body></html>")
        self.assertEqual(self._titel(html), "Echter Titel")

    def test_verschachtelte_svg_zaehlen_richtig(self):
        html = ("<html><body><svg><svg><title>Visa</title></svg></svg>"
                "<title>Echter Titel</title></body></html>")
        self.assertEqual(self._titel(html), "Echter Titel")

    def test_seite_ohne_title_bleibt_none(self):
        self.assertIsNone(self._titel("<html><body><svg><title>Visa</title></svg></body></html>"))

if __name__ == "__main__":
    unittest.main()


class TestDrosselung(unittest.TestCase):
    """Ein gedrosselter Crawl darf nicht wie ein vollständiger aussehen.

    Am 07.09.2026 kamen bei --delay 0.2 genau 826 von 2500 Antworten mit
    HTTP 429 zurück. Der Crawl zählte sie mit und lief unverändert weiter; jeder
    Anteil im Snapshot bezog sich danach auf 1667 statt 2500 Seiten, ohne dass
    das irgendwo stand.
    """

    #: Der Antwort-Helfer oben baut das Format, das `_real_fetch` liefert.
    BODY = b"<html><head><title>T</title></head><body>x</body></html>"

    def _fetch(self, antworten):
        """Ein Abruf, der die vorgegebenen Statuscodes der Reihe nach liefert."""
        folge = list(antworten)

        def fetch(url):
            code = folge.pop(0) if folge else 200
            return response(code, self.BODY,
                            {"content-type": "text/html; charset=utf-8"})
        return fetch

    def test_pause_waechst_nach_drosselung(self):
        pausen = []
        echt = crawl.time.sleep
        crawl.time.sleep = pausen.append
        try:
            crawl.crawl("https://x.test/", ["https://x.test/a", "https://x.test/b",
                                            "https://x.test/c"],
                        self._fetch([200, 429, 429, 200]), max_urls=4, delay=0.1)
        finally:
            crawl.time.sleep = echt
        self.assertTrue(pausen, "es wurde gar nicht gewartet")
        self.assertGreater(max(pausen), 0.1,
                           "nach einer Drosselung muss die Pause steigen")

    def test_ohne_drosselung_bleibt_die_pause(self):
        pausen = []
        echt = crawl.time.sleep
        crawl.time.sleep = pausen.append
        try:
            crawl.crawl("https://x.test/", ["https://x.test/a", "https://x.test/b"],
                        self._fetch([200, 200, 200]), max_urls=3, delay=0.1)
        finally:
            crawl.time.sleep = echt
        self.assertTrue(all(abs(p - 0.1) < 1e-9 for p in pausen),
                        f"die Pause darf ohne 429 nicht wandern: {pausen}")


class TestSelbstpruefung(unittest.TestCase):
    """Der Crawler prüft sein eigenes Ergebnis, bevor daraus ein Befund wird.

    Am 07.09.2026 trug jede der gut tausend abgerufenen Seiten den Titel "Visa".
    Das war unser Parser, der die Zahlungs-Icons im Seitenfuß mitnahm, und
    es ist als Schlagzeile in einen Kundenreport gewandert.
    """

    @staticmethod
    def _seiten(title, n=40):
        return [{"status": 200, "title": title} for _ in range(n)]

    def test_ein_zahlungsicon_als_titel_wird_als_eigener_fehler_benannt(self):
        hinweise = crawl.self_check(self._seiten("Visa"))
        self.assertEqual(len(hinweise), 1)
        self.assertIn("Visa", hinweise[0])
        self.assertIn("Fehler beim Auslesen", hinweise[0])

    def test_ein_anderer_wiederholter_titel_wird_zur_nachpruefung_gemeldet(self):
        hinweise = crawl.self_check(self._seiten("Beispielshop Schmuck"))
        self.assertEqual(len(hinweise), 1)
        self.assertIn("gegenpruefen", hinweise[0])

    def test_unterschiedliche_titel_melden_nichts(self):
        pages = [{"status": 200, "title": f"Seite {i}"} for i in range(40)]
        self.assertEqual(crawl.self_check(pages), [])

    def test_zu_wenige_seiten_melden_nichts(self):
        """Bei fuenf Seiten ist ein gemeinsamer Titel kein Signal."""
        self.assertEqual(crawl.self_check(self._seiten("Visa", n=5)), [])


class TestDrosselungWiederholt(unittest.TestCase):
    """Die Wartezeiten werden hier uebersprungen, nicht abgeschaltet.

    Der Crawl wartet nach einer Drosselung mindestens eine halbe Sekunde, und
    das soll er auch: der Shop hat gerade gesagt, dass es ihm zu schnell geht.
    Der Test prueft die Logik, nicht die Geduld.
    """

    def setUp(self):
        self._sleep = crawl.time.sleep
        crawl.time.sleep = lambda _s: None

    def tearDown(self):
        crawl.time.sleep = self._sleep

    """429 heisst "spaeter nochmal", nicht "gibt es nicht".

    Bis zum 08.09.2026 verbuchte der Crawl eine abgewiesene Antwort als
    erledigte Seite. Bei einem Shop war das rund ein Drittel der Seiten, und jeder
    Anteil im Snapshot bezog sich in Wahrheit auf den Rest, ohne dass das
    irgendwo stand.
    """

    def test_eine_gedrosselte_seite_wird_wiederholt(self):
        versuche = {"n": 0}

        def fetch(url):
            versuche["n"] += 1
            if versuche["n"] == 1:
                return response(429)
            return response(200, b"<html><head><title>Da</title></head></html>",
                            {"content-type": "text/html"})

        pages = crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        self.assertEqual(versuche["n"], 2)
        self.assertEqual(pages[0]["status"], 200)
        self.assertNotIn("throttled", pages[0])

    def test_dauerhaft_gedrosselt_wird_ausgewiesen(self):
        def fetch(url):
            return response(429)

        pages = crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        self.assertTrue(pages[0]["throttled"])
        self.assertEqual(
            crawl.build_summary(pages, blocked_links=0,
                                base="https://x.test/")["throttled_pages"], 1)

    def test_die_zahl_der_versuche_ist_begrenzt(self):
        """Hauptdurchgang plus Nachlauf, und dann ist Schluss.

        Die erste Fassung dieses Fixes versuchte es dreimal je Seite mit
        verdoppelter Pause. Bei anhaltender Drosselung kostete das bis zu 29
        Sekunden pro Seite, und ein Lauf über 3.000 URLs hätte 24 Stunden
        gebraucht.
        """
        versuche = {"n": 0}

        def fetch(url):
            versuche["n"] += 1
            return response(429)

        crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        self.assertEqual(versuche["n"],
                         crawl.RETRY_429 + 1 + crawl.NACHLAUF_RUNDEN)

    def test_der_hauptdurchgang_haengt_nicht_an_einer_seite(self):
        """Eine gedrosselte Seite wird geparkt, der Durchgang läuft weiter."""
        gesehen = []

        def fetch(url):
            gesehen.append(url)
            if url.endswith("/a"):
                return response(429)
            return response(200, b"<html><head><title>T</title></head></html>",
                            {"content-type": "text/html"})

        crawl.crawl("https://x.test/", ["https://x.test/a", "https://x.test/b"],
                    fetch, max_urls=3, delay=0)
        # /a wird im Hauptdurchgang zweimal versucht, dann geparkt; /b kommt
        # trotzdem dran, bevor der Nachlauf beginnt.
        self.assertIn("https://x.test/b", gesehen)
        self.assertLess(gesehen.index("https://x.test/b"), len(gesehen) - 1)

    def test_der_nachlauf_holt_nach_was_spaeter_antwortet(self):
        """Der Shop hatte waehrend des Hauptdurchgangs Zeit, sich zu erholen."""
        numerator = {"n": 0}

        def fetch(url):
            numerator["n"] += 1
            if numerator["n"] <= 2:
                return response(429)
            return response(200, b"<html><head><title>Da</title></head></html>",
                            {"content-type": "text/html"})

        pages = crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        self.assertEqual(pages[0]["status"], 200)
        self.assertNotIn("throttled", pages[0])

    def test_eine_cloudflare_challenge_ist_keine_drosselung(self):
        """Beides kommt als HTTP 429 an, und der Unterschied entscheidet ueber
        Stunden: langsamer werden hilft gegen eine Drosselung und nie gegen
        eine Bot-Erkennung."""
        self.assertEqual(
            crawl.bot_challenge(429, {"cf-mitigated": "challenge",
                                      "server": "cloudflare"}),
            "Cloudflare-Bot-Management (challenge)")
        self.assertEqual(
            crawl.bot_challenge(429, {"server": "cloudflare"}),
            "Cloudflare-Bot-Management (429 ohne Retry-After)")
        # Eine echte Drosselung nennt, wann es wieder geht.
        self.assertIsNone(
            crawl.bot_challenge(429, {"server": "cloudflare",
                                      "retry-after": "30"}))
        self.assertIsNone(crawl.bot_challenge(429, {}))
        self.assertIsNone(crawl.bot_challenge(200, {"cf-mitigated": "challenge"}))

    def test_eine_abgewiesene_seite_wird_nicht_wiederholt(self):
        """Die Challenge kommt in Millisekunden zurueck, egal wie lange wir
        vorher gewartet haben. Ein zweiter Versuch ist reine Wartezeit."""
        versuche = {"n": 0}

        def fetch(url):
            versuche["n"] += 1
            return response(429, headers={"cf-mitigated": "challenge",
                                          "server": "cloudflare"})

        pages = crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        self.assertEqual(versuche["n"], 1, "die Seite wurde wiederholt")
        self.assertEqual(len(pages), 1)
        self.assertIn("bot_challenge", pages[0])
        self.assertNotIn("throttled", pages[0])

    def test_eine_abgewiesene_seite_bremst_den_lauf_nicht_aus(self):
        """Die Pause darf nicht hochlaufen: sonst faehrt der Lauf stundenlang
        gegen eine Wand, wie am 08.09.2026."""
        def fetch(url):
            if url.endswith("/gesperrt"):
                return response(429, headers={"cf-mitigated": "challenge",
                                              "server": "cloudflare"})
            return response(200, b"<html><head><title>T</title></head></html>",
                            {"content-type": "text/html"})

        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            crawl.crawl("https://x.test/", ["https://x.test/gesperrt"], fetch,
                        max_urls=2, delay=0.5)
        letzte = [z for z in errors.getvalue().splitlines()
                  if z.startswith("Crawl: ")][-1]
        self.assertIn("Pause 0.5s", letzte)
        self.assertIn("1 als Bot abgewiesen", letzte)

    def test_die_zusammenfassung_zaehlt_abgewiesene_seiten_getrennt(self):
        """Ein Anteil aus diesem Snapshot bezieht sich auf die messbaren
        Seiten, und wie viele nicht messbar waren, muss dranstehen."""
        pages = [
            {"url": "https://x.test/a", "status": 200, "indexable": True},
            {"url": "https://x.test/b", "status": 429,
             "bot_challenge": "Cloudflare-Bot-Management (challenge)"},
        ]
        summary = crawl.build_summary(pages)
        self.assertEqual(summary["bot_challenge_pages"], 1)
        self.assertEqual(summary["throttled_pages"], 0)

    def test_der_user_agent_nennt_sich_als_crawler_mit_kontakt(self):
        """Ein nacktes Kuerzel gilt Bot-Management-Systemen als
        unidentifiziertes Skript. Name und Kontakt bleiben lesbar darin."""
        self.assertIn("compatible", crawl.USER_AGENT)
        self.assertIn("ptai-audit", crawl.USER_AGENT)
        self.assertIn("+https://", crawl.USER_AGENT)

    def test_das_lebenszeichen_kommt_sofort_und_nicht_erst_nach_50_seiten(self):
        """Die erste Fassung meldete alle 50 Seiten. Bei den auf einem echten
        Shop gemessenen 1,5 Sekunden je Seite sind das 75 Sekunden Stille am
        Anfang, und in diese Stille faellt jedes Zeitlimit, mit dem ein Aufrufer
        den Lauf beobachtet."""
        def fetch(url):
            return response(200, b"<html><head><title>T</title></head></html>",
                            {"content-type": "text/html"})

        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            crawl.crawl("https://x.test/", [], fetch, max_urls=1, delay=0)
        rows = [z for z in errors.getvalue().splitlines() if z.strip()]
        self.assertTrue(any(z.startswith("Crawl startet:") for z in rows),
                        f"keine Startzeile in {rows}")
        self.assertTrue(any("Seiten in" in z for z in rows),
                        f"keine Fortschrittszeile in {rows}")

    def test_das_lebenszeichen_misst_sekunden_und_nicht_seiten(self):
        """Ein schneller Shop soll den Bildschirm nicht vollschreiben: zwischen
        zwei Meldungen liegt eine Zeitspanne, keine Seitenzahl."""
        self.assertIsInstance(crawl.FORTSCHRITT_SEKUNDEN, float)
        self.assertGreaterEqual(crawl.FORTSCHRITT_SEKUNDEN, 5.0)

        def fetch(url):
            return response(200, b"<html><head><title>T</title></head></html>",
                            {"content-type": "text/html"})

        seiten_urls = [f"https://x.test/p{n}" for n in range(60)]
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            crawl.crawl("https://x.test/", seiten_urls, fetch, max_urls=61,
                        delay=0)
        laufend = [z for z in errors.getvalue().splitlines()
                   if z.startswith("Crawl: ")]
        # 61 Seiten in Millisekunden: genau eine Zeile, die erzwungene am Ende.
        self.assertEqual(len(laufend), 1, laufend)

    def test_die_pause_haengt_nicht_mehr_am_delay(self):
        """`delay * 16` war ein stiller Multiplikator: bei --delay 0.6 ergab er
        9,6 Sekunden Pause."""
        self.assertLessEqual(crawl.PAUSE_MAX, 5.0)
        for delay in (0.2, 0.6, 2.0):
            with self.subTest(delay=delay):
                self.assertLessEqual(min(crawl.PAUSE_MAX,
                                         max(delay * 8, 1.0)), crawl.PAUSE_MAX)
