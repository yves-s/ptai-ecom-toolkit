#!/usr/bin/env python3
"""Suchvolumen und Wettbewerb für Katalogbegriffe und GSC-Queries.

Aufruf:
  keywords_pull.py --seeds "a,b,c" [--gsc reporting/data/<run-id>/gsc.json] \
      --out ... --run-id ... --run-date ... --account-slug ... --budget-cap ... \
      --location-code <code> --language-code <lang> [--sandbox]

Schreibt <out>/dfs-keywords.json.

**Der Endpunkt kostet je Anfrage dasselbe, egal ob ein Keyword drin steht oder
tausend.** Deshalb wird gesammelt, entdoppelt und in Blöcken zu 1.000 gesendet.
Ein Aufruf je Keyword wäre technisch gleichwertig und tausendmal so teuer.

Gegen eine echte Antwort geprüft (07.09.2026, Fixture
`scripts/tests/fixtures/dfs/search_volume.json`): die Zeilen kommen **flach in
`result`**, anders als bei den Labs-Endpunkten.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import dfs_client  # noqa: E402
from audit import dfs_pull, ledger  # noqa: E402

ENDPOINT = "keywords_data/google_ads/search_volume/live"

#: Harte Grenzen des Endpunkts laut Doku.
MAX_KEYWORDS_PER_CALL = 1000
MAX_KEYWORD_LENGTH = 80

#: Obergrenze der Keyword-Liste im Snapshot.
MAX_ROWS = 1000


def collect(seeds, gsc_snapshot) -> list:
    """Seeds und GSC-Queries zu einer entdoppelten, sortierten Liste.

    Entdoppelt wird ohne Rücksicht auf Groß- und Kleinschreibung: für den
    Endpunkt ist das dasselbe Keyword, in zwei Blöcken wäre es zweimal bezahlt.
    Zu lange Begriffe fliegen hier raus und nicht in der API, weil ein Fehler
    dort die ganze bezahlte Anfrage kostet.
    """
    terms = list(seeds or [])
    for row in ((gsc_snapshot or {}).get("top_queries") or []):
        if row.get("query"):
            terms.append(row["query"])
    seen = set()
    for term in terms:
        clean = str(term).strip()
        if clean and len(clean) <= MAX_KEYWORD_LENGTH:
            seen.add(clean.lower())
    return sorted(seen)


def batches(keywords: list) -> list:
    """Blöcke zu höchstens `MAX_KEYWORDS_PER_CALL`. Leere Eingabe: kein Block."""
    return [keywords[start:start + MAX_KEYWORDS_PER_CALL]
            for start in range(0, len(keywords), MAX_KEYWORDS_PER_CALL)]


def payload(keywords: list, args) -> dict:
    return {"keywords": keywords, "location_code": args.location_code,
            "language_code": args.language_code}


def shape(rows: list, meta: dict, previous: list | None = None) -> dict:
    """Suchvolumen je Begriff plus Zähler.

    **Die Zeilen kommen flach in `result`**, nicht unter `result[0].items` wie
    bei den Labs-Endpunkten. Wer hier `dfs_pull.unwrap()` benutzt, findet
    nichts und schreibt null Keywords in den Snapshot.

    `search_volume: null` und `search_volume: 0` sind zwei verschiedene
    Aussagen: "Google liefert dafür keine Zahl" gegen "kein Suchvolumen". Sie
    werden getrennt gezählt, weil im Report daraus "ungemessen" oder "toter
    Begriff" wird, und das ist nicht dasselbe.
    """
    all_rows = list(previous or []) + list(rows)
    keywords, with_volume, without_data, total = [], 0, 0, 0
    for row in all_rows:
        volume = row.get("search_volume")
        if volume is None:
            without_data += 1
        else:
            total += int(volume)
            if volume > 0:
                with_volume += 1
        monthly = [
            {"month": f"{int(entry['year']):04d}-{int(entry['month']):02d}",
             "search_volume": entry.get("search_volume")}
            for entry in (row.get("monthly_searches") or [])
            if entry.get("year") and entry.get("month")
        ]
        monthly.sort(key=lambda entry: entry["month"])
        keywords.append({
            "keyword": row.get("keyword"),
            "search_volume": volume,
            "competition": row.get("competition"),
            "competition_index": row.get("competition_index"),
            "cpc": row.get("cpc"),
            "monthly": monthly,
        })
    # Nach Volumen absteigend, ungemessene Begriffe ans Ende: der Report
    # arbeitet die grossen zuerst ab.
    keywords.sort(key=lambda k: (k["search_volume"] is None, -(k["search_volume"] or 0)))
    listed, truncated = dfs_pull.truncate(keywords, MAX_ROWS)
    return {
        "summary": {
            "keywords_returned": len(all_rows),
            "keywords_with_volume": with_volume,
            "keywords_without_data": without_data,
            "search_volume_total": total,
        },
        "keywords": listed,
        "keywords_truncated": truncated,
        "notes": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suchvolumen und Wettbewerb für eine Begriffsliste ziehen.")
    parser.add_argument("--seeds", default="",
                        help="Keyword-Seeds aus config.json, kommagetrennt")
    parser.add_argument("--gsc", help="Pfad zu gsc.json des Laufs, liefert Top-Queries")
    dfs_pull.add_common_args(parser)
    args = parser.parse_args()

    gsc = None
    if args.gsc and Path(args.gsc).exists():
        gsc = json.loads(Path(args.gsc).read_text(encoding="utf-8"))
    keywords = collect([s.strip() for s in args.seeds.split(",")], gsc)
    blocks = batches(keywords)
    if not blocks:
        sys.exit("Fehler: keine Keywords. Ohne Begriffe gibt es nichts abzufragen, "
                 "und eine leere Anfrage kostet dasselbe wie eine volle.")

    client = dfs_pull.build_client(args)
    workspace, run_id = Path(args.workspace), args.run_id
    tag = ledger.build_tag(args.account_slug, date.fromisoformat(args.run_date),
                           "dfs_keywords")

    # Alle Blöcke sammeln und einmal am Ende formen. Ein Merge über
    # execute() würde die Keyword-Liste des zweiten Blocks über die des
    # ersten schreiben, und der wäre bezahlt und weg.
    collected, cost, failed = [], 0.0, None
    for number, block in enumerate(blocks, 1):
        try:
            ledger.check_budget(workspace, run_id, cap=args.budget_cap,
                                estimate=dfs_pull.ESTIMATE_USD["dfs_keywords"])
            answer = client.post(ENDPOINT, [{**payload(block, args), "tag": tag}])
        except (ledger.BudgetExceeded, dfs_client.DfsError) as exc:
            failed = f"Block {number} von {len(blocks)} nicht gezogen: {exc}"
            break
        rows = dfs_client.task_result(answer)
        block_cost = dfs_client.envelope_cost(answer)
        cost += block_cost
        collected.extend(rows)
        ledger.append(workspace, {
            "run_id": run_id, "pull": "dfs_keywords", "endpoint": ENDPOINT, "tag": tag,
            "tag_returned": dfs_client.task_tag(answer), "cost_usd": block_cost,
            "rows": len(rows), "sandbox": client.is_sandbox})

    if not collected:
        sys.exit(f"Fehler: Keyword-Pull nicht möglich: {failed}")

    snapshot = {
        "source": "dfs_keywords", "endpoint": ENDPOINT, "tag": tag,
        "cost_usd": round(cost, 6), "sandbox": client.is_sandbox, "run_id": run_id,
        "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **shape(collected, {"source": "dfs_keywords"}),
    }
    if failed:
        # Ein abgebrochener Block heißt: diese Begriffe sind ungemessen,
        # nicht ohne Suchvolumen.
        snapshot["notes"].append(
            f"{failed}. Die Begriffe dieses und der folgenden Blöcke sind "
            "ungemessen, nicht ohne Suchvolumen.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / dfs_pull.snapshot_name("dfs_keywords")
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Geschrieben: {path} ({len(keywords)} Begriffe in {len(blocks)} Block(e), "
          f"{snapshot['summary']['keywords_with_volume']} mit Suchvolumen)")


if __name__ == "__main__":
    main()
