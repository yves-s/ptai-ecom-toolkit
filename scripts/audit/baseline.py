#!/usr/bin/env python3
"""Der Nullpunkt, gegen den jeder spätere Report vergleicht (Spec Abschnitt 10).

Zwei Regeln tragen dieses Modul:

1. **Ein geschriebener Block ist unveränderlich.** Wer versucht, ihn zu
   überschreiben, hat einen Denkfehler, keinen Sonderfall.
   `BlockAlreadyWritten` wird deshalb nie abgefangen und in eine Warnung
   verwandelt.
2. **Ein leerer Block darf nachgetragen werden.** Stufe 1 kann nur sieben der
   zehn Blöcke füllen, weil die Pulls für SEO-Sichtbarkeit, SEA und Katalog
   erst in Stufe 2 kommen. Jeder Block trägt deshalb seinen eigenen `as_of`
   (Datum und Lauf-ID): ein später nachgetragener Block ist damit sichtbar
   nicht derselbe Nullpunkt wie einer aus dem ersten Lauf.

Ablage unter `reporting/baseline/01/baseline.json`. Die `01` steht von Anfang
an da, damit eine bewusste Neu-Baseline später nie die alte überschreiben muss.
"""
import json
import os
from datetime import date
from pathlib import Path

#: Die zehn Blöcke der Baseline (Spec Abschnitt 10). Stufe 1 füllt sieben
#: davon, "seo_visibility", "sea" und "catalogue" bleiben bis Stufe 2 leer.
BLOCKS = (
    "commerce", "traffic", "conversion", "seo_search", "seo_visibility",
    "geo", "sea", "tech", "catalogue", "measurement",
)

#: Die Nummer im Ablagepfad. Eine bewusste Neu-Baseline bekommt später "02"
#: statt die hier gespeicherte zu überschreiben.
NUMBER = "01"

#: Die Überschrift je Block in `baseline.md`, Wortlaut aus der "Bereich"-Spalte
#: der Tabelle in Spec Abschnitt 10. Ein eigenes Wörterbuch statt Ableitung aus
#: dem Blockschlüssel, weil "seo_search" kein lesbares "SEO Suche" ergibt.
HEADINGS = {
    "commerce": "Handel",
    "traffic": "Traffic",
    "conversion": "Conversion",
    "seo_search": "SEO Suche",
    "seo_visibility": "SEO Sichtbarkeit",
    "geo": "GEO",
    "sea": "SEA",
    "tech": "Technik",
    "catalogue": "Katalog",
    "measurement": "Messung",
}


#: Blöcke, deren Zahlen ein laufender Preistest verfälscht. Teilt ein
#: A/B-Werkzeug die Besucher auf zwei Preise auf, sind Conversion Rate **und**
#: Warenkorbwert der Mittelwert zweier Shops. Deshalb beide, nicht nur die
#: Conversion. Der Crawl, die Core Web Vitals und die GEO-Sichtbarkeit sind
#: davon nicht betroffen und stehen bewusst nicht hier.
PRICE_TEST_SENSITIVE = ("commerce", "conversion")


#: Wie belastbar ein einzelner Wert ist. Der Nullpunkt haelt fest, was der
#: Shop ueber sich wusste, und dazu gehoert eine kaputte Messung: sie
#: wegzulassen wuerde behaupten, es haette sie nicht gegeben.
#:
#: `measured`        gemessen, brauchbar
#: `contaminated`    gemessen, aber nachweislich falsch. Wird eingefroren,
#:                   damit spaeter nachvollziehbar ist, worauf Entscheidungen
#:                   beruhten, und traegt Grund, Bruchdatum und Befund
#: `not_measurable`  gar nicht messbar, der Wert ist None
TRUST_STATES = ("measured", "contaminated", "not_measurable")

#: Der Status je Stufe, so wie er in `baseline.md` steht.
TRUST_LABELS = {
    "measured": "gemessen",
    "contaminated": "nachweislich falsch",
    "not_measurable": "nicht messbar",
}


