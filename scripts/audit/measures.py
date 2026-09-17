#!/usr/bin/env python3
"""Der Maßnahmen-Backlog als Zustand über alle Läufe (Spec Abschnitt 9).

Der Backlog ist keine Liste, die ein Audit einmal erzeugt, sondern Zustand:
jeder Folgelauf liest ihn, prüft offene Maßnahmen gegen ihre Prüfregel und
trägt neue Befunde nach. Deshalb, genau wie bei der Baseline, zwei Dateien:
**`measures.json` ist der Zustand**, `measures.md` (Task 12) die daraus
gerenderte lesbare Fassung. Von Hand geändert wird nur die JSON, oder besser:
über den Lauf.

Drei Regeln tragen dieses Modul:

1. **Eine ID wird nie wiederverwendet.** `M-001` bezeichnet eine Maßnahme für
   die Lebensdauer des Accounts. Die nächste ID kommt aus `next_id`, einem
   Zähler im Dokument selbst, nie aus der Länge der Liste: eine gelöschte
   Maßnahme darf ihre ID nie an eine neue vergeben, sonst bezeichnet `M-007`
   in einem späteren Report etwas anderes als sechs Monate zuvor.
2. **Keine Maßnahme ohne Beleg.** Der Audit kennt keinen Befund ohne Quellfeld
   oder URL, das gilt für die daraus entstehende Maßnahme genauso. Ein leerer
   `evidence` fliegt mit `ValueError`.
3. **Eine Hypothese wird nie priorisiert.** Sie wird als Test ausgewiesen und
   nimmt an der Rangfolge aus Sicherheit, Hebel und Aufwand nicht teil.

`create()` und `set_status()` mutieren das übergebene Dokument nicht,
sondern geben ein neues zurück: ein Aufrufer, der versehentlich das alte
Dokument weiterreicht, bekommt sichtbar den alten Stand, keine stille
Verwechslung zweier Objekte, die dieselbe Liste teilen.
"""
import json
import os
from datetime import date
from pathlib import Path

from audit import env

#: Sicherheit einer Maßnahme, geordnet nach fallender Verlässlichkeit.
#: "hypothesis" entscheidet allein über `type`, siehe `create()`.
CONFIDENCE = ("confirmed", "plausible", "hypothesis")

#: Hebel-Band, geordnet nach fallendem Hebel (aus den Baseline-Zahlen
#: abgeleitet, Spec Abschnitt 9, nicht geschätzt).
LEVERAGE = ("high", "medium", "low")

#: Aufwand-Band, geordnet nach steigendem Aufwand.
EFFORT = ("small", "medium", "large")

#: Wer eine Maßnahme umsetzt (Spec Abschnitt 9). `"Path to AI"` meint den
#: Betreiber, der den Lauf fährt, nicht die Firma. Der Wert bleibt so, weil ein
#: neuer eine Migration in `create()`, `load()`, `report_build.py` und im Portal
#: bräuchte, das den Rohwert zeigt (Spec 2026-09-11, D7). Angezeigt wird er nur
#: über `responsible_label()`.
RESPONSIBLE = ("Path to AI", "Customer", "Third Party")

#: Status einer Maßnahme (Spec Abschnitt 9). Eine neue Maßnahme startet immer
#: bei "open", siehe `create()`.
STATUS = ("open", "in_progress", "implemented", "rejected", "obsolete")

#: Ergebnis von `check()` für einen einzelnen Lauf. Nur "implemented" und
#: "open" sind zugleich gültige Werte für `set_status()`, "unchecked" nie:
#: der Aufrufer darf einen ungeprüften Stand nicht als Statuswechsel
#: schreiben, siehe `check()`.
CHECK_RESULTS = ("implemented", "open", "unchecked")

#: Disziplin, deren Befunde unabhängig von Sicherheit, Hebel und Aufwand oben
#: stehen (Spec Abschnitt 9, Priorisierung).
PRIORITY_DISCIPLINE = "data_quality"

