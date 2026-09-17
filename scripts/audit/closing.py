#!/usr/bin/env python3
"""Der Schluss jedes Dokuments: die Schlussseite des Betreibers oder das neutrale Panel.

Entscheidung vom 15.09.2026, zweiter Teil: jedes Dokument des Plugins endet mit
derselben Schlussseite, der große Audit, der Monats-Report und der Report von
audit-light. Sie ist eine Verkaufsseite des Betreibers und liegt als eine
HTML-Datei außerhalb des Repos, auf die `PTAI_CLOSING_FILE` zeigt. Die Seite von
Path to AI trägt Kundenlogos und Kundenzitate und kann deshalb nie hier liegen:
das Plugin wird öffentlich verteilt, und Kundennamen hält die Leak-Prüfung auf.

`apply()` setzt den Inhalt der Datei unverändert zwischen
`<!-- CLOSING:start -->` und `<!-- CLOSING:end -->` ein und liest ihn nicht. Die
Markierungen bleiben stehen, damit ein zweiter Aufruf auf der gespeicherten
Datei dieselbe Stelle findet. Fehlt die Datei, ist sie nicht lesbar oder leer,
steht eine Zeile auf stderr, und das Dokument bekommt den neutralen Schluss; ein
Render bricht darüber nie ab. Der Report von audit-light folgt derselben Regel
in `scripts/report/sales/report-pdf-full.mjs`, die Web-Fassung des Audits
(`report_web.py`) trägt dieselben Markierungen und bekommt denselben Schluss.
Die Datei hält:

    genau ein <section>-Element auf oberster Ebene, darin optional ein <style>
    nur Selektoren unter der eigenen Klasse dieses Elements
    alle Bilder und Schriften als data:-URIs
    eine volle A4-Seite im Hochformat:
        break-before: page; width: 210mm; height: 297mm; box-sizing: border-box
    keine der Zeichenfolgen <!-- CLOSING:start -->, <!-- CLOSING:end --> und
        __CLOSING__, sonst verweigert `apply()` sie mit einem Fehler

Ein zweiter Aufruf auf einem fertigen Dokument:

    Schlussseite gesetzt   ersetzt, was zwischen den Markierungen steht, auch
                           einen neutralen Schluss oder eine frühere Seite
    ohne Schlussseite      füllt den Platzhalter, solange er da ist. Ist er
                           schon ersetzt, bleibt das Dokument unverändert, und
                           eine Zeile sagt, dass nur die Vorlage den neutralen
                           Schluss samt Logo und Fußzeile neu baut

Der neutrale Schluss, Entscheidung vom 15.09.2026, erster Teil: das Panel zeigt
ausschließlich die Kontaktangaben des Betreibers, keinen Satz. Vom 12.09.2026
an trug der Audit eine Überschrift ("Wie es weitergeht"), einen Absatz und einen
Termin-Button aus dem Schluss des Verkaufs-PDFs, der Monats-Report einen
Schlusssatz aus einer Mail. Yves hat beide als beliebig verworfen: die
Kontaktangaben sagen schon, wie man den Betreiber erreicht. Bis zum 12.09.2026
stand im Panel nur ein Satz zur Herkunft (Spec 2026-09-11 public release, B1).

Audit und Monats-Report zeigen seither dasselbe Panel: `audit_html()` und
`report_html()` bleiben zwei Funktionen, damit die Aufrufer unverändert
bleiben, rendern aber über einen gemeinsamen Baustein. Der Markdown-Report
endet immer neutral (`report_markdown()`), auch wenn eine Schlussseite gesetzt ist.

Die Werte stehen deshalb nie im Plugin, sondern in Einstellungen, gesucht
wie jeder Schlüssel über `audit.env` (Umgebung, Workspace-`.env`, zentrale Datei):

    PTAI_CLOSING_FILE          Pfad zur Schlussseite, eine führende ~ wird aufgelöst.
                               Ist die Datei brauchbar, entfällt das Panel samt
                               der vier Zeilen darunter
    PTAI_OPERATOR_NAME         Firmenname, nur wenn ausdrücklich gesetzt, sonst
                               entfällt die Zeile Unternehmen. Der Vorgabewert
                               "Dienstleister" aus `measures.responsible_label()`
                               ist eine Anzeige für Maßnahmen und Fließtext,
                               keine Tatsache für eine Kontaktzeile
    PTAI_OPERATOR_CONTACT      wer ansprechbar ist, etwa ein Name
    PTAI_OPERATOR_EMAIL        nur eine Adresse der Form name@beispiel.example, sonst entfällt die Zeile
    PTAI_OPERATOR_BOOKING_URL  nur http:// oder https:// mit einem Host, sonst entfällt die Zeile

Dieses Modul ist die einzige Quelle. Die frühere Markdown-Datei unter
`assets/brand/` ist entfernt, die beiden Vorlagen tragen nur noch den Platzhalter
im Panel und die beiden Markierungen darum.

CLI, die Report-Skill ruft sie im Workspace auf:
    python3 -m audit.closing apply <html-datei> [workspace]
    python3 -m audit.closing report-html [workspace]
    python3 -m audit.closing report-md [workspace]
"""
import html
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from audit import env

