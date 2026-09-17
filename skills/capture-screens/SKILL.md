---
name: capture-screens
description: Screenshots aller Seitentypen (Desktop und Mobil) plus ein manuell durchlaufener Kaufprozess bis zur Zahlungsauswahl für den Audit-Lauf aufnehmen und in runs/<run-id>/screens.json indexieren. Nutzen, wenn der Audit-Orchestrator (/ptai-ecom:audit) Phase 1 durchläuft, oder wenn der Nutzer explizit Screenshots vom Kunden-Shop aufnehmen will. Der einzige Pull, der nicht wiederholbar ist, weil der Vorher-Zustand ohne Bild weg ist, sobald der Kunde sein Theme ändert. Liest reporting/config.json im Kunden-Workspace.
---

# capture-screens: Screenshots je Seitentyp und der Kaufprozess

Nimmt für jeden konfigurierten Seitentyp zwei Screenshots auf (Desktop und
Mobil) und führt danach von Hand durch den Kaufprozess bis zur
Zahlungsauswahl. Beides ist der visuelle Vorher-Zustand des Shops, Spec
Abschnitt 7. Anders als jeder andere Pull dieses Plugins ist er einmalig: ein
Theme-Wechsel beim Kunden löscht den Vorher-Zustand ersatzlos, keine der
anderen Quellen (Shopify, GA4, GSC, CWV) lässt sich das nachträglich ziehen.
Deshalb hat diese Skill Vorrang vor allen anderen Pulls, sobald das Theme-
Ende des Kunden feststeht.

**Die Bilddateien gehen in den Kundenordner (`drive_path`), nie nach
`reporting/`.** Dieser Ordner wird im Kunden-Repo committet, und
Shop-Screenshots sind kein Code-Artefakt, das dort hingehört. Nur der Index
`screens.json` liegt im Workspace, die Bilder selbst liegen ausschließlich im
Kundenordner.

## Voraussetzungen

Im Kunden-Workspace (aktuelles Arbeitsverzeichnis):

- `reporting/config.json` mit `account_slug`, `drive_path` und optional
  `page_types` (fehlende Typen sind erlaubt, siehe unten)
- Ein headless Browser für die automatisierten Aufnahmen: bevorzugt die
  Headless Shell von Playwright, Chrome oder Chromium gehen auch
- `jq` installiert (baut die JSON-Ausgabe von `shoot.sh`)
- Schreibzugriff auf den Kundenordner aus `drive_path`

Fehlt `account_slug` oder `drive_path`, oder ist `drive_path` relativ, verweigert
bereits `scripts/audit/config.py: validate()` den Lauf, bevor diese Skill
überhaupt anfängt: ohne Ziel würden die Bilder sonst im Repo landen, und genau
das verletzt die PII-Regel aus Spec Abschnitt 13.

## Ablage

- **Bilder:** `<drive_path>/material/<datum>-audit-screenshots/`. `drive_path`
  aus `config.json` ist der absolute Pfad zum Kundenordner (Beispiel:
  `/pfad/zum/kundenordner/beispielshop`), meist
  `<PTAI_ACCOUNTS_ROOT>/<account_slug>`. `<datum>` ist das Tagesdatum des
  Laufs, `YYYY-MM-DD`.
- **Index:** `reporting/runs/<run-id>/screens.json`. Die `run-id` kommt
  vom Orchestrator, wenn diese Skill Teil eines Audit- oder Report-Laufs ist
  (`skills/audit/SKILL.md`); läuft sie solo, wird sie einmalig selbst
  bestimmt (Ablauf Schritt 1). **Die Analysen lesen Screenshots
  ausschließlich über diesen Index, nie über ein Directory-Listing.** Ein
  Bild ohne Eintrag existiert für sie nicht.

## Ablauf

1. **Lauf-ID bestimmen**, falls nicht vom Orchestrator übergeben:

   ```bash
   python3 -c "
   import sys
   sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
   from audit import run
   from datetime import date
   print(run.run_id(date.today(), 'audit'))
   "
   ```

   Läuft diese Skill innerhalb eines bereits laufenden Audits oder Reports,
   dessen Lauf-ID übernehmen, nie neu berechnen: sonst landen Bilder
   desselben Laufs an einem Mitternachtsübergang in zwei verschiedenen
   `runs/`-Ordnern.

