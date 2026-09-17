#!/usr/bin/env python3
"""Kostenzuordnung und Budgetdeckel für DataForSEO (Spec Abschnitt 13).

DataForSEO kennt weder Projekte noch Unterkonten. Die Zuordnung je Kunde und
Lauf läuft deshalb über zwei Dinge: das Feld `tag`, das die Endpunkte im
`data`-Objekt der Antwort zurückgeben, und diese Datei. Ohne beides ist am
Monatsende nicht mehr feststellbar, welcher Kunde welchen Betrag verursacht hat.

Der Ledger ist ausschließlich anhängend. Eine Zeile je Aufruf, geschrieben
nachdem der Aufruf zurückkam, also nachdem das Geld ausgegeben ist. Eine
Zeile, die fehlt, weil der Prozess dazwischen abgebrochen ist, ist ein
verlorener Beleg; eine Zeile, die vorher geschrieben würde und dann nie einen
Aufruf bekäme, wäre eine falsche Zahl. Von beiden Fehlern ist der erste der
billigere.

Gerechnet wird in US-Dollar, weil DataForSEO seine Kosten so zurückgibt. Der
Deckel in `config.json > dfs_budget_usd` ebenfalls.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

LEDGER_NAME = "dfs-ledger.jsonl"

#: DataForSEO nimmt für `tag` bis zu 255 Zeichen (Doku je Endpunkt).
TAG_MAX_LENGTH = 255


class BudgetExceeded(Exception):
    """Der Deckel aus `config.json > dfs_budget_usd` ist erreicht.

    Kein Fehler des Laufs: die betroffene Quelle wird `skipped` mit Grund,
    die übrigen Quellen laufen weiter, und Gate A weist die Lücke aus.
    """


def ledger_path(workspace: Path) -> Path:
    """Der eine Ort, an dem der Pfad zum Ledger gebildet wird."""
    return Path(workspace) / "reporting" / LEDGER_NAME


def build_tag(account_slug: str, run_date: date, pull: str) -> str:
    """`<kunde>/<lauf-datum>/<pull>`, der Tag aus Spec Abschnitt 13.

    Leere Teile sind ein Fehler, kein Sonderfall: `beispielshop//rankings` ist
    in der Abrechnung von einem Tag mit Datum nicht mehr zu unterscheiden.
    """
    parts = [str(account_slug).strip(), run_date.isoformat(), str(pull).strip()]
    for part in parts:
        if not part:
            raise ValueError(
                f"Tag-Teil leer: {parts!r}. Ein Tag ohne Kunde oder ohne Pull "
                "lässt sich später keiner Rechnung zuordnen."
            )
    tag = "/".join(parts)
    if len(tag) > TAG_MAX_LENGTH:
        raise ValueError(
            f"Tag ist {len(tag)} Zeichen lang, DataForSEO nimmt "
            f"{TAG_MAX_LENGTH}: {tag!r}"
        )
    return tag


def append(workspace: Path, entry: dict) -> Path:
    """Hängt eine Zeile an, legt Datei und Ordner bei Bedarf an.

    Ein Zeitstempel wird ergänzt, wenn der Aufrufer keinen mitgibt: eine Zeile
    ohne Zeit ist als Beleg wertlos.
    """
    path = ledger_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = dict(entry)
    line.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def spent(workspace: Path, run_id: str) -> float:
    """Summe der bisher in diesem Lauf angefallenen Kosten, in US-Dollar.

    Eine unlesbare oder unvollständige Zeile ist ein Abbruch, kein
    Überspringen. Wer sie überspringt, senkt die Summe, hebt damit faktisch
    den Deckel an und gibt mehr Geld aus, als bewilligt ist.
    """
    path = ledger_path(workspace)
    if not path.exists():
        return 0.0
    total = 0.0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path}, Zeile {number} ist kein gültiges JSON ({error}). Der "
                "Ledger wird nicht teilweise gelesen, weil eine übersprungene "
                "Zeile den Budgetdeckel anhebt."
            ) from error
        if entry.get("run_id") != run_id:
            continue
        if "cost_usd" not in entry:
            raise ValueError(
                f"{path}, Zeile {number} hat kein Feld cost_usd. Eine Zeile "
                "ohne Kosten ist als Beleg wertlos."
            )
        total += float(entry["cost_usd"])
    return total


def remaining(workspace: Path, run_id: str, cap: float) -> float:
    """Was in diesem Lauf noch ausgegeben werden darf, nie negativ."""
    return max(0.0, float(cap) - spent(workspace, run_id))


def check_budget(workspace: Path, run_id: str, *, cap: float, estimate: float) -> None:
    """Wirft `BudgetExceeded`, wenn der nächste Aufruf den Deckel reißen würde.

    Geprüft wird vor dem Aufruf gegen eine Schätzung, weil der echte Preis
    erst mit der Antwort kommt. Die Schätzungen je Pull stehen in
    `dfs_pull.ESTIMATE_USD` und sind an echten Aufrufen gemessen.
    """
    already = spent(workspace, run_id)
    if already + float(estimate) > float(cap):
        raise BudgetExceeded(
            f"Budgetdeckel erreicht: {cap} USD je Lauf, davon {already} USD "
            f"ausgegeben, die nächste Abfrage kostet geschätzt {estimate} USD. "
            f"DataForSEO-Teil wird abgebrochen (Lauf {run_id})."
        )
