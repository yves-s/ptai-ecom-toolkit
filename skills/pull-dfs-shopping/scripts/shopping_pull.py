#!/usr/bin/env python3
"""Google-Shopping-Präsenz und Preisvergleich über die DataForSEO Merchant API.

Aufruf:
  shopping_pull.py --keywords "laufschuhe,laufjacke" --brand beispielshop \
      --out ... --run-id ... --run-date ... --account-slug ... --budget-cap ... \
      --location-code <code> --language-code <lang> [--sandbox]

Schreibt <out>/dfs-shopping.json.

Der einzige task-basierte Pull: `task_post` legt je Keyword eine Aufgabe an,
danach wird gewartet und mit `task_get/advanced` abgeholt. Ein `task_post`
kostet (rund 0,001 USD je Aufgabe), das Abholen nicht: deshalb steht im Ledger
eine Zeile je Post und keine je Abholung.

Ob ein Angebot das eigene ist, entscheidet der Markenname aus `config.json >
brand` gegen das Verkäuferfeld. Das ist eine Heuristik und steht als solche im
Snapshot: ein Shop, der unter mehreren Namen verkauft, wird hier unterzählt.
"""
import argparse
import json
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dfs_client  # noqa: E402
from audit import dfs_pull, ledger  # noqa: E402

ENDPOINT_POST = "merchant/google/products/task_post"
ENDPOINT_GET = "merchant/google/products/task_get/advanced"

MAX_OFFERS = 20
MAX_KEYWORDS = 20

#: Nur dieser Typ ist ein Angebot. `google_shopping_carousel` sind
#: Kategoriekacheln ohne Preis und Verkäufer; in der aufgezeichneten Antwort
#: waren 3 von 43 Einträgen solche Kacheln. Mitgezählt blähen sie die
#: Angebotszahl auf und verwässern die Aussage "kein eigenes Angebot".
OFFER_TYPE = "google_shopping_serp"

#: Wartezeit zwischen zwei Abholversuchen und ihre Obergrenze. Eine Aufgabe,
#: die nach zehn Minuten nicht fertig ist, wird als fehlend vermerkt statt den
#: Run aufzuhalten.
POLL_SECONDS = 20
POLL_ATTEMPTS = 30


def task_ids(payload: dict) -> list:
    """(id, keyword) je angenommener Aufgabe. Abgelehnte fallen raus.

    Eine abgelehnte Aufgabe ohne Ergebnis würde sonst dreißigmal abgefragt und
    hielte den Lauf zehn Minuten auf, ohne dass je etwas käme.
    """
    result = []
    for task in payload.get("tasks") or []:
        if task.get("status_code") not in dfs_client.STATUS_OK:
            print(f"Warnung: Aufgabe abgelehnt ({task.get('status_code')}: "
                  f"{task.get('status_message')})")
            continue
        result.append((task.get("id"), (task.get("data") or {}).get("keyword")))
    return result


def _is_own(seller, brand) -> bool:
    """Heuristik: Markenname im Verkäufernamen, ohne Rücksicht auf Schreibung."""
    if not brand:
        return False
    return str(brand).strip().lower() in str(seller or "").lower()