_CONFIDENCE_RANK = {value: i for i, value in enumerate(CONFIDENCE)}
_LEVERAGE_RANK = {value: i for i, value in enumerate(LEVERAGE)}
_EFFORT_RANK = {value: i for i, value in enumerate(EFFORT)}


def empty() -> dict:
    """Das leere Dokument: kein Vorlauf, Zähler startet bei 1."""
    return {"next_id": 1, "measures": []}


def create(backlog: dict, *, title: str, discipline: str, evidence: str,
           confidence: str, leverage: str, effort: str,
           responsible: str | None = None, data_source: str | None = None,
           check_rule: str | None = None, finding_ref: str | None = None,
           today: date | None = None) -> dict:
    """Legt eine neue Maßnahme an und gibt ein neues Dokument zurück.

    Validiert vollständig, bevor eine ID vergeben wird: eine abgelehnte
    Erstellung (leerer Beleg, unbekannte Sicherheit, ...) darf `next_id`
    nicht weiterzählen, sonst entstünde eine Lücke in der ID-Reihe, die beim
    nächsten Blick auf den Backlog wie eine verlorene Maßnahme aussieht.

    `confidence` entscheidet allein über `type`: "hypothesis" wird nie zur
    Maßnahme, sondern zum Test, siehe Spec Abschnitt 9 ("Eine Hypothese wird
    nie priorisiert, sie wird als Test formuliert").

    `finding_ref` ist die Kennung des Befunds, aus dem die Maßnahme folgt
    (etwa "MES-01"). Sie ist der Grund, warum der Report eine Maßnahme
    beauftragbar zeigen kann: ohne sie steht im Backlog eine Handlung ohne
    Herkunft, und der Leser kann nicht prüfen, worauf sie sich stützt. Sie
    bleibt optional, weil eine Maßnahme auch aus einer Lücke in der Datenlage
    folgen kann, für die es keinen Befund am Shop gibt.
    """
    if not title:
        raise ValueError("titel darf nicht leer sein")
    if not discipline:
        raise ValueError("disziplin darf nicht leer sein")
    if not evidence:
        # Die Kernregel des Audits: kein Befund ohne Beleg, das gilt für die
        # daraus entstehende Maßnahme genauso.
        raise ValueError(
            f"Maßnahme {title!r} hat keinen Beleg. Kein Befund ohne Beleg, "
            "keine Maßnahme ohne Beleg."
        )
    if confidence not in CONFIDENCE:
        raise ValueError(f"unbekannte Sicherheit: {confidence!r}, erlaubt sind {CONFIDENCE}")
    if leverage not in LEVERAGE:
        raise ValueError(f"unbekannter Hebel: {leverage!r}, erlaubt sind {LEVERAGE}")
    if effort not in EFFORT:
        raise ValueError(f"unbekannter Aufwand: {effort!r}, erlaubt sind {EFFORT}")
    if responsible is not None and responsible not in RESPONSIBLE:
        raise ValueError(
            f"unbekannt, wer verantwortlich ist: {responsible!r}, "
            f"erlaubt sind {RESPONSIBLE}"
        )

    today_str = (today or date.today()).isoformat()
    entry = {
        "id": f"M-{backlog['next_id']:03d}",
        "title": title,
        "discipline": discipline,
        "evidence": evidence,
        "confidence": confidence,
        "leverage": leverage,
        "effort": effort,
        "responsible": responsible,
        "data_source": data_source,
        "check_rule": check_rule,
        "finding_ref": finding_ref,
        # Eine Hypothese wird nie zur Maßnahme, sie wird zum Test.
        "type": "test" if confidence == "hypothesis" else "measure",
        "status": "open",
        "history": [{"status": "open", "date": today_str}],
    }
    return {
        "next_id": backlog["next_id"] + 1,
        "measures": [*backlog["measures"], entry],
    }


