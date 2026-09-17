#!/usr/bin/env python3
"""Betreiber-Schlüssel auflösen, egal aus welchem Verzeichnis ein Lauf startet.

Der Monats-Report und der große Audit laufen im Kunden-Workspace und finden ihre
Schlüssel dort in `.env`. `audit-light` läuft für einen kalten Lead und hat
keinen Workspace: es gibt kein Verzeichnis, in dem eine passende `.env` liegen
könnte. Gleichzeitig sind PageSpeed-, GEO- und DataForSEO-Schlüssel gar keine
Kundengeheimnisse, sie gehören dem Betreiber und sind in jedem Workspace
dieselben. Bis 07.09.2026 lagen sie deshalb dupliziert in jeder Kunden-`.env`,
und ein Wechsel hätte alle einzeln anfassen müssen.

Reihenfolge, absichtlich so und nicht anders:

    1. Umgebungsvariable       ein Lauf kann jeden Wert gezielt übersteuern
    2. `.env` im Workspace     ein Kunde darf einen eigenen Wert setzen
    3. ~/.config/ptai-ecom/.env  der Betreiber-Standard

Die Kunden-`.env` schlägt die zentrale Datei bewusst: ein Kunde mit eigenem
DataForSEO-Konto soll seines benutzen, ohne dass jemand die zentrale Datei
anfasst. Und was hier NICHT hingehört, ist die Google-Service-Account-JSON: die
ist je Kunde verschieden und bleibt im Workspace, wo `setup` sie hinlegt.

CLI: python3 -m audit.env --check
"""
import os
import re
import sys
from pathlib import Path

#: Die Schlüssel, die dem Betreiber gehören. Nur diese liest die zentrale Datei;
#: alles andere bleibt Sache des Workspace.
OPERATOR_KEYS = (
    "PTAI_PSI_KEY",
    "PTAI_OPENAI_KEY",
    "PTAI_PERPLEXITY_KEY",
    "PTAI_GEMINI_KEY",
    "PTAI_DFS_LOGIN",
    "PTAI_DFS_PASSWORD",
    "PTAI_GOOGLE_ADS_TOKEN",
)

#: Funnel-Datenbank und Mailversand. Gehoeren ebenfalls dem Betreiber, heissen
#: aber nicht PTAI_*, weil sie aus dem alten ecom-audit-Repo stammen. audit-light
#: braucht sie fuer den ID-Weg, audit-light-send fuer den Versand.
FUNNEL_KEYS = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "RESEND_API_KEY")

#: Was ein audit-light-Lauf ohne --with-dfs tatsaechlich braucht. Alles andere
#: darf fehlen, ohne dass jemand darueber stolpert.
AUDIT_LIGHT_KEYS = ("PTAI_PSI_KEY", "PTAI_OPENAI_KEY", "PTAI_PERPLEXITY_KEY",
                    "PTAI_GEMINI_KEY") + FUNNEL_KEYS

#: Einstellungen des Betreibers, keine Schlüssel. Gesucht wie ein Schlüssel
#: (Umgebung, Workspace-.env, zentrale Datei) und in `status()` gezeigt, aber
#: nie als fehlend gezählt. `PTAI_ACCOUNTS_ROOT` und `PTAI_OPERATOR_NAME` haben
#: eine Vorgabe in dem Modul, das sie liest. Die beiden Absender haben keine
#: (Spec 2026-09-11 public release, D6); nur der Versand braucht sie, und Teil B
#: lässt ihn ohne sie abbrechen. Firmenname, Kontakt, Mailadresse und
#: Terminlink haben in `closing.py` ebenfalls keine (Entscheidung 15.09.2026):
#: das Schluss-Panel zeigt eine Zeile je gesetztem und gültigem Wert, ohne
#: einen einzigen davon nur die Herkunftszeile. `PTAI_CLOSING_FILE`, der Pfad zur
#: Schlussseite des Betreibers, hat auch keine: ohne sie endet jedes Dokument
#: mit diesem Panel. `load()` und `export_env()` lassen alle acht aus.
OPERATOR_SETTINGS = (
    "PTAI_ACCOUNTS_ROOT",
    "PTAI_OPERATOR_NAME",
    "PTAI_OPERATOR_CONTACT",
    "PTAI_OPERATOR_EMAIL",
    "PTAI_OPERATOR_BOOKING_URL",
    "PTAI_CLOSING_FILE",
    "PTAI_MAIL_FROM",
    "PTAI_MAIL_REPLY_TO",
)

#: Was `status()` für eine Einstellung zeigt, die nirgends steht. Bewusst nicht
#: "FEHLT": nur das zählt die CLI.
UNSET = "nicht gesetzt"

CENTRAL = Path(os.environ.get("PTAI_ENV_FILE",
                              Path.home() / ".config" / "ptai-ecom" / ".env"))