def shape(rows: list, meta: dict) -> dict:
    """Angebote je Keyword plus Preisabstand zum Median der übrigen Anbieter."""
    brand = meta.get("brand")
    keywords, own_total, foreign_total, carousel_total = [], 0, 0, 0
    currencies = set()

    for block in rows:
        offers, own_prices, foreign_prices = [], [], []
        for item in block.get("items") or []:
            if item.get("type") != OFFER_TYPE:
                carousel_total += 1
                continue
            price = item.get("price")
            if item.get("currency"):
                currencies.add(item["currency"])
            own = _is_own(item.get("seller"), brand)
            if own:
                own_total += 1
                if price is not None:
                    own_prices.append(float(price))
            else:
                foreign_total += 1
                if price is not None:
                    foreign_prices.append(float(price))
            offers.append({
                "seller": item.get("seller"), "title": item.get("title"),
                "price": price, "currency": item.get("currency"),
                "old_price": item.get("old_price"),
                "rank_absolute": item.get("rank_absolute"), "own": own,
            })
        listed, truncated = dfs_pull.truncate(offers, MAX_OFFERS)
        # Ohne eigenes Angebot gibt es keinen Preisabstand. None statt 0, weil
        # eine 0 sich als "gleich teuer wie der Markt" liest. Verglichen wird
        # das günstigste eigene Angebot, weil das der Kunde zuerst sieht.
        delta = None
        if own_prices and foreign_prices:
            delta = round(min(own_prices) - statistics.median(foreign_prices), 2)
        keywords.append({
            "keyword": block.get("keyword"),
            "offers": listed,
            "offers_truncated": truncated,
            "offers_total": len(offers),
            "own_price_vs_median": delta,
        })

    notes = ["Eigene Angebote werden über den Markennamen im Verkäuferfeld "
             "erkannt. Ein Shop, der unter mehreren Namen verkauft, wird dabei "
             "unterzählt."]
    if len(currencies) > 1:
        # Ein Preisvergleich über zwei Währungen ist keine Zahl.
        notes.append(f"Mehrere Währungen in den Angeboten: {sorted(currencies)}. "
                      "Der Preisabstand ist dann nicht vergleichbar.")
    return {
        "summary": {
            "keywords_checked": len(rows),
            "offers_total": own_total + foreign_total,
            "own_offers": own_total,
            "competitor_offers": foreign_total,
            "carousel_entries": carousel_total,
            "currencies": sorted(currencies),
            "brand_match": brand,
        },
        "keywords": keywords,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google-Shopping-Präsenz als Snapshot ziehen.")
    parser.add_argument("--keywords", required=True,
                        help="Keywords, kommagetrennt, höchstens 20")
    parser.add_argument("--brand", required=True,
                        help="Markenname aus config.json, erkennt die eigenen Angebote")
    dfs_pull.add_common_args(parser)
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()][:MAX_KEYWORDS]
    if not keywords:
        sys.exit("Fehler: keine Keywords angegeben")

    client = dfs_pull.build_client(args)
    workspace, run_id = Path(args.workspace), args.run_id
    tag = ledger.build_tag(args.account_slug, date.fromisoformat(args.run_date), "shopping")

    # Ein task_post nimmt mehrere Aufgaben und kostet je Aufgabe. Der Deckel
    # wird deshalb einmal gegen die Summe geprüft, nicht je Keyword.
    ledger.check_budget(workspace, run_id, cap=args.budget_cap,
                        estimate=dfs_pull.ESTIMATE_USD["shopping"] * len(keywords))
    tasks = [{"keyword": keyword, "location_code": args.location_code,
              "language_code": args.language_code, "tag": tag} for keyword in keywords]
    try:
        posted = client.post(ENDPOINT_POST, tasks)
    except dfs_client.DfsError as exc:
        sys.exit(f"Fehler: Shopping-Aufgaben nicht angelegt: {exc}")

    ledger.append(workspace, {
        "run_id": run_id, "pull": "shopping", "endpoint": ENDPOINT_POST, "tag": tag,
        "cost_usd": dfs_client.envelope_cost(posted), "rows": len(keywords),
        "sandbox": client.is_sandbox})

    collected, missing = [], []
    for task_id, keyword in task_ids(posted):
        block = None
        for _ in range(POLL_ATTEMPTS):
            try:
                result = dfs_client.task_result(client.get(f"{ENDPOINT_GET}/{task_id}"))
            except dfs_client.DfsError:
                result = []
            if result:
                block = dict(result[0])
                block["keyword"] = keyword
                break
            time.sleep(POLL_SECONDS)
        if block is None:
            missing.append(keyword)
            continue
        collected.append(block)

    snapshot = {
        "source": "shopping", "endpoint": ENDPOINT_POST, "tag": tag,
        "cost_usd": dfs_client.envelope_cost(posted), "sandbox": client.is_sandbox,
        "run_id": run_id,
        "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **shape(collected, {"brand": args.brand}),
    }
    if missing:
        # Nicht abgeholte Keywords sind eine Lücke, keine Null. Ohne diesen
        # Vermerk läse die Analyse "kein Angebot gefunden".
        snapshot["notes"].append(
            f"Nicht rechtzeitig abgeholt: {', '.join(missing)}. Diese Keywords "
            "sind ungemessen, nicht ohne Angebote.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / dfs_pull.snapshot_name("shopping")
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Geschrieben: {path} ({len(collected)} von {len(keywords)} Keywords)")


if __name__ == "__main__":
    main()