def set_status(backlog: dict, id: str, status: str, *, today: date | None = None) -> dict:
    """Ändert den Status einer Maßnahme und hängt einen Eintrag an ihre
    Historie an, statt sie zu ersetzen: ein früherer Statuswechsel bleibt
    sichtbar, auch nach dem zehnten Folgelauf.
    """
    if status not in STATUS:
        raise ValueError(f"unbekannter Status: {status!r}, erlaubt sind {STATUS}")

    today_str = (today or date.today()).isoformat()
    new_measures = []
    found = False
    for measure in backlog["measures"]:
        if measure["id"] == id:
            found = True
            new_measures.append({
                **measure,
                "status": status,
                "history": [*measure["history"], {"status": status, "date": today_str}],
            })
        else:
            new_measures.append(measure)
    if not found:
        raise ValueError(f"unbekannte ID: {id!r}")

    return {**backlog, "measures": new_measures}


def prioritize(backlog: dict) -> list[dict]:
    """Ordnet die Maßnahmen nach Spec Abschnitt 9.

    Drei Gruppen, in dieser Reihenfolge:

    1. Befunde der Disziplin `data_quality`, unabhängig von den drei Achsen.
    2. Die übrigen Maßnahmen (`type == "measure"`), sortiert nach Sicherheit
       vor Hebel vor Aufwand.
    3. Tests (`type == "test"`), am Ende und unsortiert nach den drei Achsen:
       eine Hypothese wird nie priorisiert.

    Innerhalb einer Gruppe ist die Sortierung stabil, eine gleiche Rangfolge
    behält also die Reihenfolge, in der die Maßnahmen angelegt wurden.
    """
    measures_list = backlog["measures"]
    tests = [m for m in measures_list if m["type"] == "test"]
    actual = [m for m in measures_list if m["type"] == "measure"]
    priority = sorted(
        (m for m in actual if m["discipline"] == PRIORITY_DISCIPLINE), key=_rank)
    remainder = sorted(
        (m for m in actual if m["discipline"] != PRIORITY_DISCIPLINE), key=_rank)
    return [*priority, *remainder, *tests]


def _rank(measure: dict) -> tuple[int, int, int]:
    """Sortierschlüssel: Sicherheit vor Hebel vor Aufwand, jeweils aufsteigend
    nach Rang, also von "am verlässlichsten"/"am größten Hebel"/"am
    geringsten Aufwand" zuerst."""
    return (
        _CONFIDENCE_RANK[measure["confidence"]],
        _LEVERAGE_RANK[measure["leverage"]],
        _EFFORT_RANK[measure["effort"]],
    )


def check(measure: dict, snapshots: dict) -> str:
    """Wertet die Prüfregel einer Maßnahme gegen die Ergebnisse dieses Laufs aus.

    `snapshots` sind die Prüfergebnisse, die dieser Lauf für einzelne
    Maßnahmen tatsächlich ermitteln konnte: ein Dict von Maßnahmen-ID auf
    das Ergebnis, `True` heißt die Prüfregel ist erfüllt, `False`, sie ist
    es nicht. Eine Maßnahme, deren Prüfregel von einer in diesem Lauf nicht
    fälligen Quelle abhängt, taucht darin schlicht nicht auf: wer den Lauf
    fährt, trägt nur ein, was er anhand frischer Daten wirklich geprüft hat.

    **Der Fall, der zählt, ist "unchecked".** Fehlt die Maßnahme in
    `snapshots`, oder trägt sie gar keine Prüfregel, bleibt ihr Status
    unangetastet: diese Funktion gibt "unchecked" zurück, nie "open" als
    Ersatzwert. Ein Statuswechsel, der nur daher kommt, dass in diesem Lauf
    niemand gemessen hat, wäre eine Falschaussage in einem Backlog, nach dem
    ein Kunde arbeitet. Der Aufrufer erkennt daran: nur bei "implemented"
    oder "open" darf er `set_status()` aufrufen, bei "unchecked" lässt er
    den bisherigen Status stehen.
    """
    if not measure.get("check_rule"):
        return "unchecked"
    if measure["id"] not in snapshots:
        return "unchecked"
    return "implemented" if snapshots[measure["id"]] else "open"


def load(workspace: Path) -> dict:
    """Lädt den Bestand. Eine fehlende Datei ist ein Fehler, kein leerer
    Bestand: wer lädt, erwartet einen bereits geschriebenen Stand."""
    return json.loads(_path(workspace).read_text(encoding="utf-8"))


