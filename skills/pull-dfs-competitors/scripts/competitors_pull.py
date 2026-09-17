#!/usr/bin/env python3
"""Wettbewerber über SERP-Überschneidung, optional die Keyword-Lücken dazu.

Aufruf:
  competitors_pull.py --target beispielshop.example --seed-keywords "a,b,c" \
      --out ... --run-id ... --run-date ... --account-slug ... --budget-cap ... \
      --location-code <code> --language-code <lang> [--with-gaps] [--sandbox]

Schreibt <out>/dfs-competitors.json.

**Gesät wird mit Keywords, nicht mit der eigenen Domain.** Der domain-seeded
Endpunkt `competitors_domain` sucht Domains mit Überschneidung im eigenen
Ranking-Set. Ist das dünn, überschneidet es sich vor allem mit den Plattformen,
auf denen die Marke ein Profil hat. In der Exploration vom 12.08.2026 kamen
dort ein soziales Netz, eine Stadt-Domain und eine Auktionsplattform heraus,
während der keyword-seeded Endpunkt 8 von 9 manuell ermittelten Wettbewerbern
fand. Genau bei der Brand, für die man Wettbewerber sucht, versagt der
domain-seeded Weg also am zuverlässigsten.

Die Liste ist ein Vorschlag für `config.json > competitors`, nicht deren
Ersatz: welche Domains als Wettbewerber gelten, ist eine Entscheidung und wird
laut Spec Abschnitt 10 mit der Baseline eingefroren. Dieser Pull schreibt nie
in die Config.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dfs_client  # noqa: E402
from audit import dfs_pull, ledger  # noqa: E402

ENDPOINT = "dataforseo_labs/google/serp_competitors/live"
ENDPOINT_GAPS = "dataforseo_labs/google/domain_intersection/live"

MAX_COMPETITORS = 20
MAX_GAPS = 300
API_LIMIT = 100

#: Domains, die im Audit keine Wettbewerber sind, auch wenn sie ranken.
#: Sie werden markiert und nicht gelöscht: dass ein Marktplatz auf den
#: Kategorie-Keywords vor der Brand steht, ist selbst ein Befund.
PLATFORM_DOMAINS = (
    "instagram.com", "facebook.com", "youtube.com", "pinterest.de",
    "pinterest.com", "tiktok.com", "amazon.de", "amazon.com", "ebay.de",
    "etsy.com", "otto.de", "kaufland.de", "wikipedia.org",
)


def _normalize(domain) -> str:
    """Domain vergleichbar machen: klein, ohne führendes www."""
    text = str(domain or "").strip().lower()
    return text[4:] if text.startswith("www.") else text


def _is_platform(domain: str) -> bool:
    name = _normalize(domain)
    return any(name == p or name.endswith("." + p) for p in PLATFORM_DOMAINS)


def payload(args) -> dict:
    return {
        "keywords": [k.strip() for k in args.seed_keywords.split(",") if k.strip()],
        "location_code": args.location_code,
        "language_code": args.language_code,
        "limit": API_LIMIT,
    }


def gap_payload(target: str, competitor: str, *, location_code: int,
                language_code: str, limit: int = API_LIMIT) -> dict:
    """Die Aufgabe für die Keyword-Lücken. **Die Reihenfolge ist der Inhalt.**

    `intersections: false` liefert Keywords, für die **target1** rankt und
    target2 nicht. Eine Content-Lücke ist "der Wettbewerber rankt, wir nicht",
    also steht der Wettbewerber auf `target1` und die eigene Domain auf
    `target2`. Vertauscht liefert derselbe Aufruf die eigenen Stärken, und die
    landen dann unter der Überschrift "Keyword-Lücken" im Report.
    """
    return {"target1": competitor, "target2": target, "intersections": False,
            "location_code": location_code, "language_code": language_code,
            "limit": limit}


def shape(rows: list, meta: dict) -> dict:
    """Wettbewerberliste ohne die eigene Domain, stärkste zuerst.

    Sortiert wird nach durchschnittlicher Position, nicht nach der Reihenfolge
    der API: der Audit will die stärksten zuerst, und wer sich auf die
    API-Reihenfolge verlässt, bekommt sie irgendwann anders und merkt es nicht.
    Eine Domain ohne Position sortiert ans Ende statt an den Anfang.
    """
    own = _normalize(meta.get("target"))
    block = dfs_pull.unwrap(rows)
    competitors = []
    for entry in block.get("items") or []:
        if own and _normalize(entry.get("domain")) == own:
            continue
        competitors.append({
            "domain": entry.get("domain"),
            "avg_position": entry.get("avg_position"),
            "median_position": entry.get("median_position"),
            "rating": entry.get("rating"),
            "etv": entry.get("etv"),
            "keywords_count": entry.get("keywords_count"),
            "visibility": entry.get("visibility"),
            "is_platform": _is_platform(entry.get("domain")),
        })
    competitors.sort(key=lambda c: (c["avg_position"] is None, c["avg_position"] or 0))

    shops = [c for c in competitors if not c["is_platform"]]
    notes = []
    if competitors and not shops:
        notes.append(
            "Nur Plattformen unter den Treffern, kein einziger Shop. Das ist "
            "kein Wettbewerbsbild, sondern ein Hinweis auf zu markenlastige "
            "Seed-Keywords: mit Kategorie-Begriffen erneut säen."
        )
    listed, truncated = dfs_pull.truncate(competitors, MAX_COMPETITORS)
    return {
        "summary": {
            # Drei verschiedene Zahlen, und alle drei stehen da: total_count
            # ist der Bestand, items_count die Liefermenge der API, und
            # `competitors_truncated` sagt nur, ob **wir** noch gekürzt haben.
            # Ohne die mittlere Zahl liest sich "84 gefunden, 20 gelistet,
            # nicht gekürzt" wie ein Widerspruch.
            "competitors_found": block.get("total_count"),
            "competitors_delivered": block.get("items_count"),
            "competitors_without_platforms": len(shops),
            "seed_keywords": block.get("seed_keywords"),
        },
        "competitors": listed,
        "competitors_truncated": truncated,
        "notes": notes,
    }


def shape_gaps(rows: list, meta: dict) -> dict:
    """Keywords, auf denen der Wettbewerber rankt und die eigene Domain nicht.

    Gelesen wird `first_domain_serp_element`, also die Position des
    Wettbewerbers. `second_domain_serp_element` ist bei `intersections: false`
    immer `null`, weil die eigene Domain dort gerade nicht rankt: wer es liest,
    bekommt eine Spalte, die in jeder Zeile leer ist.

    Sortiert nach Suchvolumen, absteigend. Eine Lücke ohne Volumen sortiert ans
    Ende, sie ist keine Priorität.
    """
    block = dfs_pull.unwrap(rows)
    gaps = []
    for entry in block.get("items") or []:
        data = entry.get("keyword_data") or {}
        element = entry.get("first_domain_serp_element") or {}
        gaps.append({
            "keyword": data.get("keyword"),
            "search_volume": (data.get("keyword_info") or {}).get("search_volume"),
            "competitor_rank": element.get("rank_absolute"),
            "competitor_url": element.get("url"),
        })
    gaps.sort(key=lambda g: (g["search_volume"] is None, -(g["search_volume"] or 0)))
    listed, truncated = dfs_pull.truncate(gaps, MAX_GAPS)
    return {
        "keyword_gaps": listed,
        "keyword_gaps_truncated": truncated,
        "summary_gaps": {
            "keyword_gaps_found": block.get("total_count"),
            "keyword_gaps_delivered": block.get("items_count"),
            "compared_against": block.get("target1"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wettbewerber über SERP-Überschneidung der Kategorie-Keywords ziehen.")
    parser.add_argument("--target", required=True, help="Domain ohne Protokoll")
    parser.add_argument("--seed-keywords", required=True,
                        help="Kategorie-Keywords aus config.json > geo_queries.category, "
                             "kommagetrennt. Markenbegriffe gehören nicht hierher")
    parser.add_argument("--with-gaps", action="store_true",
                        help="zusätzlich die Keyword-Lücken zum stärksten Wettbewerber "
                             "(eigener Endpunkt, rund 0,016 USD)")
    dfs_pull.add_common_args(parser)
    args = parser.parse_args()

    if not payload(args)["keywords"]:
        sys.exit("Fehler: keine Seed-Keywords. Ohne Kategorie-Begriffe gibt es "
                 "nichts zu säen, und ein leerer Aufruf kostet trotzdem.")

    client = dfs_pull.build_client(args)
    common = dict(
        workspace=Path(args.workspace), out=Path(args.out), run_id=args.run_id,
        run_date=date.fromisoformat(args.run_date), account_slug=args.account_slug,
        cap=args.budget_cap, pull="competitors")
    try:
        path = dfs_pull.execute(
            client, endpoint=ENDPOINT, task=payload(args),
            shape=lambda rows, meta: shape(rows, {**meta, "target": args.target}),
            **common)
    except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
        sys.exit(f"Fehler: Wettbewerber-Pull nicht möglich: {exc}")
    print(f"Geschrieben: {path}")

    if not args.with_gaps:
        return
    # Die Lücken brauchen einen benannten Gegner, und zwar einen Shop. Gegen
    # eine Plattform gerechnet ist die Liste wertlos.
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    shops = [c for c in snapshot.get("competitors") or [] if not c.get("is_platform")]
    if not shops:
        print("Warnung: kein Shop unter den Wettbewerbern, Keyword-Lücken übersprungen")
        return
    strongest = shops[0]["domain"]
    try:
        dfs_pull.execute(
            client, endpoint=ENDPOINT_GAPS, shape=shape_gaps, merge=True,
            task=gap_payload(args.target, strongest, location_code=args.location_code,
                              language_code=args.language_code),
            **common)
        print(f"Keyword-Lücken gegen {strongest} ergänzt")
    except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
        print(f"Warnung: Keyword-Lücken nicht gezogen ({exc})")


if __name__ == "__main__":
    main()
