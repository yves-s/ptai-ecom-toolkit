---
name: pull-cwv
description: Core-Web-Vitals-Daten (Feld- plus Lab-Werte, plus CrUX-Wochenhistorie) über die PageSpeed-Insights-API je Seitentyp für den Kunden-Report oder den Wochen-Puls ziehen und als Snapshot ablegen. Nutzen, wenn ein Monats-Report oder Puls CWV-Zahlen braucht, oder wenn der Nutzer explizit Core-Web-Vitals- bzw. PageSpeed-Daten für die Kunden-Site abrufen will. Liest reporting/config.json und .env im Kunden-Workspace.
---

# pull-cwv: Core-Web-Vitals-Snapshot ziehen

Zieht per PageSpeed Insights API je Seitentyp (aus `config.page_types()`,
ersatzweise `cwv_urls`) die CrUX-Feldwerte (LCP, INP, CLS) plus den
Lighthouse-Lab-Performance-Score, dazu die CrUX-Wochenhistorie je Origin, und
legt alles als Snapshot im Kunden-Workspace ab. Wird vom Report- und
Puls-Lauf aufgerufen, funktioniert aber auch solo.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `page_types` (URL je Seitentyp, gelesen über
  `config.page_types()`; fehlt `page_types` in der Config ganz, ersatzweise
  `cwv_urls`, dieselbe Liste, die auch `pull-gsc` als Index-Stichprobe nutzt,
  keine zweite Liste pflegen) und `sources.cwv` nicht `false`
- `PTAI_PSI_KEY` in der `.env` des Workspace oder zentral in
  `~/.config/ptai-ecom/.env` (PageSpeed-Insights-API-Key, gilt auch für die
  CrUX-History-API)
- `curl` und `jq` auf dem Rechner installiert (dokumentierte Voraussetzung des
  Plugins)

Fehlt eins davon oder steht `sources.cwv` auf `false`: CWV als "nicht verfügbar
(Grund)" melden und aufhören. Nie den Gesamtlauf (Report/Puls) daran scheitern
lassen.

## Ablauf

1. `reporting/config.json` lesen. Seitentypen bevorzugt über
   `config.page_types()`:

   ```bash
   python3 -c "
   import json, sys
   sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
   from audit import config
   cfg = json.load(open('reporting/config.json'))
   print(json.dumps(config.page_types(cfg), ensure_ascii=False))
   "
   ```

   Liefert immer die sechs Schlüssel `start, collection, product, cart,
   search, blog`; ein nicht konfigurierter Typ liefert `null`, der Schlüssel
   verschwindet nie. Fehlt `page_types` in der Config ganz, ersatzweise die
   alte Liste `cwv_urls` verwenden; jede URL daraus bekommt beim Script
   automatisch den Platzhalter-Seitentyp `unnamed`. Den Key findet das Skript
   selbst.

2. Kein Zeitraum nötig: CWV ist eine punktuelle Momentaufnahme, kein
   Zeitraum-Pull wie bei GA4 oder GSC.

