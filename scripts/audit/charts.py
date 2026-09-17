#!/usr/bin/env python3
"""Diagramme fuer den Audit-Report, als reines SVG.

Kein Chart-Paket: das PDF entsteht in headless Chrome mit einer strengen
CSP, und ein Diagramm, das erst im Browser gerechnet wird, ist im Druck ein
leeres Rechteck. SVG steht im Dokument und rendert ueberall gleich.

Die Bauformen folgen belegter Praxis, nicht Geschmack:

* **Kanalvergleich: zwei Balkenpanels nebeneinander, gleiche Sortierung.**
  Keine Grafik mit zwei Y-Achsen. Stephen Few, "Dual-Scaled Axes in Graphs":
  *"Because bar graphs are designed for magnitude comparisons, a graph with a
  dual-scaled axis should never exclusively encode values as bars."* Der
  Schnittpunkt zweier Linien mit verschiedenen Skalen bedeutet nichts und
  wird trotzdem gelesen. Die Form heisst bei IBCS Multi-Tier Bar Chart.
* **Kein Tortendiagramm fuer Anteile.** Few, "Save the Pies for Dessert":
  *"Pie charts only make it easy to judge the magnitude of a slice when it is
  close to 0%, 25%, 50%, 75%, or 100%."*
* **Kaufweg: Balken plus Prozentspalte, nie die Trichterform.** Der Trichter
  kodiert nichts: seine Breite folgt der Position im Stapel, nicht dem Wert,
  ihm fehlt die gemeinsame Grundlinie, und bei einem Verhaeltnis von 1 zu 30
  zwischen erster und letzter Stufe verschwinden die kleinen Werte. (Peltier,
  Storytelling with Data; Few und IBCS aeussern sich zu Trichtern nicht.)
* **Jahresvergleich: Saeulen Ist gegen Vorjahr, darunter die Abweichung.**
  IBCS-Szenarienotation: Ist solide dunkel (AC), Vorjahr hell (PY), die
  Abweichung in einem eigenen Panel, weil sie die Aussage ist.
* **Balken beginnen bei null**, weil die Laenge den Wert kodiert (Knaflic).
  Direktbeschriftung statt Legende, weil eine Legende den Blick hin und her
  springen laesst (NN/g).
* **Rot und Gruen nur fuer Abweichungen**, nie als Markenfarbe im Diagramm.
"""
from __future__ import annotations

import html

# Brand-Farben aus assets/brand/report.css. Bewusst hier dupliziert: ein SVG
# kann keine CSS-Variable des Elterndokuments aufloesen, wenn es als Bild
# gerendert wird, und der Druck soll nicht von der Kaskade abhaengen.
INK = "#14150F"
BLUE = "#1B2A6B"
ACCENT = "#E2381B"
LIGHT = "#C9CEE3"
RULE = "rgba(20,21,15,0.13)"
GREY = "#6B6D63"

FONT = ("font-family:'Inter','Helvetica Neue',Arial,sans-serif;"
           "font-size:8.5px;fill:%s" % INK)
LABEL = ("font-family:'JetBrains Mono',ui-monospace,monospace;font-size:7.5px;"
         "letter-spacing:0.08em;text-transform:uppercase;fill:%s" % BLUE)


def _e(t) -> str:
    return html.escape(str(t), quote=False)


def _frame(content: str, width: int, height: int, title: str) -> str:
    return (f'<figure class="chart"><svg viewBox="0 0 {width} {height}" '
            f'width="100%" role="img" aria-label="{_e(title)}" '
            f'xmlns="http://www.w3.org/2000/svg">{content}</svg></figure>')


