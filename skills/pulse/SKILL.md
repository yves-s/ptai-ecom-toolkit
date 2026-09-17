---
name: pulse
description: Wochen-Puls für den Kunden-Workspace erzeugen, ein kompaktes Markdown mit den konfigurierten Puls-KPIs und Vorwochen-Delta, kommentiert wird nur Auffälliges. Nutzen bei /ptai-ecom:pulse oder wenn der Nutzer einen wöchentlichen Kurzstatus, ein Wochen-Update oder einen Puls für Shop-, Traffic- oder SEO-Zahlen will. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pulse: Wochen-Puls

Der schnelle Gegenpart zum Monats-Report: eine KPI-Tabelle für die letzte volle
Woche gegen die Vorwoche, kommentiert wird nur, was auffällt. Kein
Executive-Summary-Absatz, keine Kapitel, kein PDF, nur Tabelle plus wenige
Sätze. Zieht dafür ausschließlich die Quellen, die die konfigurierten
`pulse_kpis` tatsächlich brauchen, und schreibt eigene `-pulse.json`-Snapshots,
die nie die Monats-Vergleichsbasis berühren.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` (legt der Skill `setup` an). Fehlt sie komplett:
  nichts raten, nichts anlegen, in zwei Sätzen sagen was fehlt und anbieten,
  das Setup jetzt zu starten (Skill `setup`). Sagt die Person nein, hier
  aufhören. Dasselbe gilt, wenn die Config zwar da ist, aber keine einzige
  konfigurierte KPI eine liefernde Quelle hat: kein Puls aus lauter Lücken.
- `pulse_kpis` in der Config ist optional. Fehlt der Schlüssel, gilt der
  Default-Satz aus der Spec: `sessions`, `revenue`, `orders`,
  `conversion_rate`, `aov`, `gsc_clicks`, `gsc_impressions`.
- Für jede konfigurierte KPI muss die zugehörige Quelle unter `sources` auf
  `true` stehen (Tabelle unten). Sind für keine einzige konfigurierte KPI die
  Quellen aktiv: kein Puls, auf `/ptai-ecom:setup` verweisen.
- `.env` mit den Secrets, die die jeweils aufgerufenen Pull-Skills brauchen
  (`PTAI_GOOGLE_CREDENTIALS` für GA4/GSC). Details stehen dort, hier nicht
  wiederholt.

Der Lauf liest nur. In Kundensysteme wird nie geschrieben.

## Ablauf

### 1. Config lesen, benötigte Quellen ableiten

`pulse_kpis` gegen diese Tabelle abgleichen; jede KPI kommt aus genau der/den
dort genannten Quelle(n). Ein unbekannter Schlüssel in `pulse_kpis` wird mit
einer Warnung übersprungen, der Rest läuft normal.

| KPI-Schlüssel | Label | Prim. Quelle (Feld) | Fallback |
|---|---|---|---|
| `sessions` | Sessions | `shopify.json`: `sessions.sessions` | `ga4.json`: `totals.sessions` |
| `revenue` | Umsatz | `shopify.json`: `totals.total_sales` | keine |
| `orders` | Bestellungen | `shopify.json`: `totals.orders` | keine |
| `conversion_rate` | Conversion Rate | `shopify.json`: `sessions.conversion_rate` | `ga4.json`: `funnel.purchase` / `totals.sessions` |
| `aov` | AOV | `shopify.json`: `totals.average_order_value` | keine |
| `gsc_clicks` | GSC-Klicks | `gsc.json`: `totals.clicks` | keine |
| `gsc_impressions` | GSC-Impressionen | `gsc.json`: `totals.impressions` | keine |

**Conversion-Präzedenz** wie im Monats-Report (`skills/report/SKILL.md`,
Abschnitt "Zahlen-Regeln (hart)"): `sessions` und `conversion_rate` kommen
zuerst aus `shopify.json`. Ist das Feld dort `null`, kommen sie aus
`ga4.json`. Fehlt beides, ist die KPI "nicht berechenbar", keine Ersatzzahl.

Daraus die benötigten Pull-Skills ableiten: `pull-shopify`, wenn eine der
KPIs `sessions`, `revenue`, `orders`, `conversion_rate`, `aov` konfiguriert
ist; `pull-ga4` zusätzlich, wenn `sessions` oder `conversion_rate`
konfiguriert ist (Fallback-Daten müssen bereitstehen, sobald Shopify das Feld
nicht liefert); `pull-gsc`, wenn `gsc_clicks` oder `gsc_impressions`
konfiguriert ist. **`pull-cwv` und `check-geo` laufen im Puls nie:** Core Web
Vitals und GEO sind keine Puls-KPIs, die Spec sieht sie ausdrücklich nicht
dafür vor.

Ist eine benötigte Quelle in `sources` auf `false`: die davon abhängigen
KPI-Zeilen als "nicht verfügbar (Quelle nicht aktiv)" führen, den Pull für
diese Quelle auslassen, der Rest läuft normal.

### 2. Zeitraum bestimmen: aktuelle Woche und Vorwoche

Die letzte vollständig abgeschlossene Kalenderwoche vor dem Ausführungstag,
Montag bis Sonntag (ISO-Woche). Praktisch: den Montag der laufenden,
angebrochenen Woche bestimmen, 7 Tage davor liegt der Montag der gesuchten
Woche, deren Sonntag 6 Tage später. Die Vorwoche zum Vergleich ist die davor
liegende Montag-bis-Sonntag-Spanne (7 Tage früher).

Beispiel: Ausführung am Montag 2026-08-10 → Puls-Woche Montag 2026-08-03 bis
Sonntag 2026-08-09 (ISO-Woche 2026-W32), Vergleichswoche Montag 2026-07-27
bis Sonntag 2026-08-02 (2026-W31). Die ISO-Wochennummer für den Dateinamen
lässt sich am Sonntag der Puls-Woche ablesen (macOS:
`date -j -f %Y-%m-%d <sonntag> +%G-W%V`, Linux: `date -d <sonntag> +%G-W%V`).

Anders als beim Monats-Report gibt es für den Puls keine gespeicherte
Vergleichsbasis aus einem Vorlauf: **jeder Puls-Lauf zieht Vorwoche und
aktuelle Woche gemeinsam live.** Es gilt nicht die "Snapshot schlägt Live"-
Regel des Monats-Reports, die ist an die Vormonats-Snapshot-Suche gebunden
und gilt nur dort.

### 3. Pull-Skills aufrufen

Nur die in Schritt 1 ermittelten Quellen, jeweils mit `--pulse` und der
Vorwoche als `--compare-start`/`--compare-end` in einem Aufruf, sodass der
`comparison`-Block direkt in derselben `-pulse.json` landet (gleiches Schema
wie beim Monats-Erstlauf, nur mit Wochen- statt Monatsgrenzen). Zielordner ist
der heutige Daten-Ordner; ein Re-Run am selben Tag überschreibt ihn idempotent.

**GA4** (nur wenn `sessions` oder `conversion_rate` konfiguriert ist):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-ga4/scripts/ga4_pull.py" \
  --property <ga4_property_id> \
  --creds "$PTAI_GOOGLE_CREDENTIALS" \
  --start 2026-08-03 --end 2026-08-09 \
  --compare-start 2026-07-27 --compare-end 2026-08-02 \
  --out "reporting/data/$(date +%F)" \
  --pulse
```