class ContaminatedInput(Exception):
    """Ein abgeleiteter Wert soll aus einem nachweislich falschen entstehen.

    **Das ist der Fall, der wirklich weh tut.** Eine kaputte Sitzungszahl
    einzufrieren ist harmlos, solange sie als kaputt markiert ist: sie sagt,
    was der Shop damals ueber sich wusste, und wenn die Messung repariert ist,
    erklaert das Bruchdatum den Sprung. Gefaehrlich wird sie erst als Nenner.
    Eine Conversion Rate aus einer um Faktor 3,6 ueberhoehten Sitzungszahl
    sieht aus wie eine Kennzahl, ist aber keine, und sie vererbt den Fehler an
    jede Rechnung, die sie weiterverwendet, ohne dass ihr das noch anzusehen
    waere.
    """


class PriceTestRunning(Exception):
    """Der Shop lief zum Messzeitpunkt einen Preistest.

    Kein Sonderfall, sondern der Grund, diesen Block **nicht** einzufrieren:
    die Zahl bildet einen Zustand ab, den es danach nicht mehr gibt, und ein
    Block ist nach dem Schreiben unveränderlich.
    """


class BlockAlreadyWritten(Exception):
    """Ein Block hat bereits Werte. Kein Sonderfall, sondern ein Denkfehler
    beim Aufrufer: die Baseline ist der Nullpunkt, an ihm wird nicht gerüttelt.
    """


