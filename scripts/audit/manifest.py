#!/usr/bin/env python3
"""Das Verzeichnis der Läufe einer Brand im Bucket.

**Ein Verzeichnis, kein Schema** (Spec Abschnitt 4). Es listet, welche Läufe es
gibt und wo ihre Dateien liegen. Es enthält **keine Kennzahl**: sobald Zahlen
darin stünden, wäre es ein normalisiertes Schema und damit die Datenbank durch
die Hintertür, die Abschnitt 9 ausdrücklich vertagt.

Es löst zwei praktische Probleme. Die App muss den Bucket nicht durchsuchen,
und die beiden gewachsenen Ablage-Layouts lassen sich nebeneinander bedienen:
ein Kunde liegt noch unter `reporting/reports/`, ein anderer schon unter
`reporting/runs/`. Der Manifest zeigt auf beides, ohne dass im Workspace etwas
umzieht.

**Der Freigabestatus lebt hier.** `publish` lädt hoch und setzt ihn nie,
`release` setzt ihn. Ein hochgeladener Lauf ist für den Kunden unsichtbar, bis
ein Mensch ihn gelesen hat.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

#: Version des Manifest-Formats. Steht drin, damit die App eine aeltere Fassung
#: erkennt, statt an einem fehlenden Feld zu scheitern.
VERSION = 1

#: Die Lauf-Arten, die es gibt. `light` ist der Verkaufs-Audit fuer einen kalten
#: Lead, `audit` der Vollaudit, `report` der wiederkehrende Bericht.
#: `inventory` ist die Bestandsaufnahme vor einem Theme-Wechsel und die einzige
#: Art, die Auswahl-Antworten des Kunden traegt. `tracking` dokumentiert eine
#: konkrete Tracking-Architektur und nimmt chronologische Kommentare auf.
KINDS = ("audit", "report", "light", "inventory", "tracking")

#: Dateien, die nie in den Bucket gehen. **Ausschlussliste, keine Auswahlliste**
#: (Spec Abschnitt 5): alles andere geht hoch, denn es sind die Daten des
#: Kunden. Wer eine Auswahlliste pflegt, vergisst die Datei, die der Kunde
#: gerade sucht.
EXCLUDED = ("dfs-ledger.jsonl",)


def path_for(brand: str, shop: str, run_id: str = "") -> str:
    """Der Bucket-Pfad. Login-Ebene ist die Brand, Ablage-Ebene der Shop."""
    base = f"brands/{brand}/shops/{shop}"
    return f"{base}/runs/{run_id}" if run_id else base


def empty(brand: str, name: str, shops: dict | None = None) -> dict:
    """Ein leeres Verzeichnis fuer eine Brand."""
    return {"version": VERSION, "brand": brand, "name": name,
            "shops": shops or {}, "runs": []}


def add_run(manifest_data: dict, *, shop: str, run_id: str, kind: str,
            cadence: str | None, period: str | None, run_date: str,
            files: dict, today: date | None = None) -> dict:
    """Traegt einen Lauf ein und gibt ein neues Manifest zurueck.

    Ein Lauf, den es schon gibt, wird ersetzt und behaelt dabei seinen
    Freigabestatus: ein erneutes `publish` derselben Lauf-ID ist eine
    Korrektur, keine Ruecknahme der Freigabe. Wer eine Freigabe zuruecknehmen
    will, tut das ausdruecklich.
    """
    if kind not in KINDS:
        raise ValueError(f"unbekannte Lauf-Art: {kind!r}")
    if not shop:
        raise ValueError("ein Lauf gehoert zu einem Shop")
    by_key = {(r["shop"], r["run_id"]): r for r in manifest_data.get("runs") or []}
    previous = by_key.get((shop, run_id))
    entry = {
        "shop": shop,
        "run_id": run_id,
        "kind": kind,
        "cadence": cadence,
        "period": period,
        "run_date": run_date,
        "published_at": (today or date.today()).isoformat(),
        # **Freigabe ist nie eine Nebenwirkung des Hochladens.**
        "released": bool(previous and previous.get("released")),
        "released_at": (previous or {}).get("released_at"),
        "path": path_for(manifest_data["brand"], shop, run_id),
        "files": files,
    }
    by_key[(shop, run_id)] = entry
    runs = sorted(by_key.values(),
                  key=lambda r: (r["shop"], r["run_date"], r["run_id"]),
                  reverse=True)
    return {**manifest_data, "runs": runs}


def release(manifest_data: dict, shop: str, run_id: str,
            today: date | None = None) -> dict:
    """Gibt einen Lauf frei. Erst danach sieht der Kunde ihn."""
    runs, found = [], False
    for r in manifest_data.get("runs") or []:
        if (r["shop"], r["run_id"]) == (shop, run_id):
            r = {**r, "released": True,
                 "released_at": (today or date.today()).isoformat()}
            found = True
        runs.append(r)
    if not found:
        raise KeyError(f"kein Lauf {run_id!r} fuer Shop {shop!r} im Manifest")
    return {**manifest_data, "runs": runs}


def released(manifest_data: dict, shop: str | None = None) -> list[dict]:
    """Was der Kunde sehen darf, neueste zuerst."""
    return [r for r in manifest_data.get("runs") or []
            if r.get("released") and (shop is None or r["shop"] == shop)]


def collect_files(run_dir: Path) -> dict:
    """Die Dateien eines Lauf-Ordners, relativ zu ihm, ohne die Ausschlussliste.

    Die Zuordnung ist bewusst flach: der Manifest nennt Pfade, keine Typen.
    Was `report.html` ist und was `findings/` sind, weiss die App.
    """
    out = {}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED:
            continue
        rel = path.relative_to(run_dir).as_posix()
        # Fassungen sind Archiv und gehoeren nicht in die Kundenansicht: sie
        # zeigen Zwischenstaende, die nie jemand freigegeben hat.
        if rel.startswith("revisions/"):
            continue
        out[rel] = path.stat().st_size
    return out


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, manifest_data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