#: Wohin der Herkunftsvermerk zeigt.
ORIGIN_URL = "https://path-to-ai.com"

#: Die Herkunftszeile in beiden Formen. Der Wochen-Puls endet mit derselben
#: Zeile als Markdown (`skills/pulse/SKILL.md`), ein Test hält beide gleich.
ORIGIN_HTML = f'Erstellt mit ptai-ecom von <a href="{ORIGIN_URL}">Path to AI</a>.'
ORIGIN_MARKDOWN = f"Erstellt mit ptai-ecom von [Path to AI]({ORIGIN_URL})."

#: Eyebrow-Label über dem Kontaktblock, in Audit und Monats-Report gleich.
CONTACT_LABEL = "Kontakt"

#: Der Platzhalter im Panel beider Vorlagen, er wird zum neutralen Schluss.
PLACEHOLDER = "__CLOSING__"

#: Die Markierungen um das Panel in beiden Vorlagen und in der Web-Fassung. Was
#: zwischen ihnen steht, ersetzt die Schlussseite; sie selbst bleiben stehen.
START = "<!-- CLOSING:start -->"
END = "<!-- CLOSING:end -->"

#: Die Einstellung mit dem Pfad zur Schlussseite des Betreibers.
CLOSING_FILE = "PTAI_CLOSING_FILE"

#: Was `apply()` im Dokument sucht und deshalb nie in der Schlussseite stehen
#: darf: ein END darin beendete den Abschnitt beim nächsten Aufruf mitten in der
#: Seite, ein Platzhalter darin würde ohne Einstellung neutral gefüllt.
RESERVED = (START, END, PLACEHOLDER)

#: Die eine Zeile, wenn ohne Schlussseite nichts mehr zu füllen ist.
KEPT_HINT = (f"der Platzhalter {PLACEHOLDER} ist schon ersetzt, das Dokument bleibt "
             "unverändert. Den neutralen Schluss baut nur die Vorlage neu.")

#: Was `_apply()` mit dem Dokument getan hat.
_INSERTED, _FILLED, _KEPT = "inserted", "filled", "kept"

#: Eine Adresse der Form name@beispiel.example. Keine Leerzeichen, Klammern oder
#: Anführungszeichen: der Wert steht in einem href und in einem Markdown-Link.
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")

#: Zeichen, die in Markdown etwas bedeuten und im Wert Text bleiben sollen.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _setting(name: str, workspace: str | os.PathLike) -> str:
    return (env.get(name, workspace) or "").strip()


def _name(workspace: str | os.PathLike) -> str | None:
    """Der Firmenname, nur wenn `PTAI_OPERATOR_NAME` ausdrücklich gesetzt ist.

    Kein Rückgriff auf `measures.responsible_label()`: dessen Vorgabe
    "Dienstleister" passt in einen Maßnahmen-Satz, aber nicht als Firmenname in
    einer Kontaktzeile, die es so gibt oder gar nicht.
    """
    return _setting("PTAI_OPERATOR_NAME", workspace) or None


def _contact(workspace: str | os.PathLike) -> str | None:
    return _setting("PTAI_OPERATOR_CONTACT", workspace) or None


def _email(workspace: str | os.PathLike) -> str | None:
    """Die Mailadresse, nur wenn sie wie eine aussieht. Sonst entfällt die Zeile."""
    value = _setting("PTAI_OPERATOR_EMAIL", workspace)
    return value if _EMAIL.fullmatch(value) else None