**GSC** (nur wenn `gsc_clicks` oder `gsc_impressions` konfiguriert ist;
`--inspect-urls` braucht der Puls nicht, die Index-Stichprobe ist keine
Puls-KPI):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-gsc/scripts/gsc_pull.py" \
  --site <gsc_site> \
  --creds "$PTAI_GOOGLE_CREDENTIALS" \
  --start 2026-08-03 --end 2026-08-09 \
  --compare-start 2026-07-27 --compare-end 2026-08-02 \
  --out "reporting/data/$(date +%F)" \
  --pulse
```

**Shopify** (kein Script, Ablauf aus `pull-shopify` mit Wochenfenstern statt
Monatsfenstern): die "Umsatz-Totals"-Query (`SHOW total_sales, net_sales,
orders, average_order_value SINCE <Montag> UNTIL <Sonntag>`) liefert Umsatz,
Bestellungen und AOV; ist `sessions` oder `conversion_rate` konfiguriert,
zusätzlich die "Sessions und Conversion Rate"-Query. Jede Query zweimal
ausführen, einmal mit der aktuellen Woche, einmal mit der Vorwoche, das
zweite Ergebnis in einen `comparison`-Block (gleiche Struktur, eigener
`period`). Die Zeitreihen- (`TIMESERIES day`) und Top-Produkte-/Bestands-Pulls
braucht der Puls nicht: `by_month`, `top_products` und `top_collections`
bleiben in `shopify-pulse.json` `null` mit `"notes"`-Eintrag "im Puls nicht
gezogen". Schreibt `reporting/data/<heute>/shopify-pulse.json`.

### 4. KPI-Werte, Deltas und Auffälligkeiten bestimmen

Für jede konfigurierte KPI den Wert nach der Tabelle in Schritt 1 aus der
frisch gezogenen `-pulse.json` lesen (Conversion-Präzedenz anwenden, wo
zutreffend). Delta ist überall die relative Veränderung zum Vorwochenwert in
Prozent, auch bei der Conversion Rate (die relative Veränderung der Rate,
nicht Prozentpunkte), damit die Schwelle unten einheitlich gilt.

**Für Nullwerte, fehlende Felder und die genauen Fehler-Shapes je
Snapshot-Datei gilt exakt das, was `skills/report/SKILL.md` im Abschnitt
"Fehler-Shapes je Quelle" beschreibt, hier nicht wiederholt, nur angewendet.**

Zahlen-Hygiene wie dort: jede Zahl stammt aus einem konkreten Snapshot-Feld,
nichts geschätzt, nichts erfunden. Deutsche Formate (`1.240 €`, `1,5 %`,
Deltas mit Vorzeichen `+8,2 %`).

**Formeln und Schwellen kommen ebenfalls aus dem Kennzahlen-Katalog**
(`${CLAUDE_PLUGIN_ROOT}/reference/metrics.md`), der Puls rechnet keine eigene
Logik und setzt keine eigenen Grenzwerte; auch die 20-Prozent-Schwelle unten
steht dort als plugin-weite Auffälligkeits-Schwelle.

**Auffällig** ist eine KPI, wenn eine der beiden Bedingungen zutrifft:

- das relative Delta ist betragsmäßig `>= 20 %`, oder
- der Vorwochenwert oder der aktuelle Wert liegt auf der Null-Linie (0), denn
  dann gibt es kein sinnvolles Prozent-Delta und genau das ist die
  Auffälligkeit.

Nur zu diesen Zeilen kommt ein Kommentar (ein bis zwei Sätze, aus der Zahl
begründet); alle anderen KPIs stehen kommentarlos in der Tabelle. Gibt es
keine einzige auffällige KPI, ein Satz "keine Auffälligkeiten diese Woche"
statt eines leeren Abschnitts.

Kann eine KPI mangels Nenner nicht berechnet werden (z. B. AOV ohne
Bestellung in der Vorwoche), steht "nicht berechenbar" statt eines Deltas,
keine Division durch 0.

### 5. GSC-Nachlauf kennzeichnen

GSC-Daten laufen 2 bis 3 Tage nach. Liegen zwischen dem Sonntag der
Puls-Woche und dem Ausführungstag weniger als 4 Tage (gleiche Schwelle wie im
Monats-Report), tragen die GSC-KPIs im Puls einen Hinweis: die Zahlen dieser
Woche können noch nachträglich steigen, kein Fehler.

### 6. Markdown schreiben

`reporting/reports/YYYY-Www-pulse.md` (Beispiel `2026-W32-pulse.md`, ISO-Woche
der Puls-Woche): H1 `<Brand> · Wochen-Puls KW <Nr>/<Jahr>`, eine Zeile mit dem
Zeitraum, die KPI-Tabelle, die Auffälligkeiten-Sätze, bei Bedarf der
GSC-Nachlauf-Hinweis, dann eine Trennlinie `---` und als letzte Zeile wörtlich
`Erstellt mit ptai-ecom von [Path to AI](https://path-to-ai.com).` Nie
umformulieren, nie kürzen, nichts dahinter.

### 7. Zusammenfassung an den Nutzer

Die auffälligen KPIs in Kurzform, welche Quellen nicht verfügbar waren (falls
welche), Pfad zur `.md`.

## Ausgabe-Format

Konkretes Beispiel für `reporting/reports/2026-W32-pulse.md` (illustrative
Zahlen, kein echter Kundenstand):

```markdown
# Beispielshop · Wochen-Puls KW 32/2026

Zeitraum: 03.08. bis 09.08.2026 gegenüber Vorwoche 27.07. bis 02.08.2026.

| KPI | KW 32 | KW 31 | Delta |
|---|---|---|---|
| Sessions¹ | 340 | 298 | +14,1 % |
| Umsatz | 210 € | 0 € | Null-Linie |
| Bestellungen | 1 | 0 | Null-Linie |
| Conversion Rate¹ | 0,3 % | 0,0 % | Null-Linie |
| AOV | 210,00 € | keine | nicht berechenbar |
| GSC-Klicks | 61 | 54 | +13,0 % |
| GSC-Impressionen | 3.410 | 2.750 | +24,0 % |

¹ aus ga4.json (Fallback): shopify.json trägt unter sessions den Wert null.

**Auffälligkeiten:**

- Umsatz und Bestellungen sprangen von 0 auf 210 €/1 Bestellung: die erste
  Conversion seit der Vorwoche, bei diesem Volumen keine Trendaussage.
- GSC-Impressionen +24,0 % (2.750 auf 3.410), die Klicks zogen mit +13,0 %
  deutlich schwächer mit, ein Blick auf die Snippets der gewinnenden Seiten
  lohnt sich.

GSC-Zahlen für diese Woche können noch nachträglich steigen (Meldeverzug 2
bis 3 Tage).

---

Erstellt mit ptai-ecom von [Path to AI](https://path-to-ai.com).
```

## Fehlerbilder

- **Config fehlt komplett:** nicht raten, auf `/ptai-ecom:setup` verweisen,
  aufhören.
- **`pulse_kpis` fehlt in der Config:** kein Fehler, der Default-Satz aus der
  Spec greift.
- **Unbekannter Schlüssel in `pulse_kpis`:** mit Warnung überspringen, die
  übrigen KPIs laufen normal.
- **Quelle einer konfigurierten KPI steht auf `sources: false`:** die
  betroffenen KPI-Zeilen "nicht verfügbar (Quelle nicht aktiv)", der Pull für
  diese Quelle entfällt, der Rest läuft.
- **Einzelner Pull scheitert:** die davon abhängigen KPI-Zeilen "nicht
  verfügbar (Grund)"; die genauen Shapes (`null`-Felder, `{"error": ...}`)
  stehen in den Fehlerbildern der jeweiligen Pull-Skill und in
  `skills/report/SKILL.md` unter "Fehler-Shapes je Quelle", hier nicht noch
  einmal aufgeführt.
- **Conversion-Präzedenz erschöpft** (Shopify- und GA4-Feld beide `null` bzw.
  nicht verfügbar): "nicht berechenbar" statt Zahl, kein Delta.
- **Alle benötigten Quellen scheitern:** kein Puls. Abbrechen, die Gründe je
  Quelle nennen, auf `/ptai-ecom:setup` verweisen, statt eine leere Tabelle zu
  schreiben.
- **GSC-Meldeverzug:** kein Fehler, siehe Ablauf Schritt 5, nur eine
  Kennzeichnung im Puls.
