#!/usr/bin/env python3
"""Phasenstand eines Laufs, damit ein Abbruch nicht von vorn anfängt.

Der Stand hält zwei Ebenen: die Phase (Spec Abschnitt 6) und je Quelle, ob sie
schon gezogen wurde. Die zweite Ebene ist der Grund für das Ganze: eine bereits
bezahlte DataForSEO-Abfrage darf ein zweiter Anlauf nicht noch einmal kosten.

**Genau ein Prozess schreibt diesen Zustand.** Die Pulls der Phase 1 dürfen
parallel laufen, ihre Ergebnisse meldet aber jeder an den Orchestrator zurück,
und nur der ruft `save()`. Zwei Prozesse, die je ihren eigenen Stand laden,
ihre Quelle eintragen und speichern, überschreiben einander: `os.replace` macht
den letzten Schreiber zum Gewinner, die Einträge der anderen sind weg, und deren
Quellen werden beim nächsten Anlauf ein zweites Mal bezahlt. Das ist derselbe
Schaden, den dieses Modul verhindern soll, nur eine Ebene höher.
"""
import json
import os
from datetime import date
from pathlib import Path

PHASES = ("0-setup", "1-raw-data", "2-analyses", "3-synthesis", "4-deliverables")
PHASE_STATUS = ("open", "running", "done", "failed")
SOURCE_STATUS = ("open", "done", "failed", "skipped")


class State:
    def __init__(self, workspace: Path, data: dict):
        self.workspace = Path(workspace)
        self._data = data

    @property
    def run_id(self) -> str:
        return self._data["run_id"]

    @property
    def phases(self) -> dict:
        return self._data["phases"]

    @property
    def sources(self) -> dict:
        return self._data["sources"]

    @property
    def cadence(self) -> str:
        return self._data["cadence"]

    @property
    def period(self) -> dict | None:
        """Der Berichtszeitraum-Block aus `run.period()`, beim Audit `None`."""
        return self._data["period"]

    @property
    def path(self) -> Path:
        return _path(self.workspace, self.run_id)

    def set_phase(self, phase: str, status: str) -> None:
        if phase not in PHASES:
            raise ValueError(f"unbekannte Phase: {phase!r}")
        if status not in PHASE_STATUS:
            raise ValueError(f"unbekannter Status: {status!r}")
        self._data["phases"][phase] = status

    def reopen_from(self, phase: str) -> list[str]:
        """Setzt diese Phase und alle danach auf `open`, und gibt sie zurück.

        Der Fall dahinter: die Rohdaten eines Laufs sind gut, aber die
        Auswertung darüber hat sich geändert, weil eine Analyse dazugekommen
        ist oder eine Regel gefixt wurde. Dann soll Phase 1 nicht noch einmal
        laufen. Sie kostet je nach Shop eine halbe Stunde und bei den bezahlten
        Quellen echtes Geld, und sie liefert vor allem einen **anderen**
        Messzeitpunkt: die Baseline wäre danach nicht mehr der Nullpunkt, den
        der Kunde gesehen hat.

        **Die Quellen bleiben unangetastet.** Nur die Phasen gehen auf `open`;
        `sources` behält sein `done`, damit ein erneuter Durchlauf von Phase 1
        (falls er doch stattfindet) keine Quelle zweimal zieht.
        """
        if phase not in PHASES:
            raise ValueError(f"unbekannte Phase: {phase!r}")
        ab = PHASES.index(phase)
        betroffen = list(PHASES[ab:])
        for name in betroffen:
            self._data["phases"][name] = "open"
        return betroffen

    def next_phase(self) -> str | None:
        """Die erste Phase, die nicht fertig ist. Ein Fehler hält hier an."""
        for phase in PHASES:
            if self._data["phases"][phase] != "done":
                return phase
        return None

    def set_source(self, source: str, status: str, file: str | None = None,
                    reason: str | None = None, today: date | None = None) -> None:
        """Trägt das Ergebnis einer Quelle ein.

        `today` wird durchgereicht, nicht von der Uhr geholt. Ein Lauf über
        Mitternacht bekäme sonst für Quellen desselben Laufs verschiedene
        Kalendertage, und `run.is_due()` rechnet gegen Kalendergrenzen:
        eine Quelle würde einen Zyklus zu früh oder zu spät fällig, ohne dass
        es irgendwo auffällt. Ohne Angabe gilt der heutige Tag.
        """
        if status not in SOURCE_STATUS:
            raise ValueError(f"unbekannter Status: {status!r}")
        entry = {"status": status, "pulled_at": (today or date.today()).isoformat()}
        if file:
            entry["file"] = file
        if reason:
            entry["reason"] = reason
        self._data["sources"][source] = entry

    def source_open(self, source: str) -> bool:
        return self._data["sources"].get(source, {}).get("status") != "done"

    def save(self) -> Path:
        """Schreibt den Stand atomar: erst daneben, dann umbenennen.

        Ein mitten im Schreiben abgebrochenes `write_text` hinterlässt eine
        halbe JSON-Datei, und genau diese Datei ist die Voraussetzung dafür,
        den Lauf fortzusetzen. `os.replace` ist innerhalb eines Dateisystems
        atomar: es gibt danach den alten oder den neuen Stand, nie einen halben.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.parent / (self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path


def _path(workspace: Path, run_id: str) -> Path:
    """Der eine Ort, an dem der Pfad zur state.json gebildet wird."""
    return Path(workspace) / "reporting" / "runs" / run_id / "state.json"


def new(workspace: Path, run_id: str, cadence: str, period: dict | None = None) -> State:
    """Ein frischer Stand. `period` ist der Block aus `run.period()`.

    Der Typ wird hier geprüft und nicht zurechtgebogen. Ein Tupel aus
    `date`-Objekten, wie `run.period()` es früher lieferte, überlebt
    `json.dumps` nicht: der Lauf würde erst in `save()` abbrechen, also nach
    allen Pulls und damit nach dem bezahlten Teil. Ein Fehler an der Grenze
    kostet nichts.
    """
    if period is not None and not isinstance(period, dict):
        raise ValueError(
            f"period muss der Block aus run.period() sein, kein "
            f"{type(period).__name__}: {period!r}"
        )
    return State(workspace, {
        "run_id": run_id,
        "cadence": cadence,
        "period": period,
        "phases": {p: "open" for p in PHASES},
        "sources": {},
    })


def load(workspace: Path, run_id: str) -> State:
    return State(workspace, json.loads(_path(workspace, run_id).read_text(encoding="utf-8")))


def load_or_new(workspace: Path, run_id: str, cadence: str,
                 period: dict | None = None) -> State:
    """Der Einstieg für den Orchestrator: fortsetzen, wenn es schon läuft.

    Eine fehlende Datei heißt neuer Lauf. Eine beschädigte heißt Abbruch mit
    Ansage, nie stillschweigend ein neuer Lauf: der würde jede bereits bezahlte
    Abfrage ein zweites Mal kosten, und niemand würde es merken.
    """
    try:
        return load(workspace, run_id)
    except FileNotFoundError:
        return new(workspace, run_id, cadence, period)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{_path(workspace, run_id)} ist beschädigt ({error}). Der Lauf wird nicht still neu "
            "begonnen, weil das jede bereits bezahlte Abfrage noch einmal "
            "kostet. Datei prüfen und entweder reparieren oder löschen."
        ) from error