def bar_pair(rows, links_titel, rechts_titel, title,
               links_fmt=str, rechts_fmt=str) -> str:
    """Zwei Balkenpanels nebeneinander, gemeinsame Kategorienachse.

    `zeilen` ist eine Liste aus (Name, Wert links, Wert rechts). Die
    Sortierung kommt von aussen und ist in beiden Panels dieselbe: nur dann
    laesst sich ablesen, wo viel Traffic wenig Umsatz traegt.
    """
    rows = [z for z in rows if z[1] is not None or z[2] is not None]
    if not rows:
        return ""
    line_height, header = 20, 34
    height = header + len(rows) * line_height + 6
    width, label_width, luecke = 560, 130, 26
    panel = (width - label_width - luecke) / 2
    max_l = max((z[1] or 0) for z in rows) or 1
    max_r = max((z[2] or 0) for z in rows) or 1
    x_l, x_r = label_width, label_width + panel + luecke

    parts = [f'<text x="{x_l}" y="12" style="{LABEL}">{_e(links_titel)}</text>',
             f'<text x="{x_r}" y="12" style="{LABEL}">{_e(rechts_titel)}</text>',
             f'<line x1="0" y1="20" x2="{width}" y2="20" '
             f'stroke="{INK}" stroke-width="0.8"/>']
    for i, (name, links, rechts) in enumerate(rows):
        y = header + i * line_height
        parts.append(f'<text x="0" y="{y + 9}" style="{FONT}">{_e(name)}</text>')
        for x0, value, mx, fmt, color in ((x_l, links, max_l, links_fmt, BLUE),
                                         (x_r, rechts, max_r, rechts_fmt, INK)):
            if value is None:
                parts.append(f'<text x="{x0}" y="{y + 9}" style="{FONT};'
                             f'fill:{GREY}">nicht erhoben</text>')
                continue
            w = max(1.0, panel * 0.62 * (value / mx))
            parts.append(f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="11" '
                         f'fill="{color}"/>')
            parts.append(f'<text x="{x0 + w + 4:.1f}" y="{y + 9}" '
                         f'style="{FONT}">{_e(fmt(value))}</text>')
    return _frame("".join(parts), width, int(height), title)


def step_bars(stufen, title, fmt=str,
                 quote_kopf="Anteil aller Sitzungen") -> str:
    """Der Kaufweg als Balken mit gemeinsamer Grundlinie.

    `stufen` ist eine Liste aus (Name, Wert, Quote als fertiger Text). Keine
    Trichterform: die kodiert nichts und verschluckt die kleinen Stufen genau
    dort, wo die Aussage sitzt.

    **Die Quote ist der Anteil an allen Sitzungen, nicht an der Stufe davor.**
    GA4 zaehlt je Stufe die Sitzungen mit diesem Ereignis, unabhaengig von der
    Reihenfolge, und eine Uebergangsquote behauptet einen Weg, den die Zahlen
    nicht beschreiben.
    """
    stufen = [s for s in stufen if s[1] is not None]
    if not stufen:
        return ""
    line_height, header = 24, 30
    width, label_width, quote = 560, 150, 128
    balken = width - label_width - quote - 10
    height = header + len(stufen) * line_height + 6
    mx = max(s[1] for s in stufen) or 1
    parts = [f'<text x="0" y="12" style="{LABEL}">Stufe</text>',
             f'<text x="{label_width}" y="12" style="{LABEL}">Sitzungen</text>',
             f'<text x="{width}" y="12" text-anchor="end" style="{LABEL}">'
             f"{_e(quote_kopf)}</text>",
             f'<line x1="0" y1="18" x2="{width}" y2="18" '
             f'stroke="{INK}" stroke-width="0.8"/>']
    for i, (name, value, weiter) in enumerate(stufen):
        y = header + i * line_height
        w = max(1.0, balken * (value / mx))
        parts += [
            f'<text x="0" y="{y + 11}" style="{FONT}">{_e(name)}</text>',
            f'<rect x="{label_width}" y="{y + 1}" width="{w:.1f}" height="13" '
            f'fill="{BLUE}"/>',
            f'<text x="{label_width + w + 4:.1f}" y="{y + 11}" '
            f'style="{FONT}">{_e(fmt(value))}</text>',
            f'<text x="{width}" y="{y + 11}" text-anchor="end" '
            f'style="{FONT}">{_e(weiter)}</text>']
    return _frame("".join(parts), width, int(height), title)