def load_or_empty(workspace: Path) -> dict:
    """Der Einstieg für einen Lauf: `empty()`, wenn noch nie geschrieben wurde.

    Eine beschädigte Datei heißt Abbruch mit Ansage, nie ein stiller
    Neuanfang: der würde die gesamte Statushistorie jeder bereits
    angelegten Maßnahme wegwerfen.
    """
    try:
        return load(workspace)
    except FileNotFoundError:
        return empty()
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{_path(workspace)} ist beschädigt ({error}). Wird nicht still neu "
            "angelegt, weil das die Statushistorie jeder Maßnahme wegwerfen würde. "
            "Datei prüfen und entweder reparieren oder löschen."
        ) from error


def save(workspace: Path, backlog: dict) -> Path:
    """Schreibt den Bestand atomar: erst daneben, dann umbenennen.

    Ein mitten im Schreiben abgebrochener Lauf darf keine halb geschriebene
    Datei hinterlassen, sonst existiert eine Maßnahme, deren `history` und
    `status` nicht zusammenpassen. `os.replace` ist innerhalb eines
    Dateisystems atomar: danach existiert der alte oder der neue Stand, nie
    ein halber.
    """
    if not isinstance(backlog, dict) or "measures" not in backlog:
        # prioritize() nimmt das Dokument und gibt eine Liste zurück. Wer den
        # Rückgabewert zuweist und ihn hierher reicht, schreibt die Liste in
        # measures.json; load() liefert danach eine Liste, und der nächste Lauf
        # fällt an ganz anderer Stelle um. Am 06.09.2026 im ersten echten Lauf
        # genau so passiert.
        typ = type(backlog).__name__
        raise ValueError(
            f"save() erwartet das Backlog-Dokument, bekommen hat es {typ}. "
            "Häufigste Ursache: der Rückgabewert von prioritize() wurde "
            "zugewiesen. prioritize() liefert die sortierte Liste für die "
            "Ausgabe, nicht das Dokument; gespeichert wird immer das Dokument."
        )
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(backlog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


#: Anzeigewörter für `measures.md`. Die Werte im JSON sind englisch, weil sie
#: technisch sind; das Dokument liest der Kunde, und dort steht Deutsch. Ohne
#: diese Zuordnung stünde in einer deutschen Tabelle "Hebel: low".
LABELS = {
    "leverage": {"high": "hoch", "medium": "mittel", "low": "niedrig"},
    "effort": {"small": "klein", "medium": "mittel", "large": "groß"},
    "status": {
        "open": "offen", "in_progress": "in Arbeit", "implemented": "umgesetzt",
        "rejected": "verworfen", "obsolete": "hinfällig",
    },
    "discipline": {
        "data_quality": "Datenqualität", "commerce": "Handel", "traffic": "Traffic",
        "seo": "SEO", "seo_technical": "SEO technisch", "geo": "GEO", "sea": "SEA",
        "cro": "Conversion", "content": "Content", "tech": "Technik",
        "trust": "Trust und Compliance",
    },
}


def _label(feld: str, value) -> str:
    """Das deutsche Anzeigewort, oder der Wert selbst, falls keins hinterlegt
    ist. Ein unbekannter Wert verschwindet so nicht, er steht nur unübersetzt
    da: eine fehlende Zeile wäre schlimmer als eine englische."""
    if value is None:
        return "-"
    return LABELS.get(feld, {}).get(value, str(value))


#: Anzeige für den Betreiber, solange `PTAI_OPERATOR_NAME` nirgends steht.
DEFAULT_OPERATOR_NAME = "Dienstleister"


def responsible_label(value: str | None, brand: str | None = None,
                      workspace: str | os.PathLike = ".") -> str:
    """Wer eine Maßnahme umsetzt, so wie es im Kundendokument steht.

    Die eine Anzeige für `measures.md` und den großen Audit. Bis zum 11.09.2026
    hießen dieselben Werte in `measures.md` "Path to AI" und "Dritter", im Audit
    "Path to AI" und "Dritter Dienstleister".

    - `"Path to AI"` zeigt `PTAI_OPERATOR_NAME`, gesucht über `audit.env` im
      Workspace, sonst "Dienstleister". Beim Kunden eines fremden Betreibers
      stünde sonst Path to AI als Verantwortlicher (Spec 2026-09-11, E3, D7).
    - `"Customer"` zeigt die Marke, wenn eine übergeben wird, sonst "Kunde".
    - `"Third Party"` zeigt "Dritter Dienstleister".

    Ein leerer Wert gibt einen leeren Text, der Aufrufer entscheidet, ob die
    Zeile entfällt. Ein unbekannter Wert bleibt unübersetzt stehen, wie bei
    `_label()`: eine fehlende Angabe wäre schlimmer als eine englische.
    """
    if not value:
        return ""
    if value == "Path to AI":
        return env.get("PTAI_OPERATOR_NAME", workspace) or DEFAULT_OPERATOR_NAME
    if value == "Customer":
        return brand or "Kunde"
    if value == "Third Party":
        return "Dritter Dienstleister"
    return str(value)


def render(workspace: Path) -> Path:
    """Erzeugt `measures.md`, die lesbare Fassung von `measures.json`.

    Wird aus der JSON generiert, nie von Hand gepflegt, dieselbe
    Formdisziplin wie `baseline.render()`. Zwei Abschnitte: zuerst die
    priorisierte Tabelle der echten Maßnahmen, danach ein eigener Abschnitt
    für die Tests. Eine Hypothese wird nie priorisiert (siehe
    `prioritize()`); stünde sie in derselben Tabelle wie die Maßnahmen, sähe
    sie danach aus. Jede Zeile zeigt Status und das Datum des letzten
    Statuswechsels, damit sichtbar ist, wo eine Maßnahme gerade steht und
    seit wann.
    """
    backlog = load_or_empty(workspace)
    prioritized = prioritize(backlog)
    actual = [m for m in prioritized if m["type"] == "measure"]
    tests = [m for m in prioritized if m["type"] == "test"]

    lines = ["# Maßnahmen", "", "## Priorisierte Maßnahmen", ""]
    lines.extend(_render_table(actual, "Keine Maßnahmen.", workspace))
    lines.append("## Tests")
    lines.append("")
    lines.extend(_render_table(tests, "Keine Tests.", workspace))
    markdown = "\n".join(lines).rstrip("\n") + "\n"
    return _write_atomic(_path(workspace).with_name("measures.md"), markdown)


def _render_table(entries: list[dict], empty_text: str,
                  workspace: str | os.PathLike = ".") -> list[str]:
    """Rendert eine Liste von Maßnahmen als Tabelle, oder `empty_text`, wenn
    die Liste leer ist. Eine leere Tabelle (nur Kopfzeile, keine Zeile) sähe
    wie ein Rendering-Fehler aus, ein Satz ist eindeutig."""
    if not entries:
        return [empty_text, ""]
    lines = [
        "| ID | Titel | Disziplin | Hebel | Aufwand | Verantwortlich | Status | Letzter Wechsel |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        last_change = entry["history"][-1]["date"]
        lines.append(
            f"| {entry['id']} | {entry['title']} | "
            f"{_label('discipline', entry['discipline'])} | "
            f"{_label('leverage', entry['leverage'])} | "
            f"{_label('effort', entry['effort'])} | "
            f"{responsible_label(entry['responsible'], workspace=workspace) or '-'} | "
            f"{_label('status', entry['status'])} | {last_change} |"
        )
    lines.append("")
    return lines


def _write_atomic(path: Path, content: str) -> Path:
    """Schreibt `content` atomar nach `path`: erst daneben, dann umbenennen.
    Dieselbe Mechanik wie in `baseline.py`, hier nur für `measures.md`
    gebraucht; `measures.json` schreibt weiterhin `save()` selbst.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _path(workspace: Path) -> Path:
    """Der eine Ort, an dem der Pfad zur measures.json gebildet wird."""
    return Path(workspace) / "reporting" / "measures.json"
