#!/usr/bin/env python3
"""Kundenwissen zu Befunden: lesen, ergaenzen, an die Analysen weiterreichen.

Der Audit misst von aussen. Er sieht, dass über tausend Produkte nicht kaufbar
sind, und er kann nicht wissen, dass sie schlicht ausverkauft sind. Genau
das ist am 08.09.2026 im ersten Kundentermin passiert: ein Betriebszustand
stand als Befund mit Schweregrad "hoch" im Report, und die Rueckfrage des
Kunden war nicht "das stimmt nicht", sondern "wie gebe ich euch das
zurueck, damit es beim naechsten Mal drinsteht?".

Diese Datei ist die Antwort darauf, und sie ist bewusst so klein wie
moeglich. Kein Produkt, keine Oberflaeche, kein Konto: eine JSON-Datei im
Kunden-Workspace, die ein Mensch lesen und ein Agent verstehen kann.

**Der Weg hinein ist ein Gespraech.** Der Kunde antwortet auf einen Befund
mit dessen Kennung ("HDL-07 stimmt so nicht, die sind ausverkauft"), egal
ob im Chat, in einer Mail oder im Termin. Wer den Audit fuehrt, legt daraus
einen Eintrag an. Das ist der ganze Mechanismus, und er funktioniert ab dem
ersten Tag, ohne dass jemand Software baut.

**Der Weg heraus ist der Prompt.** `as_prompt()` rendert die Eintraege in
den Text, den Phase 2 jedem Analyse-Subagent mitgibt. Die Agents haben die
Regel dazu in ihrer eigenen Beschreibung: ein Befund, den ein Eintrag
erklaert, wird nicht erneut gestellt, sondern faellt weg oder wird auf die
Teilmenge eingeengt, die der Eintrag nicht erklaert.

**Was hier nicht passiert: Zahlen ueberschreiben.** Ein Eintrag ordnet ein,
er misst nicht. Widerspricht er den Daten, gewinnen die Daten, und der
Widerspruch gehoert sichtbar in den Befund.
"""
import json
from datetime import date
from pathlib import Path

#: Dateiname im Kunden-Workspace, relativ zu dessen Wurzel.
FILE = "reporting/context.json"

#: Die Arten von Wissen, die ein Eintrag tragen kann. Bewusst vier, nicht
#: mehr: sie unterscheiden sich darin, was ein Agent damit tun soll.
KINDS = {
    "reason": "der fachliche Grund hinter einem gemessenen Zustand",
    "decision": "eine bewusste Entscheidung, die so bleiben soll",
    "planned": "laeuft bereits, Umsetzung ist unterwegs",
    "correction": "unsere Messung oder Einordnung war falsch",
}

#: Kennungs-Praefix der Eintraege selbst, damit sie im Report und im
#: Gespraech eindeutig referenzierbar sind wie ein Befund.
PREFIX = "CTX"


def context_path(workspace: str = ".") -> Path:
    """Der volle Pfad zur Kontextdatei eines Workspace."""
    return Path(workspace) / FILE


def load(workspace: str = ".") -> list[dict]:
    """Liest die Eintraege. Fehlt die Datei, ist das kein Fehler: ein Audit
    ohne Kundenwissen ist der Normalfall beim ersten Lauf."""
    p = context_path(workspace)
    if not p.exists():
        return []
    try:
        daten = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{FILE} ist kein gueltiges JSON: {exc}") from exc
    entries = daten.get("entries") if isinstance(daten, dict) else daten
    return list(entries or [])


def validate(entries: list[dict]) -> list[str]:
    """Prueft die Eintraege auf das, was ein Agent zwingend braucht.

    Ein Eintrag ohne `about` erreicht keinen Befund, und ein Eintrag ohne
    `statement` sagt nichts. Beides ist ein Fehler, kein Hinweis: eine
    stillschweigend wirkungslose Kundenaussage ist schlimmer als gar keine,
    weil beide Seiten glauben, sie sei angekommen.
    """
    errors = []
    gesehen = set()
    for i, e in enumerate(entries, 1):
        wo = e.get("id") or f"Eintrag {i}"
        if not e.get("id"):
            errors.append(f"{wo}: keine id")
        elif e["id"] in gesehen:
            errors.append(f"{wo}: id doppelt vergeben")
        else:
            gesehen.add(e["id"])
        if not (e.get("statement") or "").strip():
            errors.append(f"{wo}: kein statement, der Eintrag sagt nichts")
        if not e.get("about"):
            errors.append(f"{wo}: kein about, der Eintrag erreicht keinen Befund")
        art = e.get("kind")
        if art not in KINDS:
            errors.append(f"{wo}: kind ist '{art}', erlaubt sind "
                          f"{', '.join(sorted(KINDS))}")
        if not e.get("source"):
            errors.append(f"{wo}: keine source, spaeter ist nicht mehr "
                          "nachvollziehbar, wer das gesagt hat")
    return errors


