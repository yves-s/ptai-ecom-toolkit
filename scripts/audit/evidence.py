#!/usr/bin/env python3
"""Belege gegen die Snapshots prüfen, aus denen sie stammen sollen.

`qa.py` prüft, ob ein Befund ein `evidence`-Feld **hat**. Diese Datei prüft,
ob das Feld **aufgeht**: existiert die genannte Snapshot-Datei im Lauf, und
führt sie den genannten Pfad wirklich.

**Warum das nötig ist.** Das audit-light hat ein Beleg-Gate, das jeden Befund
mit URL live gegen die Seite hält, und es hat dort Fehler gefangen, bevor ein
Kunde sie gesehen hat. Der grosse Audit misst überwiegend aus Snapshots, für
ihn ist die Live-Abfrage der falsche Test: seine Belege zeigen auf Felder wie
`crawl.json > summary.max_click_depth`. Ein Beleg, der auf ein Feld zeigt, das
es nicht gibt, ist im Ergebnis dasselbe wie eine widerlegte Behauptung, nur
schwerer zu bemerken. Am 08.09.2026 verwies ein Befund auf
`warenkorb-gefuellt.png`, und die Datei lag nicht im Ordner.

Geprüft wird ohne Urteil. Ob eine Zahl die richtige Schlussfolgerung trägt,
entscheidet ein Mensch; ob das Feld existiert, aus dem sie stammen soll,
entscheidet dieses Script.

CLI:
    python3 -m audit.evidence --workspace . --run-id 2026-10-01-audit

Rückgabewert 0 heisst: jeder maschinell prüfbare Beleg geht auf. 1 heisst,
mindestens einer zeigt ins Leere.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Ein Beleg-Teil der Form "datei.json > pfad.zum.feld". Alles ab der ersten
#: Klammer oder einem " mit " ist Erläuterung des Menschen und gehört nicht
#: zum Pfad: "findings_index.errors (by_status.404)" zeigt auf
#: `findings_index.errors`, der Rest sagt, worauf der Mensch darin geschaut hat.
_FILE_CLAIM = re.compile(r"^\s*([A-Za-z0-9_.-]+\.json)\s*>\s*(.+?)\s*$")
_IMAGE_CLAIM = re.compile(r"^\s*([A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp))\b")
_URL_CLAIM = re.compile(r"^\s*https?://", re.IGNORECASE)

#: Schneidet die menschliche Erläuterung vom Pfad ab. **Ein Pfad endet am
#: ersten Leerzeichen.** Das ist die einzige Regel, die trägt: eine Liste von
#: Füllwörtern ("mit", "gefiltert", "aggregiert") fängt genau die Fälle, an die
#: jemand gedacht hat, und meldet den Rest als fehlendes Feld. Am 08.09.2026
#: waren so acht von zwölf Meldungen falscher Alarm, weil die Analysen
#: "ist leer, ...", "für /products/..." und "je Seitentyp" schrieben.
#: **Ein Pfad endet am ersten Leerzeichen oder Komma.** Geprüft wird damit das
#: erste genannte Feld, nicht jedes. Das ist Absicht: die Analysen zählen im
#: selben Beleg gern Geschwisterfelder auf ("summary.a, summary.b") und
#: schreiben sie teils relativ zum ersten ("pages[] ...: h1, description").
#: Wer versucht, alle zu prüfen, muss diese Relativität raten und erzeugt
#: Fehlalarm. Das erste Feld belegt die Quelle, und darum geht es hier.
_PATH_NOISE = re.compile(r"[,\s].*$", re.DOTALL)

#: Bilddateien, die als Beleg genannt werden können.
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

#: Verdikte. `resolved`, `external` und `prose` sind in Ordnung; die übrigen
#: drei sind Fehler und setzen den Rückgabewert auf 1.
OK_VERDICTS = ("resolved", "external", "prose")
BAD_VERDICTS = ("missing_field", "missing_file", "missing_image")


def split_claims(evidence: str) -> list[str]:
    """Ein `evidence`-Feld in seine Einzelbelege zerlegen.

    Getrennt wird am Semikolon: so schreiben es die Analysen, und ein Komma
    taugt nicht, weil es innerhalb einer Erläuterung vorkommt.
    """
    if not evidence:
        return []
    return [t.strip() for t in str(evidence).split(";") if t.strip()]


def classify(claim: str) -> dict:
    """Einen Einzelbeleg einordnen: Snapshot-Feld, Bild, URL oder Prosa."""
    m = _FILE_CLAIM.match(claim)
    if m:
        path = _PATH_NOISE.sub("", m.group(2)).strip()
        # `screens.json > product-mobil.png` ist ein Bildbeleg, kein Feldpfad.
        # Der Index führt die Bilder in `images[]`, ein Feld mit dem Dateinamen
        # gibt es nicht, und ohne diesen Fall meldet die Prüfung jeden
        # Screenshot-Beleg als fehlendes Feld. Genau so schreiben die Analysen
        # es, weil der Index nun einmal `screens.json` heisst.
        if path.lower().endswith(_IMAGE_SUFFIXES):
            return {"raw": claim, "kind": "image", "file": path, "path": ""}
        return {"raw": claim, "kind": "file", "file": m.group(1), "path": path}
    m = _IMAGE_CLAIM.match(claim)
    if m:
        return {"raw": claim, "kind": "image", "file": m.group(1), "path": ""}
    if _URL_CLAIM.match(claim):
        return {"raw": claim, "kind": "url", "file": "", "path": ""}
    return {"raw": claim, "kind": "prose", "file": "", "path": ""}


#: Ein Segment mit Listenzugriff: `pages[]` meint irgendein Element,
#: `compare_properties[0]` genau das erste.
_SEGMENT = re.compile(r"^(?P<key>[^\[\]]+?)(?:\[(?P<index>\d*)\])?$")


def _first_alternative(segment: str) -> str:
    """`description_length_p10/p50/p90` meint drei Felder, von denen nur das
    erste ausgeschrieben ist. Geprüft wird das ausgeschriebene: existiert es,
    existieren die Geschwister mit an Sicherheit grenzender Wahrscheinlichkeit
    auch, und ein Prüfer, der bei dieser Schreibweise Alarm schlägt, wird nach
    dem zweiten Fehlalarm nicht mehr gelesen."""
    return segment.split("/")[0].strip()


def resolve(snapshot, path: str) -> bool:
    """Führt der Snapshot diesen Pfad?

    `summary.products_total` steigt zwei Ebenen ab. `pages[].hreflang` heisst:
    `pages` ist eine Liste, und mindestens ein Element trägt `hreflang`.
    `compare_properties[0].by_month` greift genau auf das erste Element zu.
    Ein leerer Pfad meint die Datei als Ganzes und geht immer auf.
    """
    if not path:
        return True
    # **Ein Schlüssel darf selbst Punkte enthalten.** `storefront_script_hosts`
    # ist eine Zuordnung von Hostnamen auf Seitenzahlen, und
    # `storefront_script_hosts.cdn.intelligems.io` meint einen Eintrag darin,
    # keinen dreistufigen Pfad. Wer stur am Punkt trennt, meldet einen
    # korrekten Beleg als fehlendes Feld.
    if _resolve_greedy(snapshot, path):
        return True
    current = snapshot
    for raw_segment in path.split("."):
        segment = _first_alternative(raw_segment)
        if not segment:
            return False
        match = _SEGMENT.match(segment)
        if not match:
            return False
        key = match.group("key").strip()
        index = match.group("index")
        wants_list = index is not None

        if isinstance(current, list):
            # Ein Pfad darf eine Ebene überspringen: `pages[].images.total`
            # meint das Feld in den Elementen, nicht in der Liste selbst.
            for item in current:
                if isinstance(item, dict) and key in item:
                    current = item[key]
                    break
            else:
                return False
        else:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]

        if wants_list:
            if not isinstance(current, list):
                return False
            if index:  # `[0]` steigt in genau dieses Element ab
                position = int(index)
                if position >= len(current):
                    return False
                current = current[position]
    return True


def _resolve_greedy(snapshot, path: str) -> bool:
    """Loest den Pfad so auf, dass ein Schlüssel Punkte enthalten darf.

    Nach jedem Segment wird geprüft, ob der gesamte Rest ein Schlüssel dieser
    Ebene ist. Trifft das zu, ist der Pfad aufgelöst.
    """
    segments = path.split(".")
    current = snapshot
    for i, segment in enumerate(segments):
        if not isinstance(current, dict):
            return False
        rest = ".".join(segments[i:])
        if rest in current:
            return True
        if segment not in current:
            return False
        current = current[segment]
    return True


def _snapshot_dirs(workspace: Path, run_id: str) -> list[Path]:
    """Wo ein Lauf seine Dateien hält: Rohdaten in `data/`, alles über den
    Lauf selbst in `runs/`. Ein Beleg nennt nur den Dateinamen, nie den
    Ordner, deshalb wird in beiden gesucht."""
    return [workspace / "reporting" / "data" / run_id,
            workspace / "reporting" / "runs" / run_id]


def _load(workspace: Path, run_id: str, name: str):
    for directory in _snapshot_dirs(workspace, run_id):
        candidate = directory / name
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


def _image_paths(workspace: Path, run_id: str) -> dict:
    """Dateiname zu Pfad aus dem Screenshot-Index. Fehlt der Index, ist die
    Abbildung leer, und jeder Bildbeleg gilt als nicht auffindbar: genau das
    ist dann der Befund."""
    index = _load(workspace, run_id, "screens.json") or {}
    out = {}
    for image in index.get("images") or []:
        path = image.get("path")
        if path:
            out[Path(path).name] = path
    return out


def check_claim(claim: dict, workspace: Path, run_id: str, images: dict) -> str:
    """Das Verdikt für einen Einzelbeleg."""
    if claim["kind"] == "url":
        return "external"
    if claim["kind"] == "prose":
        return "prose"
    if claim["kind"] == "image":
        path = images.get(claim["file"])
        if not path:
            return "missing_image"
        return "resolved" if Path(path).exists() else "missing_image"
    snapshot = _load(workspace, run_id, claim["file"])
    if snapshot is None:
        return "missing_file"
    # Ein leeres Feld ist ein vorhandenes Feld. Dass `competitors` eine leere
    # Liste ist, kann selbst der Befund sein.
    return "resolved" if resolve(snapshot, claim["path"]) else "missing_field"


def check_run(workspace, run_id: str) -> dict:
    """Jeden Befund des Laufs gegen seine Belege halten.

    Liefert die Zählung je Verdikt und die Liste der Befunde, deren Beleg ins
    Leere zeigt, mit Disziplin und Kennung, damit der Ablauf sie benennen kann.
    """
    workspace = Path(workspace)
    findings_dir = workspace / "reporting" / "runs" / run_id / "findings"
    images = _image_paths(workspace, run_id)
    counts = {v: 0 for v in (*OK_VERDICTS, *BAD_VERDICTS)}
    problems: list[dict] = []
    checked_findings = 0

    for path in sorted(findings_dir.glob("*.json")) if findings_dir.exists() else []:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            problems.append({"file": path.name, "id": "-", "verdict": "missing_file",
                             "claim": "Datei ist kein gültiges JSON"})
            continue
        discipline = document.get("discipline") or path.stem
        for finding in document.get("findings") or []:
            checked_findings += 1
            for raw in split_claims(finding.get("evidence", "")):
                claim = classify(raw)
                verdict = check_claim(claim, workspace, run_id, images)
                counts[verdict] += 1
                if verdict in BAD_VERDICTS:
                    problems.append({"file": path.name, "discipline": discipline,
                                     "id": finding.get("id", "-"),
                                     "verdict": verdict, "claim": raw})

    return {"run_id": run_id, "findings": checked_findings,
            "counts": counts, "problems": problems,
            "coverage": check_coverage(workspace, run_id)}


def check_coverage(workspace, run_id: str) -> list[dict]:
    """Wie viel jede Disziplin beantworten konnte, und wie viel nicht.

    Die Abdeckungs-Regel stammt aus `audit-light`: eine Linse, die geblockt
    wurde, sieht im Ergebnis aus wie ein guter Shop, wenn niemand mitzählt.
    Der grosse Audit hat keinen Score, den man deckeln könnte, also zählt er:
    je Disziplin die Befunde gegen die `blocked_questions`.

    `blocked` heisst nicht, dass die Analyse schlecht war. Es heisst, dass ihr
    eine Eingabe fehlte, und das ist ein legitimer Zustand. Auffällig wird es,
    wenn eine Analyse mindestens so viel offenlassen musste, wie sie
    beantwortet hat: dann beschreibt ihr Kapitel im Report nicht den Shop,
    sondern den Ausschnitt, den der Lauf zufällig sehen konnte. Am 08.09.2026
    traf das die Conversion-Analyse mit vier Befunden gegen fünf offene Fragen,
    und im fertigen Report war davon nichts mehr zu sehen.
    """
    findings_dir = Path(workspace) / "reporting" / "runs" / run_id / "findings"
    out = []
    for path in sorted(findings_dir.glob("*.json")) if findings_dir.exists() else []:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        findings = len(document.get("findings") or [])
        blocked = len(document.get("blocked_questions") or [])
        out.append({"file": path.name,
                    "discipline": document.get("discipline") or path.stem,
                    "findings": findings, "blocked": blocked,
                    "thin": blocked >= findings and blocked > 0})
    return out


def format_report(result: dict) -> str:
    """Der Bericht für den Menschen, kurz gehalten: die Zählung, dann jede
    Fundstelle mit Kennung, damit sie ohne Suchen auffindbar ist."""
    counts = result["counts"]
    lines = [f"Belegprüfung {result['run_id']}: {result['findings']} Befunde, "
             f"{counts['resolved']} Belege aufgelöst, "
             f"{counts['prose']} ohne Feldbezug, {counts['external']} extern."]
    thin = [c for c in result.get("coverage") or [] if c["thin"]]
    if thin:
        lines.append("")
        lines.append("Diese Analysen mussten mindestens so viel offenlassen, "
                     "wie sie beantwortet haben:")
        for entry in thin:
            lines.append(f"  {entry['discipline']:<16} "
                         f"{entry['findings']} Befunde, "
                         f"{entry['blocked']} offene Fragen")
        lines.append("  Das gehört an Gate B auf den Tisch: entweder die "
                     "fehlende Quelle nachziehen, oder die Lücke steht im "
                     "Report. Ein Kapitel, das seine Lücke verschweigt, liest "
                     "sich wie ein Befund über den Shop.")
        lines.append("")
    if not result["problems"]:
        lines.append("Kein Beleg zeigt ins Leere.")
        return "\n".join(lines)
    label = {"missing_field": "Feld fehlt im Snapshot",
             "missing_file": "Snapshot fehlt im Lauf",
             "missing_image": "Bild nicht im Index oder nicht auf der Platte"}
    lines.append(f"{len(result['problems'])} Belege zeigen ins Leere:")
    for problem in result["problems"]:
        lines.append(f"  {problem['id']:<8} {label[problem['verdict']]}: "
                     f"{problem['claim']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--json", action="store_true",
                        help="Ergebnis als JSON statt als Bericht")
    args = parser.parse_args(argv)

    result = check_run(args.workspace, args.run_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
