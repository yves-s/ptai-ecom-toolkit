"""Auflösung Shop-URL zu Account-Slug."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from audit import account, env
from tests import support

SCRIPTS = Path(__file__).resolve().parents[1]

HOMEPAGE_OG = ('<html><head><title>Taschen aus Leder | Beispielshop</title>'
               '<meta property="og:site_name" content="Beispielshop &amp; Co"></head></html>')
HOMEPAGE_TITLE = "<html><head><title>Beispielshop | Taschen aus Leder</title></head></html>"


def _account(root: str, slug: str, frontmatter: str, title: str = "") -> None:
    """Legt einen Account mit gegebenem Frontmatter-Block an."""
    ordner = os.path.join(root, slug)
    os.makedirs(ordner, exist_ok=True)
    header = f"# {title}\n" if title else ""
    with open(os.path.join(ordner, "entity.md"), "w", encoding="utf-8") as fh:
        fh.write(f"---\ntype: entity\n{frontmatter}\nrechnungen:\n---\n\n{header}\nText.\n")


class TestNormalizeHost(unittest.TestCase):
    def test_schema_pfad_und_www_fallen_weg(self):
        for raw in ("https://www.shop.de/kategorie?a=1", "HTTP://Shop.de", "www.shop.de", "shop.de/"):
            self.assertEqual(account.normalize_host(raw), "shop.de", raw)

    def test_port_und_fragment_fallen_weg(self):
        self.assertEqual(account.normalize_host("https://shop.de:8443/x#y"), "shop.de")

    def test_leere_eingabe_ergibt_leeren_string(self):
        for raw in ("", None, "   "):
            self.assertEqual(account.normalize_host(raw), "")

    def test_subdomain_bleibt_erhalten(self):
        self.assertEqual(account.normalize_host("https://shop.example.de"), "shop.example.de")


class TestParseDomains(unittest.TestCase):
    def test_inline_form(self):
        self.assertEqual(account.parse_domains("domains: a.de, b.de\n"), ["a.de", "b.de"])

    def test_klammer_form(self):
        self.assertEqual(account.parse_domains("domains: [a.de, b.de]\n"), ["a.de", "b.de"])

    def test_yaml_blockliste(self):
        # Die Form, an der die alte JS-Funktion scheiterte.
        text = "aliases: [X]\ndomains:\n  - radlast.cc\n  - zweite.de\nrechnungen:\n"
        self.assertEqual(account.parse_domains(text), ["radlast.cc", "zweite.de"])

    def test_blockliste_endet_am_naechsten_feld(self):
        text = "domains:\n  - a.de\nrechnungen:\n  - nicht-uebernehmen\n"
        self.assertEqual(account.parse_domains(text), ["a.de"])

    def test_leere_zeile_ergibt_leere_liste(self):
        self.assertEqual(account.parse_domains("domains:\nrechnungen:\n"), [])

    def test_fehlende_zeile_ergibt_leere_liste(self):
        self.assertEqual(account.parse_domains("aliases: [X]\n"), [])

    def test_www_wird_auch_im_frontmatter_normalisiert(self):
        self.assertEqual(account.parse_domains("domains: www.Shop.DE\n"), ["shop.de"])


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_exakter_treffer(self):
        _account(self.root, "shop", "domains: shop.de")
        r = account.resolve("https://www.shop.de/produkt", self.root)
        self.assertEqual((r["status"], r["slug"]), ("exact", "shop"))

    def test_subdomain_treffer(self):
        _account(self.root, "brand", "domains: brand.de")
        r = account.resolve("https://shop.brand.de", self.root)
        self.assertEqual((r["status"], r["slug"]), ("subdomain", "brand"))

    def test_exakt_schlaegt_subdomain(self):
        # Eine Holding mit der Wurzeldomain darf den Shop nicht einsammeln.
        _account(self.root, "holding", "domains: brand.de")
        _account(self.root, "shop", "domains: shop.brand.de")
        r = account.resolve("https://shop.brand.de", self.root)
        self.assertEqual((r["status"], r["slug"]), ("exact", "shop"))

    def test_mehrdeutig_liefert_kandidaten_und_keinen_slug(self):
        _account(self.root, "eins", "domains: shop.de")
        _account(self.root, "zwei", "domains: shop.de")
        r = account.resolve("shop.de", self.root)
        self.assertEqual(r["status"], "ambiguous")
        self.assertIsNone(r["slug"])
        self.assertEqual(r["candidates"], ["eins", "zwei"])

    def test_kein_treffer(self):
        _account(self.root, "shop", "domains: shop.de")
        r = account.resolve("fremd.de", self.root)
        self.assertEqual((r["status"], r["slug"]), ("none", None))

    def test_blockliste_wird_gefunden(self):
        # Der Regressionstest zur Luecke der alten Funktion.
        _account(self.root, "radlast", "aliases: [Radlast]\ndomains:\n  - radlast.cc")
        r = account.resolve("https://radlast.cc", self.root)
        self.assertEqual((r["status"], r["slug"]), ("exact", "radlast"))

    def test_account_ohne_entity_wird_uebersprungen(self):
        os.makedirs(os.path.join(self.root, "leer"), exist_ok=True)
        _account(self.root, "shop", "domains: shop.de")
        self.assertEqual(account.resolve("shop.de", self.root)["slug"], "shop")

    def test_leere_url_ergibt_none_ohne_dateizugriff(self):
        r = account.resolve("", self.root)
        self.assertEqual((r["status"], r["host"]), ("none", ""))

    def test_fehlendes_accounts_verzeichnis_wirft_nicht(self):
        r = account.resolve("shop.de", os.path.join(self.root, "gibt-es-nicht"))
        self.assertEqual(r["status"], "none")


class TestBrandOf(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)

    def test_stadium_klammer_ist_keine_marke(self):
        _account(self.root, "shop", "domains: shop.de", title="Beispiel GmbH (Lead)")
        self.assertEqual(account.brand_of("shop"), "Beispiel")

    def test_klammer_ist_die_marke_nicht_die_firma(self):
        # Nach der GbR fragt niemand eine KI, nach der Marke schon.
        _account(self.root, "shop", "domains: shop.de",
                 title="A. Muster & B. Muster GbR (LEDERTASCHE)")
        self.assertEqual(account.brand_of("shop"), "LEDERTASCHE")

    def test_fuehrendes_marke_faellt_weg(self):
        _account(self.root, "shop", "domains: shop.de", title="Handel GmbH (Marke Wohnlicht)")
        self.assertEqual(account.brand_of("shop"), "Wohnlicht")

    def test_ohne_klammer_faellt_nur_die_rechtsform_weg(self):
        for title, brand in (("Beispiel & Muster Handels GmbH", "Beispiel & Muster Handels"),
                             ("nordagentur GmbH & Co. KG", "nordagentur"),
                             ("SATTELWERK", "SATTELWERK")):
            with self.subTest(title=title):
                _account(self.root, "shop", "domains: shop.de", title=title)
                self.assertEqual(account.brand_of("shop"), brand)

    def test_legal_name_behaelt_die_rechtsperson(self):
        _account(self.root, "shop", "domains: shop.de",
                 title="A. Muster & B. Muster GbR (LEDERTASCHE)")
        self.assertEqual(account.legal_name_of("shop"),
                         "A. Muster & B. Muster GbR")

    def test_ohne_ueberschrift_faellt_auf_den_slug_zurueck(self):
        _account(self.root, "shop", "domains: shop.de")
        self.assertEqual(account.brand_of("shop"), "shop")


class TestAccountsRoot(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)
        self.home = self.root.parent / "home"

    def test_the_setting_wins(self):
        self.assertEqual(account.accounts_root(), str(self.root))

    def test_a_tilde_is_expanded(self):
        (self.home / "kunden").mkdir()
        os.environ["PTAI_ACCOUNTS_ROOT"] = "~/kunden"
        self.assertEqual(account.accounts_root(), str(self.home / "kunden"))

    def test_the_setting_is_found_in_the_central_file(self):
        del os.environ["PTAI_ACCOUNTS_ROOT"]
        env.CENTRAL.write_text(f"PTAI_ACCOUNTS_ROOT={self.root}\n", encoding="utf-8")
        self.assertEqual(account.accounts_root(workspace=self.root.parent), str(self.root))

    def test_without_the_setting_the_default_applies(self):
        del os.environ["PTAI_ACCOUNTS_ROOT"]
        self.assertEqual(account.accounts_root(workspace=self.root.parent),
                         str(self.home / "ptai-ecom" / "accounts"))

    def test_a_missing_default_finds_nothing_and_raises_nothing(self):
        # Vor dem ersten Kunden gibt es den Ordner der Vorgabe noch nicht.
        del os.environ["PTAI_ACCOUNTS_ROOT"]
        self.assertEqual(account.resolve("beispielshop.example")["status"], "none")

    def test_a_configured_root_that_is_missing_raises(self):
        # Ein nicht eingebundener Cloud-Ordner darf nicht wie "kein Kunde"
        # aussehen, sonst legt audit-light einen zweiten an.
        os.environ["PTAI_ACCOUNTS_ROOT"] = str(self.root.parent / "nicht-eingebunden")
        with self.assertRaises(account.AccountsRootError) as ctx:
            account.resolve("beispielshop.example")
        self.assertIn("PTAI_ACCOUNTS_ROOT", str(ctx.exception))

    def test_a_relative_setting_raises(self):
        os.environ["PTAI_ACCOUNTS_ROOT"] = "kunden"
        with self.assertRaises(account.AccountsRootError):
            account.accounts_root()

    def test_resolve_reads_the_root(self):
        _account(str(self.root), "beispielshop", "domains: beispielshop.example")
        self.assertEqual(account.resolve("https://www.beispielshop.example")["slug"],
                         "beispielshop")

    def test_drive_path_is_absolute(self):
        path = account.drive_path("beispielshop")
        self.assertEqual(path, str(self.root / "beispielshop"))
        self.assertTrue(os.path.isabs(path))


class TestSlugFromHost(unittest.TestCase):
    def test_the_label_before_the_ending(self):
        self.assertEqual(account.slug_from_host("beispiel-shop.de"), "beispiel-shop")

    def test_www_scheme_and_subdomain_fall_away(self):
        for host in ("www.beispielshop.de", "https://shop.beispielshop.de/produkt",
                     "BEISPIELSHOP.DE"):
            with self.subTest(host=host):
                self.assertEqual(account.slug_from_host(host), "beispielshop")

    def test_two_part_endings_from_the_fixed_list(self):
        for host in ("beispielshop.co.uk", "www.beispielshop.com.au",
                     "beispielshop.co.at", "beispielshop.or.at"):
            with self.subTest(host=host):
                self.assertEqual(account.slug_from_host(host), "beispielshop")

    def test_kebab_case_and_umlauts(self):
        self.assertEqual(account.slug_from_host("Beispiel_Shop.de"), "beispiel-shop")
        self.assertEqual(account.slug_from_host("müllerbeispiel.de"), "muellerbeispiel")

    def test_single_label_and_empty_input(self):
        self.assertEqual(account.slug_from_host("localhost"), "localhost")
        self.assertEqual(account.slug_from_host(""), "")


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)

    def test_writes_domain_and_brand(self):
        path = account.create("beispielshop", "Beispielshop", "www.beispielshop.example")
        self.assertEqual(path, str(self.root / "beispielshop"))
        text = (self.root / "beispielshop" / "entity.md").read_text(encoding="utf-8")
        self.assertIn("domains: beispielshop.example\n", text)
        self.assertIn("\n# Beispielshop\n", text)

    def test_the_new_customer_resolves_with_its_brand(self):
        account.create("beispielshop", "Beispielshop", "beispielshop.example")
        found = account.resolve("https://www.beispielshop.example/produkt")
        self.assertEqual((found["status"], found["slug"]), ("exact", "beispielshop"))
        self.assertEqual(account.brand_of("beispielshop"), "Beispielshop")

    def test_an_existing_folder_is_never_touched(self):
        folder = self.root / "beispielshop"
        folder.mkdir()
        entity = folder / "entity.md"
        entity.write_text("---\ndomains: anderer-shop.example\n---\n\n# Anderer Shop\n",
                          encoding="utf-8")
        with self.assertRaises(account.AccountExistsError) as ctx:
            account.create("beispielshop", "Beispielshop", "beispielshop.example")
        self.assertIn("anderer-shop.example", entity.read_text(encoding="utf-8"))
        for part in ("domains:", "beispielshop.example", "beispielshop-2"):
            self.assertIn(part, str(ctx.exception))

    def test_a_folder_without_entity_counts_as_existing(self):
        (self.root / "beispielshop").mkdir()
        with self.assertRaises(account.AccountExistsError):
            account.create("beispielshop", "Beispielshop", "beispielshop.example")
        self.assertFalse((self.root / "beispielshop" / "entity.md").exists())

    def test_the_default_root_is_created_on_first_use(self):
        del os.environ["PTAI_ACCOUNTS_ROOT"]
        path = account.create("beispielshop", "Beispielshop", "beispielshop.example")
        self.assertEqual(path, str(self.root.parent / "home" / "ptai-ecom" / "accounts"
                                   / "beispielshop"))
        self.assertTrue(os.path.isfile(os.path.join(path, "entity.md")))

    def test_an_unusable_slug_or_host_raises(self):
        for slug, host in (("../beispielshop", "beispielshop.example"),
                           ("", "beispielshop.example"), ("beispielshop", "")):
            with self.subTest(slug=slug, host=host), self.assertRaises(ValueError):
                account.create(slug, "Beispielshop", host)


class TestHomepageBrand(unittest.TestCase):
    def test_og_site_name_wins_over_the_title(self):
        self.assertEqual(account.homepage_brand(HOMEPAGE_OG),
                         ("Beispielshop & Co", "og:site_name"))

    def test_og_site_name_as_name_attribute(self):
        page = '<meta content="Beispielshop" name="og:site_name">'
        self.assertEqual(account.homepage_brand(page), ("Beispielshop", "og:site_name"))

    def test_otherwise_the_first_part_of_the_title(self):
        self.assertEqual(account.homepage_brand(HOMEPAGE_TITLE), ("Beispielshop", "title"))

    def test_title_separators(self):
        titles = ["Beispielshop | Taschen", "Beispielshop - Taschen", "Beispielshop: Taschen",
                  "Beispielshop " + chr(0xB7) + " Taschen"]
        titles += [f"Beispielshop {dash} Taschen" for dash in (chr(0x2013), chr(0x2014))]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(account.homepage_brand(f"<title>{title}</title>"),
                                 ("Beispielshop", "title"))

    def test_a_hyphen_inside_the_name_stays(self):
        self.assertEqual(account.homepage_brand("<title>Beispiel-Shop</title>"),
                         ("Beispiel-Shop", "title"))

    def test_nothing_usable(self):
        for page in (None, "", "<html></html>", "<title>   </title>",
                     '<meta property="og:site_name" content=" ">'):
            with self.subTest(page=page):
                self.assertIsNone(account.homepage_brand(page))


class TestFindOrCreate(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)
        self.calls = []

    def fetcher(self, page):
        def fetch(url):
            self.calls.append(url)
            return page
        return fetch

    def test_an_existing_customer_is_found_without_a_fetch(self):
        account.create("beispielshop", "Beispielshop", "beispielshop.example")
        found = account.find_or_create("https://www.beispielshop.example",
                                       fetch=self.fetcher(HOMEPAGE_OG))
        self.assertEqual((found["status"], found["slug"], found["created"]),
                         ("exact", "beispielshop", False))
        self.assertEqual((found["brand"], found["brand_source"]), ("Beispielshop", "entity.md"))
        self.assertEqual(self.calls, [])

    def test_a_new_customer_takes_its_brand_from_one_fetch(self):
        found = account.find_or_create("https://www.beispielshop.example/produkt",
                                       fetch=self.fetcher(HOMEPAGE_OG))
        self.assertEqual((found["status"], found["slug"], found["created"]),
                         ("created", "beispielshop", True))
        self.assertEqual((found["brand"], found["brand_source"]),
                         ("Beispielshop & Co", "og:site_name"))
        self.assertEqual(self.calls, ["https://www.beispielshop.example/"])
        self.assertEqual(found["drive_path"], str(self.root / "beispielshop"))
        self.assertEqual(account.brand_of("beispielshop"), "Beispielshop & Co")

    def test_the_brand_argument_skips_the_fetch(self):
        found = account.find_or_create("beispielshop.example", brand="Beispiel",
                                       fetch=self.fetcher(HOMEPAGE_OG))
        self.assertEqual((found["brand"], found["brand_source"]), ("Beispiel", "argument"))
        self.assertEqual(self.calls, [])

    def test_an_unreadable_homepage_falls_back_to_the_slug(self):
        found = account.find_or_create("beispielshop.example", fetch=self.fetcher(None))
        self.assertEqual((found["brand"], found["brand_source"]), ("beispielshop", "slug"))
        self.assertEqual(self.calls, ["https://beispielshop.example/"])

    def test_a_taken_folder_aborts_before_the_fetch(self):
        (self.root / "beispielshop").mkdir()
        with self.assertRaises(account.AccountExistsError):
            account.find_or_create("beispielshop.example", fetch=self.fetcher(HOMEPAGE_OG))
        self.assertEqual(self.calls, [])

    def test_ambiguous_creates_nothing(self):
        for slug in ("erster-kunde", "zweiter-kunde"):
            account.create(slug, slug, "beispielshop.example")
        found = account.find_or_create("beispielshop.example", fetch=self.fetcher(HOMEPAGE_OG))
        self.assertEqual((found["status"], found["created"]), ("ambiguous", False))
        self.assertEqual(sorted(os.listdir(self.root)), ["erster-kunde", "zweiter-kunde"])
        self.assertEqual(self.calls, [])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.root = support.temp_accounts_root(self)

    def run_cli(self, *args, **extra_env):
        # PTAI_ENV_FILE auf eine Datei, die es nicht gibt: der Kindprozess liest
        # sonst die zentrale Datei des Betreibers.
        environment = {**os.environ,
                       "PTAI_ENV_FILE": str(self.root.parent / "keine-zentrale.env"),
                       **extra_env}
        return subprocess.run([sys.executable, "-m", "audit.account", *args], cwd=SCRIPTS,
                              env=environment, capture_output=True, text=True, timeout=60)

    def test_create_with_a_brand_needs_no_network(self):
        result = self.run_cli("create", "https://www.beispielshop.example",
                              "--brand=Beispielshop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status:     created", result.stdout)
        self.assertIn("marke aus:  argument", result.stdout)
        self.assertIn(f"drive_path: {self.root / 'beispielshop'}", result.stdout)

    def test_a_taken_folder_exits_3_and_names_both_ways(self):
        (self.root / "beispielshop").mkdir()
        result = self.run_cli("create", "beispielshop.example", "--brand=Beispielshop")
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("beispielshop-2", result.stderr)

    def test_a_missing_configured_root_exits_4(self):
        result = self.run_cli("beispielshop.example",
                              PTAI_ACCOUNTS_ROOT=str(self.root.parent / "nicht-eingebunden"))
        self.assertEqual(result.returncode, 4, result.stdout)
        self.assertIn("PTAI_ACCOUNTS_ROOT", result.stderr)


class TestParseList(unittest.TestCase):
    """Listenfelder im Frontmatter, roh (Spec 2026-09-11 public release, C2)."""

    def test_inline(self):
        self.assertEqual(account.parse_aliases("aliases: Beispiel Shop, Muster Taschen\n"),
                         ["Beispiel Shop", "Muster Taschen"])

    def test_brackets(self):
        self.assertEqual(account.parse_aliases("aliases: [Beispiel Shop, Muster Taschen]\n"),
                         ["Beispiel Shop", "Muster Taschen"])

    def test_quotes_keep_a_comma(self):
        text = "aliases: \"Muster, Söhne & Co\", 'A, B', C\n"
        self.assertEqual(account.parse_aliases(text), ["Muster, Söhne & Co", "A, B", "C"])

    def test_an_apostrophe_inside_a_word_is_no_quote(self):
        self.assertEqual(account.parse_aliases("aliases: O'Beispiel Shop, Muster\n"),
                         ["O'Beispiel Shop", "Muster"])

    def test_block_list_ends_at_the_next_field(self):
        text = 'aliases:\n  - "Beispiel, Shop"\n  - Muster Taschen\nstatus: lead\n  - kein Alias\n'
        self.assertEqual(account.parse_aliases(text), ["Beispiel, Shop", "Muster Taschen"])

    def test_aliases_are_not_normalized_like_hosts(self):
        self.assertEqual(account.parse_aliases("aliases: WWW.Beispiel.Example/Shop\n"),
                         ["WWW.Beispiel.Example/Shop"])

    def test_missing_or_empty_field(self):
        self.assertEqual(account.parse_aliases("domains: beispielshop.example\n"), [])
        self.assertEqual(account.parse_aliases("aliases:\nstatus: lead\n"), [])

    def test_parse_list_reads_any_field(self):
        self.assertEqual(account.parse_list("tags: [a, b]\n", "tags"), ["a", "b"])

    def test_domains_still_normalize(self):
        text = 'domains: "https://www.Beispielshop.example/", b.example\n'
        self.assertEqual(account.parse_domains(text), ["beispielshop.example", "b.example"])


if __name__ == "__main__":
    unittest.main()