_ZEILE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env(pfad: Path) -> dict[str, str]:
    """Liest eine `.env`, tolerant. Eine fehlende Datei ist kein Fehler.

    Kommentare und leere Zeilen fallen weg, Anführungszeichen um den Wert
    ebenfalls. Ein leerer Wert zählt als nicht gesetzt: `PTAI_PSI_KEY=` in einer
    halb ausgefüllten Datei soll die nächste Ebene nicht verdecken.
    """
    values: dict[str, str] = {}
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for row in text.splitlines():
        if not row.strip() or row.lstrip().startswith("#"):
            continue
        m = _ZEILE.match(row)
        if not m:
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[m.group(1)] = value
    return values


def get(name: str, workspace: str | os.PathLike = ".") -> str | None:
    """Einen Schlüssel auflösen. Gibt None zurück, wenn er nirgends steht."""
    if os.environ.get(name):
        return os.environ[name]
    lokal = parse_env(Path(workspace) / ".env")
    if lokal.get(name):
        return lokal[name]
    return parse_env(CENTRAL).get(name) or None


def origin(name: str, workspace: str | os.PathLike = ".") -> str | None:
    """Aus welcher Ebene ein Schlüssel kommt, nie der Wert selbst.

    Dieselbe Reihenfolge wie `get()`. Für Hinweise gedacht, die die Quelle
    nennen sollen, ohne dass irgendwo ein Wert auftaucht.
    """
    if os.environ.get(name):
        return "Umgebung"
    if parse_env(Path(workspace) / ".env").get(name):
        return "Workspace-.env"
    if parse_env(CENTRAL).get(name):
        return "zentral"
    return None


def get_together(names: tuple, workspace: str | os.PathLike = ".") -> tuple:
    """Mehrere zusammengehörige Schlüssel aus genau einer Ebene lesen.

    Ein Zugang wie Login und Passwort darf nicht aus zwei verschiedenen Ebenen
    stammen: ein Login aus der Umgebung und ein Passwort aus der zentralen
    Datei ergäben ein Paar, das so nirgends eingetragen wurde. Die API lehnt
    es mit 401 ab, und der 401 zeigt dann auf die falsche Ursache, weil beide
    Werte für sich genommen echt sind.

    Maßgeblich ist die Ebene, in der `names[0]` steht. Fehlende Namen in
    dieser Ebene werden zu None statt aus einer tieferen Ebene nachgeladen.
    Steht `names[0]` nirgends, sind alle Werte None.
    """
    first = names[0]
    if os.environ.get(first):
        return tuple(os.environ.get(n) or None for n in names)
    lokal = parse_env(Path(workspace) / ".env")
    if lokal.get(first):
        return tuple(lokal.get(n) or None for n in names)
    zentral = parse_env(CENTRAL)
    if zentral.get(first):
        return tuple(zentral.get(n) or None for n in names)
    return tuple(None for _ in names)


def load(workspace: str | os.PathLike = ".") -> dict[str, str]:
    """Alle Betreiber-Schlüssel als Wörterbuch, nur die tatsächlich gesetzten."""
    return {k: v for k in OPERATOR_KEYS + FUNNEL_KEYS if (v := get(k, workspace))}


def export_env(workspace: str | os.PathLike = ".") -> dict[str, str]:
    """Setzt die gefundenen Schlüssel in `os.environ` und gibt sie zurück.

    Für Skripte, die ihre Schlüssel aus der Umgebung lesen statt als Argument zu
    nehmen. Bereits gesetzte Variablen werden nie überschrieben, sonst würde
    Ebene 1 der Reihenfolge wirkungslos.
    """
    gefunden = load(workspace)
    for k, v in gefunden.items():
        os.environ.setdefault(k, v)
    return gefunden


def status(workspace: str | os.PathLike = ".") -> list[tuple[str, str]]:
    """Je Schlüssel und Einstellung, woher der Wert kommt. Zeigt nie einen Wert.

    Ein Schlüssel, der nirgends steht, heißt `FEHLT`, eine Einstellung
    `nicht gesetzt` (`UNSET`). Die CLI zählt nur `FEHLT`.
    """
    rows = [(k, origin(k, workspace) or "FEHLT") for k in OPERATOR_KEYS + FUNNEL_KEYS]
    return rows + [(k, origin(k, workspace) or UNSET) for k in OPERATOR_SETTINGS]


if __name__ == "__main__":
    workspace = next((a for a in sys.argv[1:] if not a.startswith("--")), ".")
    print(f"zentrale Datei: {CENTRAL}{'' if CENTRAL.is_file() else '  (existiert nicht)'}")
    fehlt = 0
    for name, source in status(workspace):
        print(f"  {name:<26} {source}")
        fehlt += source == "FEHLT"
    if fehlt:
        print(f"\n{fehlt} Schlüssel fehlen. Die betroffene Quelle meldet sich im Lauf als "
              f"'nicht angeschlossen' und bricht nichts ab.", file=sys.stderr)
    raise SystemExit(0)
