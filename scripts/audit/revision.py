#!/usr/bin/env python3
"""Eine Fassung eines Laufs beiseitelegen, bevor eine neue darüber entsteht.

**Wofür.** Die Rohdaten eines Laufs sind gut, aber die Auswertung darüber hat
sich geändert: eine Analyse ist dazugekommen, eine Regel wurde gefixt. Dann
läuft Phase 2 bis 4 erneut auf denselben Snapshots. Was dabei entsteht,
überschreibt die vorige Fassung, und die war ein Kundendokument oder hätte
eines werden können.

**Warum nicht einfach überschreiben.** Ein Report trägt Zahlen, über die
gesprochen wurde. Wer eine Fassung ersetzt, ohne die alte zu behalten, kann
später nicht mehr sagen, warum eine Zahl heute anders lautet als im Termin.
Das Archiv beantwortet genau diese Frage und kostet ein paar Kilobyte.

**Was nicht mitgeht.** `report-text.json` bleibt liegen. Darin stehen die
Sätze, die ein Mensch geschrieben hat (Cover-Headline, Kernaussagen je
Kapitel); sie gelten für den Lauf, nicht für die Fassung, und wer sie
mitarchiviert, lässt den Betreiber sie ein zweites Mal schreiben.

CLI:
    python3 -m audit.revision --workspace . --run-id 2026-10-01-audit
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

#: Was eine Fassung ausmacht: die Befunde je Disziplin und was daraus gerendert
#: wurde. Verzeichnisse wandern als Ganzes, Dateien einzeln.
BEWEGT_ORDNER = ("findings",)
BEWEGT_DATEIEN = ("audit.pdf", "audit.html", "audit-web.html")

#: Der Backlog liegt eine Ebene höher als der Lauf, weil er über alle Läufe
#: gilt. Er wird kopiert, nicht verschoben: die Maßnahmen, die ein Mensch
#: schon angefasst hat, bleiben im Original stehen.
BACKLOG = ("measures.json", "measures.md")


def revisions_dir(workspace, run_id: str) -> Path:
    return Path(workspace) / "reporting" / "runs" / run_id / "revisions"


def next_number(workspace, run_id: str) -> str:
    """Die nächste freie Fassungsnummer, zweistellig."""
    base = revisions_dir(workspace, run_id)
    if not base.is_dir():
        return "01"
    genutzt = [int(d.name) for d in base.iterdir()
               if d.is_dir() and d.name.isdigit()]
    return f"{max(genutzt, default=0) + 1:02d}"


def archive(workspace, run_id: str) -> Path | None:
    """Legt die aktuelle Fassung nach `revisions/NN/` und gibt den Pfad zurück.

    `None` heisst: es gab nichts zu archivieren, der Lauf hat noch keine
    Befunde und keinen Report. Das ist kein Fehler, sondern der Normalfall beim
    allerersten Durchgang.
    """
    workspace = Path(workspace)
    run = workspace / "reporting" / "runs" / run_id
    quellen = [run / name for name in (*BEWEGT_ORDNER, *BEWEGT_DATEIEN)]
    # Ein leerer `findings/`-Ordner ist keine Fassung. Er entsteht schon beim
    # Anlegen des Laufs, und wer ihn archiviert, legt beim ersten Durchgang
    # eine leere Fassung 01 an, gegen die später niemand vergleichen kann.
    if not any(any(q.iterdir()) if q.is_dir() else q.exists() for q in quellen):
        return None

    ziel = revisions_dir(workspace, run_id) / next_number(workspace, run_id)
    ziel.mkdir(parents=True)
    for quelle in quellen:
        if quelle.exists():
            shutil.move(str(quelle), str(ziel / quelle.name))
    for name in BACKLOG:
        datei = workspace / "reporting" / name
        if datei.exists():
            shutil.copy2(datei, ziel / name)
    return ziel


def keep(measure: dict) -> bool:
    """Bleibt diese Maßnahme beim Zurücksetzen stehen?

    Ja, sobald ein Mensch sie angefasst hat: ein Status jenseits von `open`
    oder mehr als der eine Eintrag, den `create()` selbst schreibt. Diese
    Arbeit darf eine neue Analyse nicht wegwerfen, auch wenn sie denselben
    Befund noch einmal stellt. Der Preis ist eine mögliche Dublette, und die
    ist billiger als eine verlorene Entscheidung.
    """
    if measure.get("status") != "open":
        return True
    return len(measure.get("history") or []) > 1


def reset_measures(backlog: dict) -> tuple[dict, int, int]:
    """Nimmt die unberührten Maßnahmen heraus, behält die angefassten.

    Gibt den neuen Backlog zurück, dazu die Zahl der entfernten und der
    behaltenen. `next_id` zählt hinter den behaltenen weiter, damit keine
    Kennung zweimal vergeben wird, solange in derselben Datei noch eine alte
    steht.
    """
    alle = backlog.get("measures") or []
    behalten = [m for m in alle if keep(m)]
    entfernt = len(alle) - len(behalten)
    return ({"next_id": len(behalten) + 1, "measures": behalten},
            entfernt, len(behalten))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--keep-measures", action="store_true",
                        help="den Backlog nicht anfassen")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    ziel = archive(workspace, args.run_id)
    if ziel is None:
        print("Nichts zu archivieren: dieser Lauf hat noch keine Fassung.")
    else:
        print(f"Fassung liegt in {ziel.relative_to(workspace)}")

    if args.keep_measures:
        return 0
    datei = workspace / "reporting" / "measures.json"
    if not datei.exists():
        return 0
    neu, entfernt, behalten = reset_measures(
        json.loads(datei.read_text(encoding="utf-8")))
    datei.write_text(json.dumps(neu, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"Backlog: {entfernt} unberührte Maßnahmen entfernt, "
          f"{behalten} angefasste behalten.")
    if behalten:
        print("  Die behaltenen tragen einen Status oder eine Historie. Eine "
              "neue Analyse kann denselben Befund noch einmal stellen; das "
              "gibt eine Dublette und ist billiger als eine verlorene "
              "Entscheidung.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