def write_block(workspace: Path, block: str, values: dict, *,
                 run_id: str, today: date, sources: dict, trust: dict,
                 known_gaps: tuple[str, ...] = (),
                 price_test: dict | None = None) -> Path:
    """Schreibt einen Block, sofern er noch leer ist.

    `today` und `run_id` kommen vom Aufrufer, nie von der Uhr: der Stand
    eines Blocks muss den Lauf tragen, der ihn tatsächlich gefüllt hat, nicht
    den Tag, an dem dieser Code zufällig ausgeführt wurde.

    `price_test` ist für die Blöcke aus `PRICE_TEST_SENSITIVE` Pflicht und
    kommt aus `gates.price_test_verdict()`. **Geprüft wird nicht, ob der
    Aufrufer blockiert, sondern ob er überhaupt nachgesehen hat:** ein
    Parameter, den der Aufrufer selbst auf "blockiert" setzen müsste,
    erzwingt nichts, weil wer den Test kennt, gar nicht erst schreibt. Fehlt
    die Angabe, scheitert der Aufruf. Damit ist Vergessen ein Fehler, und
    genau das kann eine Regel in Prosa nicht leisten.

    `trust` sagt je Wert, wie belastbar er ist, und ist Pflicht. Dieselbe
    Mechanik wie bei `price_test`: erzwungen wird nicht ein Urteil, sondern
    dass der Aufrufer hingesehen hat. Ein Wert ohne Eintrag gilt als
    `measured`, und wer eine kaputte Messung stillschweigend durchwinkt, tut
    das dann sichtbar und nicht aus Versehen.

    Zwei Formen, beide optional je Wert:

        trust = {
            "sessions": {"status": "contaminated",
                         "reason": "Analytics zaehlt 3,64-mal so viele Besuche "
                                   "wie der Shop als Menschen zaehlt",
                         "break": "2026-06", "finding": "MES-03"},
            "conversion_rate": {"derived_from": ["sessions"]},
        }

    Der erste Eintrag friert die kaputte Zahl bewusst ein: sie ist der
    Zustand, auf dem die Entscheidungen des Kunden beruhten, und ohne sie
    fehlt spaeter die Erklaerung fuer den Sprung nach der Reparatur. Das
    `break`-Datum macht den spaeteren Vergleich ehrlich, statt eine geheilte
    Messung wie einen Einbruch aussehen zu lassen.

    Der zweite scheitert: `conversion_rate` entsteht aus `sessions`, und eine
    Rate aus einer ueberhoehten Zahl ist keine Kennzahl. Sie wird gar nicht
    erst eingefroren.

    `sources` hält je Quelle, aus der dieser Block gerechnet wurde, wann sie
    gezogen wurde (`pulled_at`) und welchen Zeitraum sie abdeckt (`period`,
    optional). Das ist nicht dasselbe wie `today`, und der Unterschied wird
    genau dann sichtbar, wenn er zählt: beim Nachtrag. Ein Block, der im
    Dezember aus Zahlen vom November festgeschrieben wird, trägt sonst nur
    den Dezember, und jeder spätere Vergleich rechnet gegen einen Zeitpunkt,
    an dem nie gemessen wurde. Der abgedeckte Zeitraum gehört aus demselben
    Grund dazu: "Umsatz je Monat über die volle Historie" ist ohne Anfang und
    Ende keine Aussage, sondern eine Zahl.
    """
    if block not in BLOCKS:
        raise ValueError(f"unbekannter Block: {block!r}, erlaubt sind {BLOCKS}")
    if not values:
        # Ein Block ohne Werte gilt danach als geschrieben und ist damit für
        # immer eingefroren, obwohl er nichts enthält: empty_blocks meldet ihn
        # nicht mehr, --backfill füllt ihn nie, und is_complete hält die
        # Baseline für fertig. Ein Block wird entweder mit Inhalt geschrieben
        # oder gar nicht. Hat eine Quelle nichts geliefert, bleibt er leer.
        raise ValueError(
            f"Block {block!r} soll ohne Werte geschrieben werden. Ein leerer Block "
            "wäre unveränderlich leer. Quelle prüfen und den Block leer lassen."
        )

    unexplained = sorted(k for k, v in values.items()
                         if v is None and k not in known_gaps)
    if unexplained:
        # Ein Block ist unveränderlich, sobald er steht. Ein None, das aus
        # einem vertippten Quellfeld stammt, wird damit zu einer für immer
        # eingefrorenen Lücke, und render() schreibt "nicht berechenbar", als
        # wäre sie gemessen. Am 06.09.2026 im ersten echten Lauf genau so
        # passiert: ein falscher Schlüssel, ein None, ein toter Wert.
        raise ValueError(
            f"Block {block!r} enthält None in {unexplained}, ohne dass diese "
            "Felder als bekannte Lücke angemeldet sind. Entweder ist der "
            "Quellfeldname falsch, oder die Lücke ist Absicht und gehört nach "
            "known_gaps. Ein Block ist nach dem Schreiben unveränderlich."
        )

    if not isinstance(trust, dict):
        raise ValueError(
            f"Block {block!r} braucht trust. Je Wert gehoert dazu, ob er "
            "gemessen, nachweislich falsch oder nicht messbar ist, und woraus "
            "er abgeleitet wurde. Ein leeres Dict ist die ausdrueckliche "
            "Aussage 'alles gemessen' und erlaubt."
        )
    unbekannt = sorted(set(trust) - set(values))
    if unbekannt:
        raise ValueError(
            f"Block {block!r}: trust nennt {unbekannt}, was gar nicht in values "
            "steht. Ein Vermerk auf einen Wert, den es nicht gibt, wirkt nie."
        )
    for name, entry in trust.items():
        if not isinstance(entry, dict):
            raise ValueError(f"trust[{name!r}] in Block {block!r} ist kein Dict")
        status = entry.get("status", "measured")
        if status not in TRUST_STATES:
            raise ValueError(
                f"trust[{name!r}] in Block {block!r} hat status {status!r}, "
                f"erlaubt sind {TRUST_STATES}")
        if status == "contaminated" and not entry.get("reason"):
            raise ValueError(
                f"trust[{name!r}] in Block {block!r} ist als falsch markiert, "
                "aber ohne reason. Ein Wert, dem niemand mehr ansieht, warum er "
                "falsch ist, ist nach dem Einfrieren nur noch eine seltsame Zahl."
            )

    verdorben = {n for n, e in trust.items()
                 if e.get("status") == "contaminated"}
    for name, entry in trust.items():
        quellen = set(entry.get("derived_from") or ())
        getroffen = sorted(quellen & verdorben)
        if getroffen:
            raise ContaminatedInput(
                f"Block {block!r}: {name!r} ist aus {getroffen} abgeleitet, und "
                f"diese Werte sind als nachweislich falsch markiert. Die kaputte "
                f"Zahl selbst darf eingefroren werden, eine Rechnung darauf "
                f"nicht: sie sieht aus wie eine Kennzahl und vererbt den Fehler "
                f"an alles, was sie weiterverwendet. {name!r} weglassen oder aus "
                f"einer belastbaren Quelle rechnen."
            )

    if block in PRICE_TEST_SENSITIVE:
        if not isinstance(price_test, dict):
            raise ValueError(
                f"Block {block!r} braucht price_test. Die Zahlen dieses Blocks "
                "sind unter einem laufenden Preistest der Mittelwert zweier "
                "Shops, und der Block ist nach dem Schreiben unveränderlich. "
                "gates.price_test_verdict(crawl) liefert die Angabe."
            )
        if not price_test.get("checked"):
            # "Nicht geprüft" ist keine Freigabe. Ohne Crawl weiß niemand, ob
            # ein Test lief, und danach ist der Block eingefroren.
            raise ValueError(
                f"Block {block!r} soll geschrieben werden, obwohl der Preistest "
                f"nicht geprüft wurde: {price_test.get('evidence')!r}. Erst "
                "prüfen, dann einfrieren."
            )
        if price_test.get("running"):
            raise PriceTestRunning(
                f"Block {block!r} wird nicht geschrieben: {price_test.get('evidence')}. "
                "Eine Conversion unter laufendem Preistest ist der Mittelwert "
                "zweier Shops und taugt nicht als Nullpunkt. Test beenden, "
                "danach mit --backfill nachtragen."
            )

    if not sources:
        # Ein Block ohne Herkunft lässt sich später nicht nachprüfen, und
        # sein Festschreibedatum wird beim Lesen zum Erhebungsdatum. Beides
        # fällt erst auf, wenn der Block längst eingefroren ist.
        raise ValueError(
            f"Block {block!r} soll ohne Quellenangabe geschrieben werden. Ohne "
            "sources ist später weder nachprüfbar, woher die Zahlen kommen, "
            "noch unterscheidbar, wann sie erhoben und wann sie festgeschrieben "
            "wurden."
        )
    for name, entry in sources.items():
        if not isinstance(entry, dict) or not entry.get("pulled_at"):
            raise ValueError(
                f"Quelle {name!r} in Block {block!r} hat kein pulled_at. Ohne "
                "Erhebungsdatum ist der Block nicht von einem gleichzeitig "
                "gemessenen zu unterscheiden."
            )

    data = _load_or_empty(workspace)
    existing = data["blocks"].get(block)
    if existing is not None:
        raise BlockAlreadyWritten(
            f"Block {block!r} ist bereits geschrieben (festgeschrieben am "
            f"{existing['as_of']['written']} im Lauf {existing['as_of']['run_id']}), "
            "ein geschriebener Block ist unveränderlich."
        )

    data["blocks"][block] = {
        "values": values,
        "as_of": {
            # "written" statt "date": der Tag, an dem eingefroren wurde. Wann
            # gemessen wurde, steht je Quelle darunter, und beim Nachtrag ist
            # das ein anderer Tag.
            "written": today.isoformat(),
            "run_id": run_id,
            "sources": sources,
            **({"trust": trust} if trust else {}),
            **({"price_test": price_test} if price_test else {}),
        },
    }
    return _save(workspace, data)