def _booking_url(workspace: str | os.PathLike) -> str | None:
    """Der Terminlink, nur mit http oder https und einem Host.

    Alles andere fällt weg statt im href zu landen, auch `javascript:`. Eine
    fehlende Zeile ist sichtbar, ein Link, der etwas anderes tut als einen
    Termin zu öffnen, nicht.
    """
    value = _setting("PTAI_OPERATOR_BOOKING_URL", workspace)
    if not value or re.search(r"\s", value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return value


def _fields(workspace: str | os.PathLike) -> tuple[str | None, str | None, str | None, str | None]:
    """Name, Ansprechpartner, Mailadresse und Terminlink, nur gültige Werte."""
    return (_name(workspace), _contact(workspace), _email(workspace), _booking_url(workspace))


def _link_text(url: str) -> str:
    """Der sichtbare Linktext eines Terminlinks: ohne Schema, ohne Schrägstrich
    am Ende. `https://cal.com/beispiel/30min` wird `cal.com/beispiel/30min`.
    """
    return re.sub(r"^https?://", "", url).rstrip("/")


def _row(label: str, value_html: str) -> str:
    return (f'<div class="summary-row"><div class="summary-label">{label}</div>'
            f'<div class="summary-value">{value_html}</div></div>')


def _rows_html(name: str | None, contact: str | None, email: str | None,
              url: str | None) -> list[str]:
    """Die Kontaktzeilen als fertiges HTML, eine je gesetztem und gültigem Wert."""
    rows = []
    if name:
        rows.append(_row("Unternehmen", html.escape(name)))
    if contact:
        rows.append(_row("Ansprechpartner", html.escape(contact)))
    if email:
        mail = html.escape(email)
        rows.append(_row("E-Mail", f'<a href="mailto:{mail}">{mail}</a>'))
    if url:
        rows.append(_row("Termin", f'<a href="{html.escape(url)}">{html.escape(_link_text(url))}</a>'))
    return rows


def _origin_html() -> str:
    return f'<p class="origin">{ORIGIN_HTML}</p>'


def _markdown_text(value: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value)


def _panel_html(workspace: str | os.PathLike) -> str:
    """Das Schluss-Panel, für Audit und Monats-Report identisch: reine
    Kontaktfakten des Betreibers, kein Satz (Entscheidung 15.09.2026). Ohne
    gültige Einstellung bleibt nur die Herkunftszeile.
    """
    rows = _rows_html(*_fields(workspace))
    parts = []
    if rows:
        parts.append(f'<p class="eyebrow eyebrow--line">{CONTACT_LABEL}</p>')
        parts.append('<div class="summary">\n' + "\n".join(rows) + "\n</div>")
    parts.append(_origin_html())
    return "\n".join(parts)


def audit_html(workspace: str | os.PathLike = ".") -> str:
    """Inhalt des Schluss-Panels im großen Audit, zwischen Logo und Fußzeile.

    Identisch mit `report_html()`, beide Namen bleiben für die Aufrufer erhalten.
    """
    return _panel_html(workspace)


def report_html(workspace: str | os.PathLike = ".") -> str:
    """Inhalt des Schluss-Panels im Monats-Report. Identisch mit `audit_html()`."""
    return _panel_html(workspace)


def report_markdown(workspace: str | os.PathLike = ".") -> str:
    """Der Schluss des Markdown-Reports, derselbe Inhalt wie `report_html()`."""
    name, contact, email, url = _fields(workspace)
    rows = []
    if name:
        rows.append(f"- Unternehmen: {_markdown_text(name)}")
    if contact:
        rows.append(f"- Ansprechpartner: {_markdown_text(contact)}")
    if email:
        rows.append(f"- E-Mail: [{_markdown_text(email)}](mailto:{email})")
    if url:
        rows.append(f"- Termin: [{_markdown_text(_link_text(url))}]({url})")
    parts = []
    if rows:
        parts.append(f"## {CONTACT_LABEL}\n\n" + "\n".join(rows))
    parts.append(ORIGIN_MARKDOWN)
    return "\n\n".join(parts)


def closing_file(workspace: str | os.PathLike = ".") -> str | None:
    """Der Inhalt der Schlussseite aus `PTAI_CLOSING_FILE`, unverändert, oder None.

    None ohne Meldung, wenn die Einstellung nirgends steht. None mit genau einer
    Zeile auf stderr, wenn sie gesetzt ist, die Datei aber fehlt, nicht als
    UTF-8 lesbar oder leer ist: dann bekommt das Dokument den neutralen Schluss.
    """
    value = _setting(CLOSING_FILE, workspace)
    if not value:
        return None
    try:
        text = Path(value).expanduser().read_text(encoding="utf-8")
    except FileNotFoundError:
        reason = "gibt es nicht"
    except (OSError, ValueError, RuntimeError):
        # OSError: ein Ordner oder keine Rechte. ValueError: kein UTF-8.
        # RuntimeError: die ~ lässt sich nicht auflösen.
        reason = "ist nicht lesbar"
    else:
        if text.strip():
            return text
        reason = "ist leer"
    print(f"Hinweis: {CLOSING_FILE} zeigt auf {value}, die Datei {reason}. "
          "Das Dokument endet mit dem neutralen Schluss.", file=sys.stderr)
    return None


def _region(html_text: str) -> tuple[int, int] | None:
    """Anfang und Ende des markierten Abschnitts, beide Markierungen eingeschlossen."""
    start = html_text.find(START)
    if start < 0:
        return None
    end = html_text.find(END, start + len(START))
    return None if end < 0 else (start, end + len(END))


def _apply(html_text: str, workspace: str | os.PathLike) -> tuple[str, str]:
    """`apply()` plus was geschehen ist: `_INSERTED`, `_FILLED` oder `_KEPT`."""
    page = closing_file(workspace)
    if page is None:
        if PLACEHOLDER not in html_text:
            return html_text, _KEPT
        return html_text.replace(PLACEHOLDER, report_html(workspace)), _FILLED
    found = [marker for marker in RESERVED if marker in page]
    if found:
        raise ValueError(
            f"{CLOSING_FILE} zeigt auf {_setting(CLOSING_FILE, workspace)}, und die Datei "
            f"enthält {', '.join(found)}. Damit markiert das Plugin den Schluss im "
            "Dokument, ein zweites Einsetzen fände die falsche Stelle. Die Schlussseite "
            "ohne diese Zeichenfolge speichern.")
    region = _region(html_text)
    if region is None:
        raise ValueError(
            f"{CLOSING_FILE} ist gesetzt, aber im Dokument fehlen die Markierungen "
            f"{START} und {END} um den Schluss. Das Dokument neu aus der Vorlage bauen.")
    start, end = region
    body = page if page.endswith("\n") else page + "\n"
    return html_text[:start] + f"{START}\n{body}{END}" + html_text[end:], _INSERTED


def apply(html_text: str, workspace: str | os.PathLike = ".") -> str:
    """Setzt den Schluss in ein fertiges Dokument ein.

    Mit einer brauchbaren Schlussseite aus `PTAI_CLOSING_FILE` ersetzt ihr
    Inhalt alles zwischen `START` und `END`. Die Markierungen bleiben stehen,
    ein zweiter Aufruf ersetzt deshalb wieder genau diesen Abschnitt. Sonst wird
    `PLACEHOLDER` zum neutralen Schluss aus `report_html()`. Ist er schon
    ersetzt, kommt das Dokument unverändert zurück, mit `KEPT_HINT` auf stderr.

    `ValueError`, statt die Seite irgendwo anzuhängen oder still wegzulassen,
    wenn die Markierungen fehlen, obwohl eine Schlussseite gesetzt ist, und
    wenn die Schlussseite eine Zeichenfolge aus `RESERVED` enthält.
    """
    text, outcome = _apply(html_text, workspace)
    if outcome == _KEPT:
        print(f"Hinweis: {KEPT_HINT}", file=sys.stderr)
    return text


COMMANDS = {"report-html": report_html, "report-md": report_markdown}

USAGE = ("Aufruf: python3 -m audit.closing report-html|report-md [workspace]\n"
         "        python3 -m audit.closing apply <html-datei> [workspace]")


def _apply_file(target: str, workspace: str) -> int:
    """Setzt den Schluss in eine gespeicherte HTML-Datei ein und schreibt sie zurück."""
    path = Path(target)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as err:
        print(f"{target} ist nicht lesbar: {err}", file=sys.stderr)
        return 1
    try:
        text, outcome = _apply(text, workspace)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    if outcome == _KEPT:
        # Nicht zurückschreiben: die Datei bleibt, wie sie ist, auch ihr Zeitstempel.
        print(f"Schluss in {target}: {KEPT_HINT}")
        return 0
    path.write_text(text, encoding="utf-8")
    if outcome == _INSERTED:
        print(f"Schluss in {target}: die Schlussseite aus {CLOSING_FILE}.")
    else:
        print(f"Schluss in {target}: der neutrale Schluss.")
    return 0


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["apply"] and len(args) in (2, 3):
        return _apply_file(args[1], args[2] if len(args) == 3 else ".")
    if not args or args[0] not in COMMANDS or len(args) > 2:
        print(USAGE, file=sys.stderr)
        return 2
    print(COMMANDS[args[0]](args[1] if len(args) > 1 else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
