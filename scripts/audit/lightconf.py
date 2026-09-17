#!/usr/bin/env python3
"""Lauf-Config für audit-light aus Shop-URL und Account bauen (Spec Abschnitt 5.1.1).

Der große Audit liest eine dauerhafte `reporting/config.json` aus dem
Kunden-Workspace. audit-light hat keinen Workspace: ein kalter Lead hat keinen,
und er hat auch keine Shopify-, GA4- oder Search-Console-Zugänge, ohne die
`config.validate()` gar nicht erst durchliefe. Deshalb baut dieses Modul eine
eigene, flüchtige `run-config.json` im Lauf-Ordner. Sie geht bewusst **nicht**
durch `config.validate()`: die dortige Pflichtfeldliste beschreibt einen Kunden
mit Zugängen, nicht einen Lead mit einer URL.

Sie deckt genau das ab, was die vier kostenlosen Pulls an Inhalt brauchen:

    check-geo        brand, domain, geo_queries (drei Gruppen), geo_method, competitors
    pull-cwv         page_types
    capture-screens  account_slug, drive_path, checkout_capture
    crawl-site       domain

Zwei Stufen, weil eine davon erst nach dem Crawl beantwortbar ist:

    build()                  vor dem Crawl. Alles, was aus URL und Account folgt.
    add_page_types()         nach dem Crawl. Die sechs Seitentypen aus crawl.json.

Was dieses Modul NICHT rät: die Kategorie- und Problem-Fragen für die
GEO-Messung. Welche Begriffe eine Marktnische treffen, entscheidet kein Muster
über URLs. Das heißt aber nicht, dass ein Mensch gefragt werden muss: der
Orchestrator liest sie aus dem Crawl ab, also aus Titel, Beschreibung und
Kategorienamen des Shops, und setzt sie über `set_geo_queries()`. `build()` legt
nur die Markengruppe deterministisch an. Die gesetzten Fragen gehören sichtbar in
den Report unter Quellen und Methodik: eine falsche Kategoriefrage misst die
falsche Sichtbarkeit, und das fiele sonst niemandem auf.

CLI: python3 -m audit.lightconf <shop-url> --slug <account-slug> [--out <datei>]
"""
import json
import os
import re
import sys

from audit import account

#: Reihenfolge ist die Anzeigereihenfolge im Report. Deckungsgleich mit
#: `config.PAGE_TYPES_DEFAULT`, damit ein Lauf von audit-light und einer von
#: audit dieselben sechs Typen meinen.
PAGE_TYPES = ("start", "collection", "product", "cart", "search", "blog")

#: Erkennungsmuster je Seitentyp, in Prüfreihenfolge. Bewusst grob: sie müssen
#: über Shopify, WooCommerce und Eigenbauten hinweg tragen und dabei eher nichts
#: als das Falsche liefern. Ein nicht erkannter Typ bleibt None und wird im
#: Datenlage-Blatt als Lücke ausgewiesen, statt still eine falsche URL zu messen.
_PATTERNS = {
    "collection": (r"/collections?/", r"/kategorie", r"/categor", r"/produkte(?:/|$)", r"/shop/"),
    "product":    (r"/products?/", r"/artikel/", r"/p/\w", r"/produkt/"),
    "cart":       (r"/cart(?:/|$|\?)", r"/warenkorb", r"/basket"),
    "search":     (r"/search(?:/|$|\?)", r"/suche", r"/suchergebnis"),
    "blog":       (r"/blogs?/", r"/magazin", r"/ratgeber", r"/journal", r"/news(?:/|$)"),
}

#: Sammelseiten, die zwar auf ein Muster passen, aber nicht repräsentativ sind.
#: Zwei Sorten: leere Übersichten (`/collections/`) und die Alles-Seite
#: (`/collections/all`), die jeder Shopify-Shop hat. Letztere ist der häufigere
#: Fall und der irreführendere: sie ist eine echte Seite mit Produkten, aber
#: keine Kategorie. Wer sie als Beispiel-PLP misst, prüft Filter und
#: Kategorietext an der einen Seite, die beides nie hat.
_UNSPECIFIC = (r"/collections/?$", r"/collections/all/?$", r"/products/?$",
               r"/blogs/?$", r"/shop/?$", r"/collections/alle-produkte/?$")