def load(workspace: Path) -> dict:
    """Lädt die Baseline. Eine fehlende Datei ist ein Fehler, kein leerer Stand:
    wer lädt, erwartet, dass vorher mindestens ein Block geschrieben wurde."""
    return json.loads(_path(workspace).read_text(encoding="utf-8"))


def empty_blocks(workspace: Path) -> list[str]:
    """Die Blöcke, die noch keinen Stand tragen, in der Reihenfolge von BLOCKS."""
    data = _load_or_empty(workspace)
    return [block for block in BLOCKS if data["blocks"].get(block) is None]


def is_complete(workspace: Path) -> bool:
    """Alle zehn Blöcke tragen einen Stand, egal aus welchem Lauf."""
    return not empty_blocks(workspace)


def render(workspace: Path) -> Path:
    """Erzeugt `baseline.md`, die lesbare Fassung von `baseline.json`.

    Wird aus der JSON generiert, nie von Hand gepflegt. Jeder Block bekommt
    eine eigene Überschrift in der Reihenfolge von `BLOCKS` und zeigt seinen
    eigenen `as_of`: ein später nachgetragener Block ist so sichtbar nicht
    derselbe Nullpunkt wie einer aus dem ersten Lauf.

    Ein leerer Block erscheint als Satz "noch nicht erhoben", nie als Null,
    Strich oder leere Tabellenzeile. Eine gemessene Null und ein noch nicht
    gemessener Block dürfen im Dokument nicht verwechselbar sein, das ist der
    einzige Grund, warum diese Funktion existiert statt die JSON von Hand zu
    lesen.

    Aus demselben Grund trägt ein Wert mit Vermerk in `as_of.trust` seinen
    Status sichtbar im Dokument, dazu Grund, Monat des Bruchs, Befund und jede
    Korrektur. Sonst sieht ein eingefrorener, nachweislich falscher Wert aus
    wie ein gemessener, und der Leser erfährt es nur, wenn er die JSON öffnet.
    """
    data = _load_or_empty(workspace)
    lines = ["# Baseline", ""]
    for block in BLOCKS:
        lines.append(f"## {HEADINGS[block]}")
        lines.append("")
        entry = data["blocks"].get(block)
        if entry is None:
            lines.append("Noch nicht erhoben.")
            lines.append("")
            continue
        lines.extend(_render_as_of(entry["as_of"]))
        lines.extend(_render_values(entry["values"], _checked_trust(block, entry)))
    markdown = "\n".join(lines).rstrip("\n") + "\n"
    return _write_atomic(_path(workspace).with_name("baseline.md"), markdown)


