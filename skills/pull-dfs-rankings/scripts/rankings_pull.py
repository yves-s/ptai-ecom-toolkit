#!/usr/bin/env python3
"""Ranking-Bestand, Share of Voice und optional die Sichtbarkeitshistorie.

Aufruf:
  rankings_pull.py --target beispielshop.example --out reporting/data/<run-id> \
      --run-id <run-id> --run-date YYYY-MM-DD --account-slug <slug> \
      --budget-cap 10.0 --location-code <code> --language-code <lang> \
      [--competitors "a.example,b.example"] [--with-history] [--sandbox]

Schreibt <out>/dfs-rankings.json.

Drei Endpunkte mit sehr verschiedenen Preisen, deshalb nicht drei
gleichrangige Aufrufe (gemessen am 12.08.2026):

  ranked_keywords          0,0144 USD   jeder Lauf
  bulk_traffic_estimation  0,0126 USD   jeder Lauf, fünf Domains in einem Call
  historical_rank_overview 0,127  USD   nur mit --with-history

Die Historie ist die teuerste Labs-Abfrage überhaupt, rund das Neunfache des
Bestands, und die Exploration hat sie als "einmalig nützlich, nicht in den
Monats-Report" bewertet. Der Share of Voice ist ihr günstiger Ersatz im
laufenden Betrieb: die Zeitreihe entsteht über die Läufe hinweg, statt sie je
Lauf teuer einzukaufen.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dfs_client  # noqa: E402
from audit import dfs_pull, ledger  # noqa: E402

ENDPOINT_RANKED = "dataforseo_labs/google/ranked_keywords/live"
ENDPOINT_TRAFFIC = "dataforseo_labs/google/bulk_traffic_estimation/live"

#: Teuerste Labs-Abfrage, rund 0,127 USD gegen 0,0144 USD beim Bestand.
#: Läuft deshalb nur auf --with-history.
ENDPOINT_HISTORY = "dataforseo_labs/google/historical_rank_overview/live"

#: Obergrenze der Keyword-Liste im Snapshot. Die Kennzahlen kommen aus
#: `metrics`, die Liste ist nur Beleg, deshalb kostet die Kürzung hier nichts.
MAX_KEYWORDS = 500

#: Die API nimmt bis 1000 Zeilen je Aufruf.
API_LIMIT = 1000

#: Die Positionsbänder aus `metrics.organic`, von vorn nach hinten. Sie sind
#: **disjunkt**: pos_2_3 enthält pos_1 nicht.
BANDS = ("pos_1", "pos_2_3", "pos_4_10", "pos_11_20", "pos_21_30", "pos_31_40",
         "pos_41_50", "pos_51_60", "pos_61_70", "pos_71_80", "pos_81_90",
         "pos_91_100")


def payload(args) -> dict:
    return {
        "target": args.target,
        "location_code": args.location_code,
        "language_code": args.language_code,
        "limit": API_LIMIT,
        "order_by": ["ranked_serp_element.serp_item.rank_absolute,asc"],
    }


def cumulative(metrics: dict) -> dict:
    """Kumulative Bänder aus den disjunkten Bändern der API.

    Gerechnet wird über `metrics.organic` und nicht über die gelieferten
    Zeilen. Der Unterschied ist keine Feinheit: die API liefert je Aufruf
    höchstens tausend Zeilen, kennt aber den vollen Bestand. Ueber die
    gelieferte Teilmenge gezählt käme ein Bruchteil des echten Werts heraus,
    und zwar ein plausibel aussehender.

    Fehlt `metrics.organic` ganz, gibt es keine Bänder und keine Null: eine 0
    läse sich als "kein einziges Keyword in den Top 3".
    """
    organic = (metrics or {}).get("organic") or {}
    if not organic:
        return {"top_3": None, "top_10": None, "top_100": None}
    running, result = 0, {}
    for band in BANDS:
        running += int(organic.get(band) or 0)
        if band == "pos_2_3":
            result["top_3"] = running
        elif band == "pos_4_10":
            result["top_10"] = running
        elif band == "pos_91_100":
            result["top_100"] = running
    return result


def shape(rows: list, meta: dict) -> dict:
    """Ranking-Bestand als summary plus begrenzte Keyword-Liste.

    Die Kennzahlen kommen aus `metrics` und `total_count` der API, die Liste
    ist nur noch Beleg.

    `rank_absolute` ist ein **Datenbankwert, kein Live-Messwert**. Am
    12.08.2026 wich er in einem Gegencheck von der Live-SERP ab, und ein als
    aktuell gelesener Datenbankwert ist genau die Sorte Zahl, die im Report
    niemandem auffällt. Deshalb reist `last_updated_time` je Keyword mit.
    """
    b = dfs_pull.unwrap(rows)
    items = b.get("items") or []
    organic = (b.get("metrics") or {}).get("organic") or {}

    features: dict = {}
    keywords = []
    for entry in items:
        element = entry.get("ranked_serp_element") or {}
        serp = element.get("serp_item") or {}
        kind = serp.get("type")
        if kind:
            features[kind] = features.get(kind, 0) + 1
        data = entry.get("keyword_data") or {}
        info = data.get("keyword_info") or {}
        keywords.append({
            "keyword": data.get("keyword"),
            "rank_absolute": serp.get("rank_absolute"),
            "rank_group": serp.get("rank_group"),
            "search_volume": info.get("search_volume"),
            "cpc": info.get("cpc"),
            "competition_level": info.get("competition_level"),
            # etv sitzt auf serp_item, nicht auf ranked_serp_element. Eine
            # Ebene daneben liefert None für jede Zeile.
            "etv": serp.get("etv"),
            "url": serp.get("url"),
            "serp_type": kind,
            "last_updated_time": element.get("last_updated_time"),
        })
    listed, truncated = dfs_pull.truncate(keywords, MAX_KEYWORDS)
    return {
        "summary": {
            # total_count ist der Bestand, items_count die Liefermenge. Wer
            # len(items) nimmt, meldet die Liefermenge als Bestand.
            "ranked_keywords_total": b.get("total_count"),
            "ranked_keywords_delivered": b.get("items_count"),
            **cumulative(b.get("metrics") or {}),
            "etv": organic.get("etv"),
            "is_new": organic.get("is_new"),
            "is_up": organic.get("is_up"),
            "is_down": organic.get("is_down"),
            "is_lost": organic.get("is_lost"),
            # Zählt über die gelieferten Zeilen, nicht über den Bestand.
            # Der Name sagt das, damit niemand es anders liest.
            "serp_features_in_sample": features,
        },
        "top_keywords": listed,
        "top_keywords_truncated": truncated,
        "notes": ["rank_absolute ist der Stand der DataForSEO-Datenbank zum "
                   "jeweiligen last_updated_time, keine Live-Position."],
    }


def shape_traffic(rows: list, meta: dict) -> dict:
    """Share of Voice: geschätzter organischer Traffic je Domain.

    Ein Aufruf für bis zu fünf Domains. Die Reihe über die Läufe hinweg
    entsteht dadurch von selbst, ohne die teure Historie je Lauf zu kaufen.
    """
    b = dfs_pull.unwrap(rows)
    return {"share_of_voice": [
        {"domain": entry.get("target"),
         "etv": ((entry.get("metrics") or {}).get("organic") or {}).get("etv"),
         "ranked_keywords": ((entry.get("metrics") or {}).get("organic") or {}).get("count")}
        for entry in (b.get("items") or [])
    ]}


def shape_history(rows: list, meta: dict) -> dict:
    """Sichtbarkeitshistorie als Monatsreihe, aufsteigend sortiert.

    Der Monat ist zweistellig aufgefüllt (`2026-08`, nie `2026-8`): sonst
    sortiert die Reihe als Text falsch, und jeder spätere Vergleich gegen den
    gleichen Kalendermonat der Baseline greift daneben.
    """
    history = []
    for entry in (dfs_pull.unwrap(rows).get("items") or []):
        organic = ((entry.get("metrics") or {}).get("organic") or {})
        year, month = entry.get("year"), entry.get("month")
        if year is None or month is None:
            continue
        history.append({"month": f"{int(year):04d}-{int(month):02d}",
                         "ranked_keywords": organic.get("count"),
                         "etv": organic.get("etv")})
    history.sort(key=lambda row: row["month"])
    result = {"visibility_history": history}
    # Am 07.09.2026 an einer echten Antwort gesehen: für eine Domain ohne
    # organische Sichtbarkeit liefert die API `metrics.organic: null` je Monat.
    # Eine Reihe voller None sieht aus wie ein fehlgeschlagener Pull, ist aber
    # ein Befund. Der Vermerk sagt, welches von beidem es war.
    if history and all(row["ranked_keywords"] is None for row in history):
        result["notes_history"] = [
            f"Alle {len(history)} Monate ohne organische Metriken: die Domain "
            "hat in diesem Markt keine Sichtbarkeit in der DataForSEO-Datenbank. "
            "Das ist ein Befund, kein fehlgeschlagener Abruf."]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ranking-Keywords, Share of Voice und optional die Historie ziehen.")
    parser.add_argument("--target", required=True,
                        help="Domain ohne Protokoll, z. B. beispielshop.example")
    parser.add_argument("--competitors", default="",
                        help="Wettbewerber-Domains für den Share of Voice, "
                             "kommagetrennt, höchstens vier (config.json > competitors)")
    parser.add_argument("--with-history", action="store_true",
                        help="zusätzlich die Sichtbarkeitshistorie ziehen "
                             "(rund 0,13 USD, gehört in den Erstlauf, nicht in die Kadenz)")
    dfs_pull.add_common_args(parser)
    args = parser.parse_args()

    client = dfs_pull.build_client(args)
    common = dict(
        workspace=Path(args.workspace), out=Path(args.out), run_id=args.run_id,
        run_date=date.fromisoformat(args.run_date), account_slug=args.account_slug,
        cap=args.budget_cap, pull="dfs_rankings")
    try:
        path = dfs_pull.execute(client, endpoint=ENDPOINT_RANKED, task=payload(args),
                                 shape=shape, **common)
    except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
        sys.exit(f"Fehler: Ranking-Pull nicht möglich: {exc}")

    # Share of Voice: eine ETV-Zahl je Domain für die eigene plus die
    # Wettbewerber, ein Aufruf. Fällt er aus, bleibt der Bestand erhalten.
    domains = ([args.target]
               + [d.strip() for d in args.competitors.split(",") if d.strip()])[:5]
    try:
        dfs_pull.execute(client, endpoint=ENDPOINT_TRAFFIC, shape=shape_traffic, merge=True,
                          task={"targets": domains, "location_code": args.location_code,
                                "language_code": args.language_code}, **common)
    except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
        print(f"Warnung: Share of Voice nicht gezogen ({exc})")

    if not args.with_history:
        print(f"Geschrieben: {path} (ohne Historie, --with-history kostet rund "
              f"0,13 USD zusätzlich)")
        return
    try:
        dfs_pull.execute(client, endpoint=ENDPOINT_HISTORY, shape=shape_history, merge=True,
                          task={"target": args.target, "location_code": args.location_code,
                                "language_code": args.language_code}, **common)
        print(f"Geschrieben: {path} (mit Historie)")
    except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
        print(f"Warnung: Sichtbarkeitshistorie nicht gezogen ({exc}), "
              f"Ranking-Bestand steht in {path}")


if __name__ == "__main__":
    main()