def year_comparison(months, title, fmt=str) -> str:
    """Saeulen Ist gegen Vorjahr, darunter die Abweichung als eigenes Panel.

    `monate` ist eine Liste aus (Label, Ist, Vorjahr). Die Abweichung ist die
    Aussage und wird nicht dem Auge des Betrachters ueberlassen.
    """
    months = [m for m in months if m[1] is not None]
    if not months:
        return ""
    width, height_top, height_bottom, header = 560, 120, 54, 26
    # Der Abstand zwischen Saeulen- und Abweichungspanel muss die
    # Beschriftung der positiven Balken tragen: bis 07.09.2026 lief die
    # Panel-Ueberschrift durch die Balken hindurch.
    luecke = 34
    height = header + height_top + luecke + height_bottom + 14
    n = len(months)
    schritt = width / n
    saeule = min(20.0, schritt * 0.34)
    mx = max(max(m[1] or 0, m[2] or 0) for m in months) or 1
    y0 = header + height_top

    parts = [f'<text x="0" y="10" style="{LABEL}">Umsatz je Monat</text>',
             f'<rect x="150" y="4" width="8" height="8" fill="{INK}"/>'
             f'<text x="162" y="11" style="{FONT}">dieses Jahr</text>',
             f'<rect x="228" y="4" width="8" height="8" fill="{LIGHT}"/>'
             f'<text x="240" y="11" style="{FONT}">Vorjahr</text>']
    for i, (label, ist, vor) in enumerate(months):
        x = i * schritt + schritt / 2
        hv = height_top * ((vor or 0) / mx)
        hi = height_top * ((ist or 0) / mx)
        parts += [
            f'<rect x="{x - saeule:.1f}" y="{y0 - hv:.1f}" width="{saeule:.1f}" '
            f'height="{hv:.1f}" fill="{LIGHT}"/>',
            f'<rect x="{x:.1f}" y="{y0 - hi:.1f}" width="{saeule:.1f}" '
            f'height="{hi:.1f}" fill="{INK}"/>',
            f'<text x="{x:.1f}" y="{y0 + 11}" text-anchor="middle" '
            f'style="{FONT};fill:{GREY}">{_e(label)}</text>']
    parts.append(f'<line x1="0" y1="{y0}" x2="{width}" y2="{y0}" '
                 f'stroke="{INK}" stroke-width="0.8"/>')

    # Abweichungspanel
    parts.append(f'<text x="0" y="{y0 + 26}" style="{LABEL}">'
                 "Abweichung gegen das Vorjahr</text>")
    y1 = y0 + luecke + height_bottom / 2
    abw = [((m[1] - m[2]) / m[2] if m[2] else None) for m in months]
    mxa = max((abs(a) for a in abw if a is not None), default=0) or 1
    for i, a in enumerate(abw):
        if a is None:
            continue
        x = i * schritt + schritt / 2
        h = (height_bottom / 2 - 10) * (abs(a) / mxa)
        oben = y1 - h if a >= 0 else y1
        # Die Beschriftung steht immer am aeusseren Ende des Balkens, damit
        # sie bei positiven wie negativen Werten gleich weit von der
        # Nulllinie weg sitzt und nie in den Balken laeuft.
        y_text = (y1 - h - 3) if a >= 0 else (y1 + h + 8)
        parts += [
            f'<rect x="{x - saeule / 2:.1f}" y="{oben:.1f}" '
            f'width="{saeule:.1f}" height="{h:.1f}" '
            f'fill="{BLUE if a >= 0 else ACCENT}"/>',
            f'<text x="{x:.1f}" y="{y_text:.1f}" '
            f'text-anchor="middle" style="{FONT};font-size:7px">'
            f'{("+" if a >= 0 else "")}{a * 100:.0f}%</text>']
    parts.append(f'<line x1="0" y1="{y1}" x2="{width}" y2="{y1}" '
                 f'stroke="{RULE}" stroke-width="0.8"/>')
    return _frame("".join(parts), width, int(height), title)
