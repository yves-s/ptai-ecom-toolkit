#!/usr/bin/env python3
"""Katalog-Snapshot aus den Rohseiten der Shopify-CLI-Abfrage.

Aufruf:
  catalog_build.py --pages <raw.json> [--collections <raw.json>] --out <dir>

Liest die gesammelten GraphQL-Antwortseiten, die die Skill über
`shopify store execute` geholt hat, und schreibt <out>/catalog.json.

Drei Regeln tragen dieses Script:

1. **Kein Fließtext im Snapshot.** Aus der Produktbeschreibung wird ihre
   Länge, nicht ihr Inhalt. Der erste echte Lauf hat `shopify.json` auf 1,3 MB
   gebracht und `crawl.json` auf 2,7 MB bei 300 Seiten; ein Katalog mit 2.000
   Produkten samt Texten ist derselbe Fall. Aggregat plus gekappte Beispiele,
   Rohdaten nur für gezielte Abfragen.
2. **Kein Urteil.** Das Script zählt und misst, es entscheidet nicht, was
   "dünn" ist. Es liefert die Längenverteilung, die Schwelle steht im
   Kennzahlen-Katalog und gehört der Analyse.
3. **Eine fehlende Struktur ist kein leerer Katalog.** Fehlt ein Feld in allen
   Produkten, war die Abfrage falsch. Ohne diese Prüfung meldet der Snapshot
   "kein Produkt hat SEO-Felder" für einen Shop, der sie pflegt, und das ist
   genau die Sorte Zahl, die niemandem auffällt.

Nur Standardbibliothek.
"""
import argparse
import json
import math
from pathlib import Path

#: Obergrenze jeder Beispielliste im Snapshot.
MAX_LIST = 200

#: Felder, die die Abfrage je Produkt liefern muss. Fehlt eins in **allen**
#: Produkten, ist nicht der Katalog leer, sondern die Query unvollständig.
REQUIRED_PRODUCT_FIELDS = ("seo", "images", "variants", "description")


def _wurzel(page: dict) -> dict:
    """Die Nutzlast einer Antwortseite, mit und ohne `data`-Hülle.

    Ein roher GraphQL-Aufruf über HTTP liefert `{"data": {"products": …}}`, die
    Shopify CLI mit `store execute --json` dagegen `{"products": …}` ohne die
    Hülle. Wer nur die eine Form kennt, bekommt von der anderen null Knoten
    zurück, meldet Erfolg und schreibt einen leeren Snapshot. Genau das ist am
    07.09.2026 im ersten vollständigen Lauf passiert: 0 Produkte aus mehreren tausend,
    Exit-Code 0, keine Fehlermeldung.
    """
    if not isinstance(page, dict):
        return {}
    inner = page.get("data")
    return inner if isinstance(inner, dict) else page


def products_from_pages(pages: list) -> list:
    """Alle Produktknoten aus einer Folge von GraphQL-Antwortseiten."""
    products = []
    for page in pages:
        products.extend((_wurzel(page).get("products") or {}).get("nodes") or [])
    return products


def collections_from_pages(pages: list) -> list:
    collections = []
    for page in pages:
        collections.extend((_wurzel(page).get("collections") or {}).get("nodes") or [])
    return collections


def check_shape(products: list) -> list:
    """Meldet Felder, die in keinem einzigen Produkt vorkommen.

    Einzelne Produkte ohne SEO-Felder sind normal und ein Befund. Ein Feld,
    das **nirgends** vorkommt, ist dagegen kein Befund über den Shop, sondern
    ein Fehler in der Abfrage: die Namen der Admin-GraphQL ändern sich mit der
    API-Version, und eine falsch benannte Verschachtelung liefert `null` statt
    eines Fehlers.
    """
    if not products:
        return []
    notes = []
    for field in REQUIRED_PRODUCT_FIELDS:
        if not any(field in product for product in products):
            notes.append(
                f"Feld {field!r} kommt in keinem der {len(products)} Produkte vor. "
                "Das ist kein leerer Katalog, sondern eine unvollständige "
                "Abfrage: Feldnamen gegen die Admin-GraphQL der eingesetzten "
                "API-Version prüfen und erneut ziehen."
            )
    return notes


def _has_text(value) -> bool:
    """Text vorhanden? Leerstring und Leerzeichen zählen nicht.

    Shopify liefert fehlende Felder mal als `null`, mal als `""`. Beides heißt
    dasselbe, und wer nur auf `null` prüft, meldet eine zu kleine Lücke.
    """
    return bool(str(value or "").strip())


def flatten(product: dict) -> dict:
    """Ein Produkt auf die Zähler eindampfen, die der Snapshot braucht."""
    seo = product.get("seo") or {}
    images = (product.get("images") or {}).get("nodes") or []
    variants = (product.get("variants") or {}).get("nodes") or []
    # unitCost `null` heißt "cost per item nicht gepflegt". 0.00 ist ein
    # gepflegter Wert (Zugabe, Werbeartikel) und keine Lücke.
    without_cost = sum(
        1 for variant in variants
        if ((variant.get("inventoryItem") or {}).get("unitCost") or {}).get("amount") is None)
    prices = []
    for variant in variants:
        try:
            prices.append(float(variant.get("price")))
        except (TypeError, ValueError):
            # Ein Preis, den niemand lesen kann, darf die Spanne nicht auf 0
            # ziehen. Dann sieht der Shop aus, als verschenke er Ware.
            continue
    return {
        "handle": product.get("handle"),
        "title": product.get("title"),
        "status": product.get("status"),
        "product_type": product.get("productType"),
        "vendor": product.get("vendor"),
        "description_length": len(product.get("description") or ""),
        "seo_title": _has_text(seo.get("title")),
        "seo_description": _has_text(seo.get("description")),
        "images": len(images),
        "images_with_alt": sum(1 for image in images if _has_text(image.get("altText"))),
        "variants": len(variants),
        "variants_without_sku": sum(1 for v in variants if not _has_text(v.get("sku"))),
        "variants_without_cost": without_cost,
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
    }