def next_id(entries: list[dict]) -> str:
    """Die naechste freie Kennung, fortlaufend und dreistellig."""
    zahlen = []
    for e in entries:
        identifier = str(e.get("id") or "")
        if identifier.startswith(PREFIX + "-"):
            remainder = identifier.split("-", 1)[1]
            if remainder.isdigit():
                zahlen.append(int(remainder))
    return f"{PREFIX}-{max(zahlen, default=0) + 1:03d}"


def add(workspace: str, statement: str, about: list[str], kind: str,
        source: str, heute: date | None = None) -> dict:
    """Haengt einen Eintrag an und schreibt die Datei.

    Anhaengen, nie ersetzen: was der Kunde einmal gesagt hat, bleibt
    nachvollziehbar, auch wenn er es spaeter anders sieht. Eine geaenderte
    Einschaetzung ist ein neuer Eintrag, der den alten benennt.
    """
    if kind not in KINDS:
        raise ValueError(f"kind '{kind}' unbekannt, erlaubt: "
                         f"{', '.join(sorted(KINDS))}")
    if not about:
        raise ValueError("about darf nicht leer sein, sonst erreicht der "
                         "Eintrag keinen Befund")
    entries = load(workspace)
    entry = {
        "id": next_id(entries),
        "date": (heute or date.today()).isoformat(),
        "source": source,
        "about": list(about),
        "kind": kind,
        "statement": statement.strip(),
    }
    entries.append(entry)
    p = context_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False,
                            indent=2) + "\n", encoding="utf-8")
    return entry


def for_finding(entries: list[dict], befund_id: str) -> list[dict]:
    """Alle Eintraege, die diesen Befund betreffen.

    `about` traegt Befund-Kennungen (`HDL-07`) oder ganze Sektionen
    (`commerce`), letzteres fuer eine Aussage, die nicht an einem einzelnen
    Befund haengt ("wir bespielen Paid Social bewusst nicht").
    """
    sektion = befund_id.split("-", 1)[0].lower()
    treffer = []
    for e in entries:
        goals = {str(z).lower() for z in (e.get("about") or [])}
        if befund_id.lower() in goals or sektion in goals:
            treffer.append(e)
    return treffer


def as_prompt(entries: list[dict]) -> str:
    """Rendert die Eintraege als Prompt-Abschnitt fuer einen Analyse-Subagent.

    Leer, wenn es nichts gibt: ein leerer Abschnitt im Prompt erzeugt sonst
    die Illusion, es haette Kundenwissen gegeben und es sei nichts
    Passendes dabei gewesen.
    """
    if not entries:
        return ""
    rows = [
        "## Was der Kunde bereits eingeordnet hat",
        "",
        "Diese Aussagen kommen vom Kunden selbst und beziehen sich auf "
        "frueher gestellte Befunde. Ein Befund, den ein Eintrag erklaert, "
        "wird nicht erneut gestellt: er faellt weg oder wird auf die "
        "Teilmenge eingeengt, die der Eintrag nicht erklaert. "
        "Widerspricht ein Eintrag den Zahlen, gewinnen die Zahlen, und der "
        "Widerspruch gehoert sichtbar in den Befund.",
        "",
    ]
    for e in entries:
        goals = ", ".join(str(z) for z in (e.get("about") or []))
        rows.append(f"- **{e.get('id')}** (betrifft {goals}, "
                      f"{KINDS.get(e.get('kind'), e.get('kind'))}, "
                      f"{e.get('source')}, {e.get('date')}): "
                      f"{e.get('statement')}")
    return "\n".join(rows)