def _is_unspecific(path: str) -> bool:
    return any(re.search(p, path) for p in _UNSPECIFIC)


def _path_of(url: str) -> str:
    return "/" + re.sub(r"^[a-z]+://[^/]+/?", "", str(url or "").lower())


def pick_page_types(urls, domain: str) -> dict[str, str | None]:
    """Wählt je Seitentyp eine repräsentative URL aus einer Crawl-Liste.

    Kriterium bei mehreren Kandidaten ist die geringste Pfadtiefe und danach die
    kürzere URL: die flachste Produktseite ist eher eine gewöhnliche als ein
    Sonderfall tief in einer Kampagnenstruktur. Der Typ `start` ist immer die
    Domain selbst, dafür braucht es keinen Kandidaten.
    """
    result: dict[str, str | None] = {t: None for t in PAGE_TYPES}
    result["start"] = domain.rstrip("/") + "/" if domain else None

    kandidaten: dict[str, list[str]] = {t: [] for t in _PATTERNS}
    for url in urls or []:
        path = _path_of(url)
        if _is_unspecific(path):
            continue
        for typ, muster in _PATTERNS.items():
            if any(re.search(m, path) for m in muster):
                kandidaten[typ].append(str(url))
                break

    for typ, items in kandidaten.items():
        if items:
            result[typ] = sorted(items, key=lambda u: (_path_of(u).count("/"), len(u)))[0]
    return result


def brand_queries(brand: str, domain: str) -> list[str]:
    """Die Markengruppe für die GEO-Messung, deterministisch aus dem Markennamen.

    Drei Fragen, die eine KI beantworten kann, ohne die Marke zu kennen: was ist
    das, taugt das, wo kauft man das. Rechtsformzusätze und Klammerzusätze fallen
    weg, weil niemand "Beispiel GmbH (Marke X) Erfahrungen" fragt.
    """
    name = re.sub(r"\s*\([^)]*\)\s*$", "", brand or "").strip()
    name = re.sub(r"\s+(GmbH|AG|UG|KG|GmbH & Co\. KG|e\.K\.|GbR|Ltd\.?|Inc\.?)\s*$", "", name,
                  flags=re.I).strip()
    if not name:
        name = (domain or "").split(".")[0]
    return [
        f"Was ist {name}?",
        f"Ist {name} zu empfehlen? Erfahrungen und Bewertungen",
        f"Wo kann man Produkte von {name} kaufen?",
    ]


def build(shop_url: str, slug: str, *, brand: str | None = None,
          with_dfs: bool = False, checkout_path: bool = False,
          audit_id: str | None = None) -> dict:
    """Die Lauf-Config vor dem Crawl.

    `page_types` enthält nur `start`; die übrigen fünf füllt `add_page_types()`
    nach dem Crawl. `geo_queries.category` und `.problem` bleiben leer und werden
    vom Orchestrator gesetzt, siehe Modul-Docstring.
    """
    # Der Host fuer die Account-Suche und die Domain fuer den Lauf sind zwei
    # verschiedene Dinge. `normalize_host` wirft `www.` weg, damit ein Account
    # mit `shop.de` auch `www.shop.de` findet. Als Lauf-Domain waere das falsch:
    # beispielshop.example leitet auf www.beispielshop.example um, und ein Crawl oder eine
    # CWV-Messung auf die Nicht-www-Form misst die Weiterleitung mit.
    host = account.normalize_host(shop_url)
    raw = str(shop_url or "").strip()
    if raw and not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    domain = re.sub(r"/+$", "", raw.split("?")[0].split("#")[0]) if raw else ""
    brand = brand or account.brand_of(slug)

    return {
        "brand": brand,
        "domain": domain,
        # Die Supabase-Zeile, aus der dieser Lauf stammt. Ohne sie findet
        # audit-light-send den Empfaenger nicht mehr, und der Lauf laesst sich
        # nicht mehr dem Funnel-Lead zuordnen, aus dem er kam.
        "audit_id": audit_id,
        "account_slug": slug,
        "drive_path": account.drive_path(slug),
        "page_types": {"start": domain + "/" if domain else None},
        "geo_queries": {"brand": brand_queries(brand, host), "category": [], "problem": []},
        "geo_method": "api",
        "competitors": [],
        "checkout_capture": checkout_path,
        "sources": {
            "crawl": True, "screens": True, "cwv": True, "geo": True,
            "dfs_rankings": with_dfs, "competitors": with_dfs, "shopping": with_dfs,
            "dfs_keywords": with_dfs, "backlinks": with_dfs,
            # Kundenzugänge. Ein Lead hat sie nicht, und das ist kein Fehler,
            # sondern die Definition dieses Laufs.
            "shopify": False, "catalogue": False, "shop_tech": False,
            "ga4": False, "gsc": False, "ads": False,
        },
    }