def _percentile(values: list, share: float):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


def _capped(rows: list, key: str) -> dict:
    return {key: [row["handle"] for row in rows][:MAX_LIST],
            f"{key}_truncated": len(rows) > MAX_LIST}


def build(products: list, collections: list, shape_notes: list | None = None) -> dict:
    """Der Snapshot: summary mit vollen Zählern, Listen begrenzt."""
    images_total = sum(p["images"] for p in products)
    images_with_alt = sum(p["images_with_alt"] for p in products)
    variants_total = sum(p["variants"] for p in products)
    lengths = [p["description_length"] for p in products]

    missing_seo_title = [p for p in products if not p["seo_title"]]
    missing_seo_description = [p for p in products if not p["seo_description"]]
    missing_alt = [p for p in products if p["images"] and p["images_with_alt"] < p["images"]]
    missing_image = [p for p in products if not p["images"]]
    missing_cost = [p for p in products if p["variants_without_cost"]]

    summary = {
        "products_total": len(products),
        "products_active": sum(1 for p in products if p["status"] == "ACTIVE"),
        "products_without_seo_title": len(missing_seo_title),
        "products_without_seo_description": len(missing_seo_description),
        "products_without_description": sum(1 for p in products if p["description_length"] == 0),
        "products_without_image": len(missing_image),
        "products_with_missing_alt": len(missing_alt),
        "description_length_p10": _percentile(lengths, 0.10),
        "description_length_p50": _percentile(lengths, 0.50),
        "description_length_p90": _percentile(lengths, 0.90),
        "images_total": images_total,
        "images_with_alt": images_with_alt,
        # Ohne Bilder gibt es keinen Anteil. None statt 0, weil eine 0 sich als
        # "kein Bild hat einen Alt-Text" liest und das ein erfundener Befund
        # wäre.
        "share_images_with_alt": (round(images_with_alt / images_total, 4)
                                   if images_total else None),
        "variants_total": variants_total,
        "variants_without_sku": sum(p["variants_without_sku"] for p in products),
        "variants_without_cost": sum(p["variants_without_cost"] for p in products),
        "collections_total": len(collections),
        "collections_without_description": sum(
            1 for c in collections if not _has_text(c.get("description"))),
    }
    result = {"source": "catalogue", "summary": summary,
              "notes": list(shape_notes or [])}
    result.update(_capped(missing_seo_title, "products_without_seo_title"))
    result.update(_capped(missing_seo_description, "products_without_seo_description"))
    result.update(_capped(missing_alt, "products_with_missing_alt"))
    result.update(_capped(missing_cost, "products_without_cost"))
    # Spec Abschnitt 19: Marge nur, wenn `cost per item` gepflegt ist.
    #
    # Bis 07.09.2026 stand hier Gleichheit statt einer Schwelle. Ein Shop, bei
    # dem jede Variante bis auf eine den Einkaufspreis vermisste, bekam keinen
    # Hinweis: eine einzige gepflegte Variante schaltete die Warnung ab,
    # obwohl die Marge faktisch nicht berechenbar war. Der Anteil entscheidet,
    # nicht der Einzelfall, und er steht im Hinweis, damit niemand raten muss.
    if variants_total:
        ohne = summary["variants_without_cost"]
        share = ohne / variants_total
        if share >= 0.9:
            # Abgerundet, nie kaufmaennisch gerundet. Jede Variante bis auf
            # eine sind bei grossen Katalogen 99,99 Prozent, und `.1f` macht
            # daraus "100.0 Prozent": eine
            # Vollerhebung, die es nicht gibt. Die eine gepflegte Variante ist
            # der Unterschied zwischen "nicht berechenbar" und "niemand hat es
            # je gepflegt", und der Satz steht so im Kundenreport.
            prozent = math.floor(share * 1000) / 10
            wie_viele = ("Keine einzige Variante hat einen Einkaufspreis"
                         if ohne == variants_total
                         else f"{ohne} von {variants_total} Varianten "
                              f"({prozent:.1f} Prozent) haben keinen Einkaufspreis")
            result["notes"].append(
                f"{wie_viele}. Marge und Deckungsbeitrag sind für diesen Shop "
                f"nicht berechenbar.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Katalog-Snapshot aus den CLI-Rohseiten bauen.")
    parser.add_argument("--pages", required=True,
                        help="JSON-Datei mit der Liste der Produkt-Antwortseiten")
    parser.add_argument("--collections", help="dasselbe für Collections")
    parser.add_argument("--out", required=True, help="Zielordner, reporting/data/<run-id>")
    args = parser.parse_args()

    pages = json.loads(Path(args.pages).read_text(encoding="utf-8"))
    collection_pages = (json.loads(Path(args.collections).read_text(encoding="utf-8"))
                        if args.collections else [])
    raw_products = products_from_pages(pages)
    snapshot = build([flatten(p) for p in raw_products],
                      collections_from_pages(collection_pages),
                      shape_notes=check_shape(raw_products))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "catalog.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Geschrieben: {path} ({snapshot['summary']['products_total']} Produkte, "
          f"{snapshot['summary']['variants_total']} Varianten)")
    for note in snapshot["notes"]:
        print(f"  Hinweis: {note}")


if __name__ == "__main__":
    main()
