#!/usr/bin/env python3
"""Shop-Technik-Snapshot aus der CLI-Antwort plus der Fremdtechnik aus dem Crawl.

Aufruf:
  shop_tech_build.py --shop <cli-antwort.json> [--crawl <crawl.json>] --out <dir>

Schreibt <out>/shop-tech.json.

Der Storefront-Teil kommt aus `crawl.json` desselben Laufs und **nicht** aus
einem zweiten Abruf: `crawl-site` besucht den Shop ohnehin und hält Skript-
Quellen und inline eingebaute Mess-IDs bereits fest. Ein zweiter Abruf sähe
womöglich einen anderen Zustand als der Crawl, gegen den die technische Analyse
rechnet, und zwei Zustände in einem Lauf sind schlimmer als einer.

Gelesen wird bevorzugt der `findings_index`, nicht `pages[]`: der Crawl ist bei
300 Seiten schon 2,7 MB groß, und hier werden Häufigkeitstabellen gebraucht,
keine Seitenliste.

Ein fehlender Block (etwa `themes: null`, weil der Scope fehlt) wird zu einem
Vermerk und nie zu einer Null. "Keine Skript-Tags installiert" und "nicht
lesbar" sind zwei verschiedene Aussagen, und nur eine davon ist ein Befund.

Nur Standardbibliothek.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

MAX_HOSTS = 100


def _index(crawl: dict, key: str) -> dict:
    return ((crawl.get("findings_index") or {}).get(key) or {})


def script_hosts(crawl: dict | None) -> dict:
    """Host je eingebundenem Fremdskript, je Host die Zahl der Seiten.

    Das Feld je Seite heißt `script_sources`, nicht `scripts`. Der bevorzugte
    Weg ist der `findings_index`; der Rückfall auf `pages[]` gilt Crawls aus
    der Zeit vor dem Index.
    """
    if not crawl:
        return {}
    indexed = _index(crawl, "script_hosts")
    if indexed:
        return dict(sorted(indexed.items(), key=lambda kv: -kv[1]))
    counts: dict = {}
    for page in crawl.get("pages") or []:
        hosts = set()
        for source in page.get("script_sources") or []:
            host = urlparse(str(source or "")).netloc
            if host:
                hosts.add(host)
        for host in hosts:
            counts[host] = counts.get(host, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def inline_tag_ids(crawl: dict | None) -> dict:
    """Inline eingebaute Container- und Mess-IDs, je ID die Zahl der Seiten.

    Genau die Zahl ist der Befund: eine ID auf drei von 300 Seiten ist ein
    Rest, eine zweite GA4-ID auf allen Seiten ist doppelte Messung. Ein Host
    sagt, dass ein Anbieter eingebunden ist, eine ID sagt **welches Konto**.
    """
    if not crawl:
        return {}
    indexed = _index(crawl, "inline_tag_ids")
    if indexed:
        return dict(indexed)
    counts: dict = {}
    for page in crawl.get("pages") or []:
        for tag_id in page.get("inline_tag_ids") or []:
            counts[tag_id] = counts.get(tag_id, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def build(answer: dict, crawl: dict | None) -> dict:
    """Die CLI-Antwort und der Crawl zu einem Snapshot."""
    notes = []
    # Mit und ohne `data`-Hülle: ein roher GraphQL-Aufruf liefert sie, die
    # Shopify CLI mit `store execute --json` nicht. Ohne diese Zeile meldet
    # jeder Block "nicht gelesen", obwohl die Antwort vollständig vorliegt.
    inner = (answer or {}).get("data")
    data = inner if isinstance(inner, dict) else (answer or {})

    def read(key, default):
        """Fehlend und leer sind zwei verschiedene Aussagen.

        Ein Block, den die Abfrage gar nicht geliefert hat (fehlender Scope,
        falscher Feldname), steht auf `null` und wird zum Vermerk. Ein Block,
        der leer zurückkommt, ist eine Messung: der Shop hat keine Skript-Tags.
        """
        if key not in data or data[key] is None:
            notes.append(
                f"Block {key!r} nicht gelesen (fehlender Scope oder Feldname). "
                "Nicht als 'nicht vorhanden' werten.")
            return default
        return data[key]

    themes = (read("themes", {}) or {}).get("nodes") or []
    main_theme = next((t for t in themes if t.get("role") == "MAIN"), None)
    script_tags = (read("scriptTags", {}) or {}).get("nodes") or []
    locales = read("shopLocales", []) or []
    markets = (read("markets", {}) or {}).get("nodes") or []
    payments = read("paymentSettings", {}) or {}

    all_hosts = script_hosts(crawl)
    # Gekappt wird erst hier, damit der Zähler im summary die volle Menge
    # nennt. Eine gekappte Liste ohne Merker erzeugt eine falsche Zahl.
    hosts = dict(list(all_hosts.items())[:MAX_HOSTS])
    tag_ids = inline_tag_ids(crawl)
    pages_scanned = None
    if crawl is not None:
        pages_scanned = (crawl.get("summary") or {}).get("pages_crawled")
        if pages_scanned is None:
            pages_scanned = len(crawl.get("pages") or [])

    return {
        "source": "shop_tech",
        "summary": {
            "themes_total": len(themes),
            "script_tags_total": len(script_tags),
            "locales_total": len(locales),
            "markets_total": len(markets),
            "third_party_script_hosts": len(all_hosts),
            "inline_tag_ids": len(tag_ids),
            # None heißt "nicht gemessen", 0 hieße "gecrawlt und nichts
            # gefunden". Der Unterschied entscheidet, ob die Analyse einen
            # Befund schreibt oder eine Lücke ausweist.
            "crawl_pages_scanned": pages_scanned,
        },
        "theme": ({"name": main_theme.get("name"), "role": main_theme.get("role"),
                    "updated_at": main_theme.get("updatedAt")} if main_theme else None),
        "themes": [{"name": t.get("name"), "role": t.get("role")} for t in themes],
        "script_tags": [{"src": t.get("src"), "display_scope": t.get("displayScope")}
                         for t in script_tags],
        "locales": locales,
        "markets": [{"name": m.get("name"), "enabled": m.get("enabled"),
                      "primary": m.get("primary")} for m in markets],
        "payments": {"supported_digital_wallets": payments.get("supportedDigitalWallets")},
        "storefront_script_hosts": hosts,
        "storefront_script_hosts_truncated": len(all_hosts) > MAX_HOSTS,
        "storefront_inline_tag_ids": tag_ids,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Shop-Technik-Snapshot bauen.")
    parser.add_argument("--shop", required=True, help="JSON-Antwort der CLI-Abfrage")
    parser.add_argument("--crawl", help="crawl.json desselben Laufs, liefert die Fremdtechnik")
    parser.add_argument("--out", required=True, help="Zielordner, reporting/data/<run-id>")
    args = parser.parse_args()

    answer = json.loads(Path(args.shop).read_text(encoding="utf-8"))
    crawl = None
    if args.crawl and Path(args.crawl).exists():
        crawl = json.loads(Path(args.crawl).read_text(encoding="utf-8"))

    snapshot = build(answer, crawl)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "shop-tech.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    theme = (snapshot["theme"] or {}).get("name", "unbekannt")
    print(f"Geschrieben: {path} (Theme: {theme}, "
          f"{snapshot['summary']['script_tags_total']} Skript-Tags, "
          f"{snapshot['summary']['third_party_script_hosts']} Fremd-Hosts, "
          f"{snapshot['summary']['inline_tag_ids']} Mess-IDs)")
    for note in snapshot["notes"]:
        print(f"  Hinweis: {note}")


if __name__ == "__main__":
    main()