def _checked_trust(block: str, entry: dict) -> dict:
    """Die Vermerke eines Blocks, geprüft, bevor sie gerendert werden.

    `write_block` prüft dasselbe beim Schreiben, aber Korrekturen werden nach
    dem Einfrieren von Hand in `baseline.json` nachgetragen. Ein vertippter
    Schlüssel oder Status ließe einen Vermerk sonst still aus `baseline.md`
    verschwinden, und das ist genau der Fehler, den der Vermerk verhindern soll.
    """
    trust = entry["as_of"].get("trust") or {}
    unknown = sorted(set(trust) - set(entry["values"]))
    if unknown:
        raise ValueError(
            f"Block {block!r}: trust nennt {unknown}, was nicht in values steht. "
            "Der Vermerk würde in baseline.md fehlen. Schlüssel in baseline.json "
            "prüfen."
        )
    for name, note in trust.items():
        status = note.get("status", "measured")
        if status not in TRUST_LABELS:
            raise ValueError(
                f"Block {block!r}: trust[{name!r}] hat status {status!r}, "
                f"erlaubt sind {TRUST_STATES}"
            )
    return trust


def _render_as_of(as_of: dict) -> list[str]:
    """Der Stand eines Blocks: wann festgeschrieben, wann erhoben, welcher Zeitraum.

    Beide Daten stehen im Dokument, nicht nur eines. Im Erstlauf sind sie
    derselbe Tag und die Zeile liest sich wie vorher; bei einem Nachtrag
    laufen sie auseinander, und genau dann muss der Leser sehen, dass die
    Zahlen älter sind als ihr Eintrag in die Baseline. Ohne diese Trennung
    liest der nächste Vergleich das Festschreibedatum als Messzeitpunkt.
    """
    lines = [f"Festgeschrieben: {as_of['written']} (Lauf {as_of['run_id']})", ""]
    sources = as_of.get("sources") or {}
    if not sources:
        return lines
    lines.append("| Quelle | Erhoben am | Zeitraum |")
    lines.append("|---|---|---|")
    for name, entry in sources.items():
        period = entry.get("period") or {}
        if period.get("start") and period.get("end"):
            span = f"{period['start']} bis {period['end']}"
        else:
            # Crawl, Screenshots und Core Web Vitals sind Momentaufnahmen.
            # Ein erfundener Zeitraum wäre schlimmer als keiner.
            span = "Momentaufnahme"
        lines.append(f"| {name} | {entry.get('pulled_at')} | {span} |")
    lines.append("")
    return lines