2. **Zielordner bestimmen:** `drive_path` aus `reporting/config.json` lesen,
   `material/$(date +%F)-audit-screenshots/` anhängen, Ordner anlegen
   (`mkdir -p`). `drive_path` ist absolut, eine Wurzel davor gibt es nicht.

3. **Seitentypen lesen.** Immer alle sechs Standardtypen, auch ohne
   Override in der Config:

   ```bash
   python3 -c "
   import json, sys
   sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
   from audit import config
   cfg = json.load(open('reporting/config.json'))
   print(json.dumps(config.page_types(cfg), ensure_ascii=False))
   "
   ```

   Das Ergebnis hat immer die Schlüssel `start, collection, product,
   cart, search, blog`. Ein Typ ohne Override liefert `null`.

4. **Je Typ mit einer URL** (`null` ausgeschlossen, siehe Schritt 5):

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/skills/capture-screens/scripts/shoot.sh" \
     --url "<url>" --name "<page-type>" --target "<Zielordner aus Schritt 2>"
   ```

   Die Zeile `IMAGES_JSON: [...]` aus der Ausgabe trägt die fertigen
   Einträge (Seitentyp, Gerät, Aufnahmezeit, Quell-URL, absoluter Pfad) für
   `screens.json`, unverändert übernehmen, nie Pfad oder Zeitstempel selbst
   neu tippen. Der Exit-Code ist die Anzahl fehlgeschlagener Aufnahmen (0, 1
   oder 2): bei über 0 die stderr-Zeilen in die Meldung an den Nutzer
   aufnehmen, aber mit den übrigen Seitentypen weitermachen. Ein
   fehlgeschlagener Typ bekommt keinen Eintrag in `screens.json`, dafür aber
   eine Zeile in der Meldung an den Nutzer ("Aufnahme fehlgeschlagen:
   <typ>, Grund: ..."), damit ein fehlendes Bild sichtbar bleibt statt in
   der Ausgabe unterzugehen.

5. **Ein Typ ohne URL (`null`) wird nie übersprungen, sondern gemeldet.**
   Kein Aufruf von `shoot.sh`, aber eine Zeile "nicht konfiguriert:
   <Seitentyp>" in der Meldung an den Nutzer und im `not_configured`-Feld
   von `screens.json` (siehe Schema unten). Läuft diese Skill innerhalb des
   Audit-Orchestrators, landet dieselbe Information in
   `runs/<run-id>/source-status.md`; diese Skill selbst schreibt diese Datei
   nicht, sie meldet nur.

6. **`screens.json` schreiben**, alle gesammelten Bild-Einträge plus die
   Liste nicht konfigurierter Typen, siehe Schema unten. Existiert die Datei
   schon (ein vorheriger Teillauf), Einträge ergänzen statt überschreiben:
   ein zweiter Anlauf nach einem Abbruch darf bereits fotografierte Typen
   nicht aus dem Index werfen.

7. **Kaufprozess von Hand durchlaufen**, siehe unten.

8. **Kernergebnis an den Nutzer melden:** wie viele Typen fotografiert
   (Desktop plus Mobil je Typ), welche nicht konfiguriert waren, welche
   fehlgeschlagen sind, ob der Kaufprozess durchlaufen wurde, wohin die
   Bilder gegangen sind (voller Pfad).

## Der Kaufprozess

Läuft wie der Rest dieser Skill automatisiert, mit den Browser-Werkzeugen
(nicht mit `shoot.sh`, das ist nur für die Seitentyp-Aufnahmen). Ein Audit,
der auf einen Menschen wartet, ist kein Werkzeug.

**Vor jedem Schritt die Seite lesen, dann handeln.** Nie blind auf eine
Koordinate klicken: erst den Seiteninhalt abfragen (Accessibility-Baum oder
Text), prüfen, dass die erwartete Stufe erreicht ist, dann den nächsten
Schritt auslösen. Das ist der Ersatz für das Auge, das früher danebensaß, und
der einzige Grund, warum dieser Ablauf überhaupt manuell war.

1. Ein reguläres Produkt **mit Bestand** öffnen, nie das Beispielprodukt aus
   `page_types.product`. Bestand aus `shopify.json > availability` oder aus
   der Produktseite selbst.
2. In den Warenkorb legen, Warenkorb-Ansicht (Drawer oder Seite)
   fotografieren: `checkout-warenkorb.png`.
3. Zur Kasse gehen, Kontakt- und Versandadresse mit Platzhalter-Daten
   ausfüllen. Den Schritt Versandart-Auswahl fotografieren:
   `checkout-versand.png`.
4. Bis zur Zahlungsart-Auswahl weitergehen, dort **anhalten** und
   fotografieren: `checkout-zahlung.png`. Sichtbar sollen die angebotenen
   Zahlungsarten sein, keine ausgefüllten Zahlungsfelder.
5. Die Kasse verlassen, nichts abschicken.

### Was dabei nie passiert

Diese vier Regeln gelten unabhängig davon, wer oder was den Ablauf steuert,
und sie sind der Grund, warum die Automatisierung vertretbar ist:

- **Keine Zahlungsart wählen, nichts absenden, keine Zahlungsdaten eingeben.**
  Auch dann nicht, wenn eine Zahlungsart wie "Kauf auf Rechnung" ohne
  Kartendaten auskommt. Der Lauf endet an der Auswahl, nicht dahinter.
- **Keine echten personenbezogenen Daten.** Weder die des Nutzers noch die
  eines Kunden. Platzhalter, erkennbar als solche.
- **Kein Login.** Der Kaufweg wird als Gast durchlaufen. Verlangt der Shop
  zwingend ein Konto, bricht der Schritt ab und meldet das als Befund, statt
  ein Konto anzulegen.
- **Kein zweiter Versuch nach einem Fehlklick.** Führt ein Schritt nicht
  dorthin, wo er hinsollte, wird abgebrochen und der erreichte Stand
  protokolliert. Ein Skript, das sich durch einen unbekannten Checkout
  probiert, ist genau das Risiko, das diesen Ablauf früher manuell gemacht
  hat.

Ein so verlassener Warenkorb hinterlässt beim Shop eine abgebrochene Session,
wie sie jeder Besucher auch erzeugt. Er taucht damit in
`shopify.json > abandoned_checkouts` auf; bei einem Shop mit sehr wenigen
Bestellungen ist das eine Session von wenigen und gehört als Anmerkung in den
Lauf, damit niemand sie später für Kundenverhalten hält.

### Abschalten

`checkout_capture` in `reporting/config.json` entscheidet, ob dieser Teil
läuft. **Nie im Lauf nachfragen:** die Aufnahme legt einen echten
Testwarenkorb im Produktivshop an, und ob das in Ordnung ist, gehört ins
Setup, einmal je Kunde. Fehlt das Feld, läuft der Kaufweg nicht und die Lücke
wird im Report ausgewiesen.
Die Seitentyp-Aufnahmen laufen trotzdem. Sinnvoll bei einem Shop, dessen
Kasse ein Konto verlangt, und bei jedem Kunden, der einen Testwarenkorb nicht
will. Fehlt das Feld, gilt `true`.

## screens.json-Schema

```json
{
  "run_id": "2026-10-01-audit",
  "created_at": "2026-10-01T09:12:03Z",
  "target_dir": "<drive_path>/material/2026-10-01-audit-screenshots",
  "images": [
    {
      "page_type": "start",
      "device": "desktop",
      "captured_at": "2026-10-01T09:12:01Z",
      "source_url": "https://beispielshop.de/",
      "path": "<drive_path>/material/2026-10-01-audit-screenshots/start-desktop.png"
    },
    {
      "page_type": "start",
      "device": "mobil",
      "captured_at": "2026-10-01T09:12:04Z",
      "source_url": "https://beispielshop.de/",
      "path": "<drive_path>/material/2026-10-01-audit-screenshots/start-mobil.png"
    },
    {
      "page_type": "checkout-zahlung",
      "device": "desktop",
      "captured_at": "2026-10-01T09:24:47Z",
      "source_url": "https://beispielshop.de/checkout/...",
      "path": "<drive_path>/material/2026-10-01-audit-screenshots/checkout-zahlung.png",
      "manual": true
    }
  ],
  "not_configured": ["warenkorb", "suche"]
}
```

`not_configured` trägt jeden Seitentyp, für den `config.page_types()`
`null` geliefert hat. Eine leere Liste heißt: alle sechs Typen waren
konfiguriert, nicht dass die Prüfung ausgefallen ist, das Feld steht immer
da, auch leer.

## Fehlerbilder

- **Kein Browser gefunden:** `shoot.sh` bricht sofort ab (Exit 1, vor der
  ersten Aufnahme). Die Headless Shell installieren
  (`npx playwright install chromium-headless-shell`) oder Chrome bzw.
  Chromium, erneut aufrufen.
- **`jq` fehlt:** dieselbe Behandlung, `shoot.sh` bricht ab, bevor es
  überhaupt eine URL anfasst.
- **Eine einzelne Aufnahme schlägt fehl** (Timeout, 4xx/5xx, Netzwerk):
  `shoot.sh` bricht deswegen nicht ab, die andere Aufnahme desselben Typs
  läuft weiter, der Exit-Code zählt die fehlgeschlagenen Aufnahmen. Diese
  Skill meldet den Typ als fehlgeschlagen (Schritt 4), er bleibt ohne
  Eintrag in `screens.json`, nie mit einem erfundenen Pfad.
- **Die URL ist nicht erreichbar (DNS, Timeout, TLS):** headless Chrome
  beendet sich dabei trotzdem mit Exit 0 und schreibt ein Bild, nur eben von
  Chromes eigener Fehlerseite ("Die Website ist nicht erreichbar"), nicht
  von der Zielseite. Das ist die eine Fehlerart, die weder am Exit-Code noch
  an der Dateigröße auffällt, eine Fehlerseite ist einige Zehn-KB groß wie
  eine echte Seite. `shoot.sh` erkennt sie über eine interne, sprach- und
  versionsstabile Chromium-Markierung im DOM, verwirft das Bild und zählt
  die Aufnahme als fehlgeschlagen. Die Headless Shell von Playwright
  schreibt statt der Fehlerseite ein leeres Bild mit leerem DOM, auch das
  verwirft `shoot.sh`. Eine echte, vom Kunden-Server
  ausgelieferte Fehlseite (eigene 404-Seite des Shops) ist davon nicht
  betroffen und wird normal fotografiert, das ist echter Seiteninhalt, keine
  Chrome-Fehlermeldung.
- **Cookie-Consent-Banner im Bild:** erwartet, kein Fehler. Jede Aufnahme
  läuft mit einem frischen, nicht angemeldeten Chrome-Profil ohne
  gespeicherte Einwilligung, deshalb erscheint der Banner auf jeder
  Aufnahme gleich, nicht nur gelegentlich. Wer das Layout darunter braucht,
  liest es aus der zweiten Aufnahme desselben Laufs falls vorhanden, sonst
  bleibt der Banner Teil des dokumentierten Ist-Zustands.
- **Ein Seitentyp mit `null`-URL:** kein Fehler, kein Aufruf von
  `shoot.sh`, aber immer eine "nicht konfiguriert"-Zeile, nie ein stilles
  Weglassen (Schritt 5).
- **Kaufprozess mitten im Ablauf abgebrochen** (Verbindung weg, falsches
  Element, Kunde meldet sich): keine der bisherigen Kasse-Screenshots
  verwerfen, sie bleiben gültig. Nur den fehlenden Rest in der Meldung an
  den Nutzer als offen kennzeichnen, kein zweiter Versuch ohne Rücksprache:
  ein zweiter Warenkorb mit demselben Produkt ist beim Kunden sichtbar.