3. **Nur Seitentypen mit URL werden zu einem Argument.** Aus jedem Paar mit
   einer URL (`null` ausgeschlossen) wird `<page_type>=<url>`. Script
   aufrufen. **Zielordner ist der Daten-Ordner des laufenden Audits oder
   Reports**, also `reporting/data/<run-id>` als erstes Argument; ohne Lauf-ID
   gilt der heutige Daten-Ordner wie im Beispiel (Abschnitt Snapshot-Schema):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/pull-cwv/scripts/psi_pull.sh" \
     "reporting/data/$(date +%F)" - <page_type>=<url> [<page_type>=<url> ...]
   ```

   Ein Seitentyp ohne URL (`null`) wird nie zu einem Argument, verschwindet
   dabei aber auch nicht still: er erscheint als "nicht konfiguriert:
   <Seitentyp>" in der Meldung an den Nutzer (Schritt 4).

4. Kernzahlen an den Nutzer melden: Performance-Score je Seitentyp, LCP/INP/
   CLS aus den Feldwerten (falls vorhanden), Auffälligkeiten (z. B. ein
   Seitentyp im POOR-Bereich), die CrUX-Wochenhistorie je Origin (falls
   vorhanden, sonst der Grund aus dem `error`-Feld). Jeder nicht
   konfigurierte Seitentyp aus Schritt 3 wird explizit gemeldet, nie
   stillschweigend ausgelassen. Fehlt die Feld-Datenbasis für eine URL, das
   als "keine CrUX-Daten (zu wenig Traffic)" einordnen, nicht als Fehler.

## Snapshot-Schema

**Der Zielordner kommt vom Aufrufer.** Solo ist `reporting/data/<heute>` der
sinnvolle Vorgabewert, und `report` und `pulse` legen ihre Snapshots dort ab,
solange sie ohne Lauf-ID laufen (Spec Abschnitt 14, Umstellung in Stufe 3).
**Läuft der Pull dagegen in einem Audit oder Report mit Lauf-ID, ist der
Zielordner `reporting/data/<run-id>`**, also Datum plus Kadenz
(`2026-10-01-audit`, `2026-11-01-month`), und das erste Argument des Scripts
(`<out-dir>`) zeigt dorthin. Der Orchestrator gibt den Ordner vor; wer den Pull
während eines Laufs von Hand startet, muss dieselbe Lauf-ID verwenden. Ein
Snapshot im falschen Ordner ist für die Analyse nicht vorhanden, und sie meldet
keinen Fehler, sondern rechnet ohne ihn weiter.

Das Script schreibt `<out-dir>/cwv.json`:

```json
{
  "fetched_at": "2026-08-10T12:00:00Z",
  "strategy": "mobile",
  "pages": [
    {
      "page_type": "start",
      "url": "https://beispielshop.de/",
      "field_data": {
        "lcp_ms": 2100, "lcp_category": "AVERAGE",
        "inp_ms": 180, "inp_category": "FAST",
        "cls": 0.08, "cls_category": "FAST"
      },
      "lab": { "performance_score": 0.82, "lcp_ms": 2050.3, "cls": 0.07 }
    },
    { "page_type": "product", "url": "https://beispielshop.de/products/BELIEBIG", "error": "HTTP 403: ..." }
  ],
  "historie": [
    {
      "origin": "https://beispielshop.de",
      "wochen": [
        { "start": "2026-03-02", "ende": "2026-03-29", "lcp_ms": 2050, "inp_ms": 175, "cls": 0.07 }
      ]
    },
    { "origin": "https://blog.beispielshop.de", "error": "keine CrUX-Historie (HTTP 404: chrome ux report data not found)" }
  ]
}
```

CWV ist punktuell: kein `period`-Block, kein `comparison`. Der Report
vergleicht gegen den Vormonats-Snapshot (jüngster `reporting/data/`-Ordner mit
`cwv.json`). Die Wochenhistorie in `historie` ersetzt das nicht: sie
beschreibt rund 25 Wochen bis heute, keinen fixen Vergleichszeitraum wie GA4
oder GSC.

`page_type` kommt aus dem Aufruf-Argument (`<page_type>=<url>`); ein Argument
ohne `=` bekommt den Platzhalter `unnamed`, damit bestehende Aufrufe ohne
Seitentyp-Zuordnung unverändert weiterlaufen. `field_data` ist `null`, wenn
CrUX für die URL keine Feld-Datenbasis hat (bei kleinen Sites normal, kein
Fehler); `lab` ist davon unabhängig immer vorhanden, solange der Call selbst
erfolgreich war. Scheitert der Call für eine URL (HTTP-Fehler, Timeout,
ungültige Antwort), steht statt `field_data`/`lab` ein `{"page_type", "url",
"error"}`-Eintrag in `pages`; die anderen Einträge bleiben davon unberührt.

`historie` ist ein eigenes Array, ein Eintrag je eindeutigem Origin aus den
übergebenen URLs, nicht je Seitentyp: mehrere Seitentypen auf demselben Shop
teilen sich einen Origin und damit einen Eintrag. Jeder Eintrag trägt
entweder `wochen` (rund 25 aufsteigend sortierte Wochenwerte für LCP, INP und
CLS als p75-Perzentile) oder statt `wochen` ein `error`-Feld, wenn der Origin
zu wenig CrUX-Traffic für die Historie hat, dieselbe Ursache wie ein
`field_data: null` oben, nur für die Zeitreihe statt den Momentwert.

## Setup-Check

`--check` testet nur Auth plus einen schnellen Call gegen `https://example.com/`
(nur die Performance-Kategorie), eine OK-/Fehlerzeile, Exit 0/1, gedacht für
den Setup-Wizard:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/pull-cwv/scripts/psi_pull.sh" --check -
```

## Fehlerbilder

- `Fehler: 'jq' ist nicht installiert` bzw. `'curl' ist nicht installiert`: auf
  dem Rechner nachinstallieren (`brew install jq`), dann erneut.
- HTTP 400/403 vom PSI-Endpunkt: meist ein ungültiger oder gesperrter API-Key.
  In der Google Cloud Console prüfen, ob die PageSpeed-Insights-API für den Key
  aktiviert ist.
- `error`-Eintrag statt `field_data`/`lab` bei einzelnen URLs: nicht fatal, die
  übrigen URLs im Snapshot bleiben vollständig.
- `field_data: null`: kein Fehler, sondern zu wenig CrUX-Traffic für die URL
  (typisch bei kleinen Sites). Der Report weist das als "keine Feld-Daten" aus,
  nutzt aber den Lab-Score weiter.
- `error`-Eintrag statt `wochen` in `historie`: meist zu wenig CrUX-Traffic für
  den Origin (HTTP 404 der CrUX-History-API, Meldung etwa "chrome ux report
  data not found"), kein technischer Fehler. Die übrigen Origins und alle
  Einträge in `pages` bleiben davon unberührt.
- Ein Seitentyp aus `config.page_types()` ganz ohne URL: kein Argument für
  ihn, aber immer eine "nicht konfiguriert: <Seitentyp>"-Meldung an den
  Nutzer (Ablauf Schritt 3/4), nie ein stilles Weglassen.