def _render_values(values: dict, trust: dict) -> list[str]:
    """Rendert die `values` eines Blocks generisch, ohne Kenntnis der
    einzelnen Kennzahl-Namen: welches Feld was bedeutet, steht im
    Kennzahlen-Katalog, nicht hier. Diese Funktion darf nur eins sicherstellen:
    dass kein Wert beim Rendern verloren geht.

    Einfache Werte (Zahl, Text, Bool, None) werden zu einer Tabellenzeile.
    Eine Zeitreihe wie "Umsatz je Monat" kommt als verschachteltes Dict herein
    und bekommt einen eigenen Abschnitt mit eigener Tabelle, eine Liste wie das
    GEO-Query-Set ebenso.

    `trust` sind die geprüften Vermerke aus `as_of`. Ein einfacher Wert mit
    Vermerk trägt seinen Status in der eigenen Zeile, damit ihn auch sieht,
    wer nur die Tabelle überfliegt; der Vermerk selbst steht unter der
    Tabelle. Bei Zeitreihe und Liste steht er zwischen Überschrift und Zahlen.
    Werte ohne Vermerk rendern Byte für Byte wie vor dem 12.09.2026.
    """
    simple = [(k, v) for k, v in values.items() if not isinstance(v, (dict, list))]
    nested = [(k, v) for k, v in values.items() if isinstance(v, (dict, list))]

    lines: list[str] = []
    if simple:
        lines.append("| Kennzahl | Wert |")
        lines.append("|---|---|")
        for key, value in simple:
            cell = _format_value(value)
            if key in trust:
                cell += f" ({TRUST_LABELS[trust[key].get('status', 'measured')]})"
            lines.append(f"| {key} | {cell} |")
        lines.append("")
        for key, _ in simple:
            if key in trust:
                lines.append(f"> **{key}**")
                lines.extend(_render_note(trust[key]))

    for key, value in nested:
        lines.append(f"### {key}")
        lines.append("")
        if key in trust:
            lines.extend(_render_note(trust[key]))
        if isinstance(value, dict):
            lines.append("| Schlüssel | Wert |")
            lines.append("|---|---|")
            for subkey, subvalue in value.items():
                lines.append(f"| {subkey} | {_format_value(subvalue)} |")
        else:
            lines.extend(_render_list(value))
        lines.append("")

    return lines


