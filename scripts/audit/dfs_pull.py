#!/usr/bin/env python3
"""Der gemeinsame Ablauf der fünf DataForSEO-Pulls.

Ein Pull besteht danach nur noch aus zwei reinen Funktionen: `payload()` baut
die Aufgabe, `shape()` macht aus den Ergebniszeilen einen Snapshot mit
`summary` und begrenzten Listen. Alles dazwischen, also Zugangsdaten,
Budgetprüfung, Aufruf, Ledger-Zeile und das Schreiben der Datei, steht hier
einmal.

Die Reihenfolge ist nicht beliebig:

1. Deckel prüfen. Vorher, sonst ist das Geld schon weg.
2. Aufrufen.
3. Ledger schreiben. Danach, weil erst die Antwort den echten Betrag kennt.
4. Snapshot schreiben.

Scheitert Schritt 2, gibt es keine Ledger-Zeile. Das ist Absicht: ein
geschätzter Betrag im Ledger wäre eine erfundene Zahl, und der Ledger ist ein
Belegbuch.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import dfs_client
from audit import ledger

#: Dateiname je Pull-Schlüssel. Ausgeschrieben statt aus dem Schlüssel
#: abgeleitet, damit ein Tippfehler auffällt statt eine Datei anzulegen, die
#: keine Analyse liest.
SNAPSHOT_NAMES = {
    "dfs_rankings": "dfs-rankings.json",
    "dfs_keywords": "dfs-keywords.json",
    "backlinks": "dfs-backlinks.json",
    "competitors": "dfs-competitors.json",
    "shopping": "dfs-shopping.json",
}

#: Geschätzte Kosten je Aufruf in US-Dollar, am 07.09.2026 an echten Aufrufen
#: gemessen (`scripts/tests/fixtures/dfs/HERKUNFT.md`): search_volume 0,090,
#: die Backlinks-Endpunkte je 0,024, historical_rank_overview 0,127, Labs
#: ranked_keywords laut Bewertung vom 12.08.2026 0,0144.
#:
#: Mit Sicherheitszuschlag, und der ist kein Aberglaube: die Preise haben eine
#: Zeilenkomponente, und gemessen wurde an einer kleinen Domain mit 23
#: verweisenden Domains. Ein Shop mit 40.000 Ranking-Keywords liefert mehr
#: Zeilen und kostet mehr. `backlinks` deckt fünf Aufrufe ab, `dfs_rankings`
#: zwei ohne und drei mit `--with-history`.
ESTIMATE_USD = {
    "dfs_rankings": 0.06,
    "dfs_keywords": 0.15,
    "backlinks": 0.15,
    "competitors": 0.04,
    "shopping": 0.02,
}


def snapshot_name(pull: str) -> str:
    if pull not in SNAPSHOT_NAMES:
        raise ValueError(
            f"unbekannter Pull: {pull!r}, erlaubt sind {sorted(SNAPSHOT_NAMES)}")
    return SNAPSHOT_NAMES[pull]


def truncate(rows: list, limit: int) -> tuple:
    """Begrenzte Liste plus Kürzungsmerker.

    Der Zähler im `summary` nennt immer die volle Menge, die Liste ist nur
    Beleg. Eine gekürzte Liste, die sich nicht als gekürzt zu erkennen gibt,
    erzeugt eine falsche Zahl.
    """
    return rows[:limit], len(rows) > limit


def unwrap(rows: list) -> dict:
    """Der eine Ergebnisblock einer DataForSEO-Labs-Antwort.

    Die Labs-Endpunkte liefern `result` als Liste mit genau einem Block, und
    die eigentlichen Zeilen liegen darin unter `items`, neben `total_count`,
    `items_count` und `metrics`. Wer über `result` iteriert und dort schon die
    Zeilen erwartet, findet nichts und schreibt null Zeilen in den Snapshot:
    ein Shop mit vierhundert Rankings erschiene als Shop ohne Rankings, ohne
    dass irgendetwas abstürzt.

    Das gilt für die Labs-Endpunkte. Die Keywords-Data-Endpunkte liefern ihre
    Zeilen flach in `result`, die Backlinks-Endpunkte wieder anders. Diese
    Funktion ist deshalb bewusst nicht "der Entpacker für alles": wer sie
    dorthin ausweitet, macht aus drei klaren Formen eine Vermutung.
    """
    if not rows or not isinstance(rows[0], dict):
        return {"total_count": 0, "items_count": 0, "items": [], "metrics": {}}
    return rows[0]


def execute(client, *, workspace: Path, out: Path, run_id: str, run_date: date,
            account_slug: str, pull: str, endpoint: str, task: dict, shape,
            cap: float, estimate: float | None = None, merge: bool = False) -> Path:
    """Ein DataForSEO-Aufruf mit Deckel, Ledger und Snapshot. Gibt den Pfad zurück."""
    filename = snapshot_name(pull)
    tag = ledger.build_tag(account_slug, run_date, pull)
    if estimate is None:
        estimate = ESTIMATE_USD[pull]

    ledger.check_budget(workspace, run_id, cap=cap, estimate=estimate)

    payload = client.post(endpoint, [{**task, "tag": tag}])
    rows = dfs_client.task_result(payload)
    cost = dfs_client.envelope_cost(payload)
    sandbox = bool(getattr(client, "is_sandbox", False))

    ledger.append(workspace, {
        "run_id": run_id, "pull": pull, "endpoint": endpoint, "tag": tag,
        "tag_returned": dfs_client.task_tag(payload), "cost_usd": cost,
        "rows": len(rows), "sandbox": sandbox,
    })

    meta = {
        "source": pull, "endpoint": endpoint, "tag": tag, "cost_usd": cost,
        "sandbox": sandbox, "run_id": run_id,
        "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    snapshot = {**meta, **shape(rows, meta)}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    if merge and path.exists():
        # Ein Pull mit zwei Endpunkten schreibt zweimal in dieselbe Datei.
        # Ohne Zusammenführen gewinnt der zweite Aufruf und der erste Teil ist
        # bezahlt und weg.
        previous = json.loads(path.read_text(encoding="utf-8"))
        snapshot = {**previous, **snapshot}
        snapshot["cost_usd"] = float(previous.get("cost_usd", 0.0)) + cost
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def add_common_args(parser) -> None:
    """Die Schalter, die jeder der fünf Pulls hat."""
    parser.add_argument("--workspace", default=".",
                        help="Kunden-Workspace mit reporting/ (Default: .)")
    parser.add_argument("--out", required=True,
                        help="Zielordner des Laufs, reporting/data/<run-id>")
    parser.add_argument("--run-id", required=True, help="Lauf-ID, z. B. 2026-10-01-audit")
    parser.add_argument("--run-date", required=True,
                        help="Lauf-Datum YYYY-MM-DD, erster Teil des Tags")
    parser.add_argument("--account-slug", required=True,
                        help="Account-Slug aus config.json, erster Teil des Tags")
    parser.add_argument("--budget-cap", type=float, required=True,
                        help="dfs_budget_usd aus config.json, Deckel je Lauf in USD")
    # Kein Vorgabewert. Ein still angenommenes Deutschland misst für einen
    # Shop in Österreich oder der Schweiz den falschen Markt: die Zahlen
    # kommen zurück, sehen plausibel aus und gehören zu einem anderen Land.
    # Der Orchestrator reicht beides aus config.market() durch.
    parser.add_argument("--location-code", type=int, required=True,
                        help="numerischer Standortcode aus config.json > market")
    parser.add_argument("--language-code", required=True,
                        help="Sprachcode aus config.json > market")
    parser.add_argument("--sandbox", action="store_true",
                        help="Rauchtest gegen die Sandbox (Dummy-Werte, nie für Zahlen)")


def build_client(args):
    """Client aus den Zugangsdaten (Umgebung, Workspace, zentral) und dem Sandbox-Schalter."""
    login, password = dfs_client.credentials(workspace=args.workspace)
    base = dfs_client.BASE_SANDBOX if args.sandbox else dfs_client.BASE_PRODUCTION
    return dfs_client.Client(login, password, base=base)