def add_page_types(cfg: dict, crawl_json: str) -> dict:
    """Ergänzt die Seitentypen aus dem Crawl-Snapshot. Fehlt er, bleibt es bei `start`."""
    try:
        with open(crawl_json, encoding="utf-8") as fh:
            crawl = json.load(fh)
    except (OSError, ValueError):
        return cfg
    urls = [p.get("url") for p in crawl.get("pages", []) if isinstance(p, dict)]
    cfg["page_types"] = pick_page_types(urls, cfg.get("domain", ""))
    return cfg


def set_geo_queries(cfg: dict, category: list[str], problem: list[str]) -> dict:
    """Setzt die beiden Gruppen, die ein Mensch oder Agent entscheiden muss.

    Die Markengruppe bleibt unangetastet. Beide Listen werden auf je drei Fragen
    gekappt: check-geo empfiehlt höchstens acht Fragen gesamt, und jede Frage
    kostet drei API-Aufrufe.
    """
    cfg.setdefault("geo_queries", {})
    cfg["geo_queries"]["category"] = [q for q in (category or []) if q][:3]
    cfg["geo_queries"]["problem"] = [q for q in (problem or []) if q][:3]
    return cfg


def missing(cfg: dict) -> list[str]:
    """Was fehlt, bevor der Lauf weiterlaufen darf. Leere Liste heißt: vollständig.

    Absichtlich kurz. Das ist keine zweite `validate()`, sondern die Prüfung, ob
    die Felder gesetzt sind, die dieses Modul selbst erzeugt.
    """
    fehlt = []
    for feld in ("brand", "domain", "account_slug", "drive_path"):
        if not cfg.get(feld):
            fehlt.append(feld)
    gq = cfg.get("geo_queries") or {}
    if cfg.get("sources", {}).get("geo") and not gq.get("category"):
        fehlt.append("geo_queries.category (vom Orchestrator zu setzen)")
    # Nicht die None-Werte zaehlen: direkt nach build() hat page_types ueberhaupt
    # nur den Schluessel `start`, und der ist gesetzt. Es zaehlt, ob ausser der
    # Startseite irgendein Typ steht, denn nur die kommen aus dem Crawl.
    pages = cfg.get("page_types") or {}
    if not any(url for typ, url in pages.items() if typ != "start"):
        fehlt.append("page_types (crawl-site zuerst laufen lassen)")
    return fehlt


def write(cfg: dict, path: str) -> str:
    """Schreibt die Config in den Lauf-Ordner und legt fehlende Ordner an."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


if __name__ == "__main__":
    argv = sys.argv[1:]
    positional = [a for a in argv if not a.startswith("--")]
    opt = lambda n: next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{n}=")), None)
    if not positional:
        print("Aufruf: python3 -m audit.lightconf <shop-url> --slug=<account> [--out=<datei>]",
              file=sys.stderr)
        raise SystemExit(1)

    slug = opt("slug")
    if not slug:
        found = account.resolve(positional[0])
        if not found["slug"]:
            print(f"Kein Kunde für {found['host']} ({found['status']}). --slug=<ordner> "
                  f"angeben oder den Kunden anlegen: python3 -m audit.account create "
                  f"{positional[0]}", file=sys.stderr)
            raise SystemExit(2)
        slug = found["slug"]

    cfg = build(positional[0], slug,
                with_dfs="--with-dfs" in argv, checkout_path="--checkout" in argv)
    goal = opt("out")
    if goal:
        write(cfg, goal)
        print(f"geschrieben: {goal}")
    else:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    for f in missing(cfg):
        print(f"offen: {f}", file=sys.stderr)