def _render_note(note: dict) -> list[str]:
    """Der Vermerk zu einem Wert: Status, Grund, Monat des Bruchs, Befund und
    jede Korrektur mit ihrem Datum, jeweils nur, wenn vorhanden.

    Als Zitat statt als Aufzählung, weil eine Aufzählung in Markdown mit einer
    direkt folgenden Werteliste zu einer einzigen Liste zusammenläuft. Bei
    `measured` heißt der Text "Hinweis" statt "Grund": er beschreibt dort eine
    Einschränkung, keinen Fehler. Ohne `status` gilt ein Wert als gemessen,
    genau wie in `write_block`.
    """
    status = note.get("status", "measured")
    lines = [f"> - Status: {TRUST_LABELS[status]}"]
    if note.get("reason"):
        label = "Hinweis" if status == "measured" else "Grund"
        lines.append(f"> - {label}: {note['reason']}")
    if note.get("break"):
        lines.append(f"> - Monat des Bruchs: {note['break']}")
    if note.get("finding"):
        lines.append(f"> - Befund: {note['finding']}")
    for correction in note.get("corrections") or ():
        lines.append(f"> - Korrektur vom {correction['date']}: {correction['note']}")
    lines.append("")
    return lines


def _render_list(items: list) -> list[str]:
    """Eine Liste aus `values`: als Tabelle, wenn ihre Einträge Dicts sind
    (etwa die Wettbewerberliste), sonst als Aufzählung (etwa das
    GEO-Query-Set)."""
    if not items:
        return ["Leere Liste."]
    if all(isinstance(entry, dict) for entry in items):
        columns: list[str] = []
        for entry in items:
            for key in entry:
                if key not in columns:
                    columns.append(key)
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        for entry in items:
            values_per_column = (_format_value(entry.get(column)) for column in columns)
            lines.append("| " + " | ".join(values_per_column) + " |")
        return lines
    return [f"- {_format_value(entry)}" for entry in items]


def _format_value(value) -> str:
    """Formatiert einen einzelnen Wert für die Markdown-Ausgabe.

    `None` heißt "nicht berechenbar" und wird nie als leere Zelle oder als
    Null ausgegeben, sonst liest sich eine fehlende Zahl wie eine gemessene.
    Ein Bool wird ausgeschrieben, weil "True" und "False" kein Deutsch sind
    und in einem Kundendokument nichts verloren haben.
    """
    if value is None:
        return "nicht berechenbar"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    return str(value)


def _load_or_empty(workspace: Path) -> dict:
    """Lädt die Baseline oder legt das leere Grundgerüst an.

    Eine fehlende Datei heißt: noch kein Block wurde je geschrieben. Eine
    beschädigte Datei heißt Abbruch mit Ansage, nie ein stiller Neuanfang: der
    würde jeden bereits geschriebenen, unveränderlichen Block wegwerfen.
    """
    path = _path(workspace)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"blocks": {block: None for block in BLOCKS}}
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path} ist beschädigt ({error}). Wird nicht still neu angelegt, "
            "weil das jeden bereits geschriebenen Block wegwerfen würde. "
            "Datei prüfen und entweder reparieren oder löschen."
        ) from error


def _save(workspace: Path, data: dict) -> Path:
    """Schreibt die Baseline atomar: erst daneben, dann umbenennen.

    Ein mitten im Schreiben abgebrochener Lauf darf keine halb geschriebene
    Datei hinterlassen, sonst existiert ein Block, dessen `values` und `as_of`
    nicht zusammenpassen. `os.replace` ist innerhalb eines Dateisystems atomar:
    danach existiert der alte oder der neue Stand, nie ein halber.
    """
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return _write_atomic(_path(workspace), content)


def _write_atomic(path: Path, content: str) -> Path:
    """Schreibt `content` atomar nach `path`: erst daneben, dann umbenennen.
    Gemeinsame Mechanik für `baseline.json` und die daraus gerenderte
    `baseline.md`, ein mitten im Schreiben abgebrochener Lauf darf für keine
    der beiden Dateien eine halb geschriebene Fassung hinterlassen.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _path(workspace: Path) -> Path:
    """Der eine Ort, an dem der Pfad zur baseline.json gebildet wird."""
    return Path(workspace) / "reporting" / "baseline" / NUMBER / "baseline.json"
