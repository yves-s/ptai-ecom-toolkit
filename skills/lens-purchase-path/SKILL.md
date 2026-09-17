---
name: lens-purchase-path
description: Die Kaufstrecke eines Shops von außen prüfen, also den Weg von der Produktseite über den Warenkorb bis zur Zahlungsauswahl, ohne Zugänge und ohne eine Bestellung auszulösen. Prüft Kaufbutton, Verfügbarkeit, Lieferzeit, Versandkosten vor der Kasse, Gastbestellung, Zahlarten, Schrittzahl und Bedienbarkeit auf dem Handy. Nutzen als Linse L3 in ptai-ecom:audit-light, im großen Audit als Ergänzung zur GA4-gestützten Funnel-Analyse, oder wenn der Nutzer wissen will, woran ein Kauf in einem fremden Shop scheitert. Liefert belegte Befunde mit Deep-Link, keine Vermutungen über Conversion-Zahlen.
---

# lens-purchase-path: der Weg zum Kauf, von außen

Die Kaufstrecke ist der größte Hebel im E-Commerce und die Stelle, an der ein
Audit von außen am meisten sieht. Jeder Punkt hier ist ohne Zugang prüfbar, und
keiner braucht eine ausgelöste Bestellung.

**Der Methodenkern kommt aus `marketing-skills:cro`**, dem Sieben-Punkte-Rahmen:
Nutzenversprechen, Headline, CTA-Hierarchie, visuelle Hierarchie,
Vertrauenssignale, Einwandbehandlung, Reibungspunkte. Was dort nicht passt und
hier nicht gilt: die seitentypischen Frameworks für Homepage, Pricing, Feature
und Blog (ein Shop hat PLP, PDP, Warenkorb und Kasse, keine Pricing-Page) sowie
Test-Ideen und A/B-Vorschläge (von außen weder vorschlagbar noch messbar).

## Was diese Linse nicht kann, und das gehört in den Report

- **Keine Abbruchquoten.** Wo Menschen aussteigen, steht in Analytics, nicht auf
  der Seite. Ein Befund lautet nie "hier springen 60 Prozent ab".
- **Keine ausgelöste Bestellung.** Geprüft wird bis zur Zahlungsauswahl, nie
  darüber hinaus. Bei einem Shop ohne Geschäftsbeziehung wird gar kein
  Testwarenkorb angelegt, dann trägt die Prüfung nur so weit, wie die Seiten
  ohne Warenkorb zeigen.
- **Was erst im Browser entsteht, braucht den Screenshot.** Sticky-Buttons,
  Varianten-Auswahl und Versandrechner sind im HTML oft unsichtbar. Ohne
  Screenshot-Beleg: weglassen oder als Prüfauftrag mit `confidence: "low"`.

## Die Prüfpunkte

### 1. Der Kaufbutton

Auf der Produktseite, in Desktop **und** Mobil.

- Ohne Scrollen erreichbar? Auf dem Handy ist das der häufigste Fund: der Button
  liegt unter Galerie, Varianten und Trust-Leiste.
- Eindeutig als Hauptaktion erkennbar, oder konkurriert er mit gleich lauten
  Buttons ("Merkzettel", "Vergleichen", Chat-Blase)?
- Beschriftung: sagt sie, was passiert ("In den Warenkorb"), oder ist sie vage
  ("Weiter", "Auswählen")?

`crit`, wenn der Kaufbutton auf dem Handy ohne Scrollen nicht sichtbar ist oder
gar nicht als Hauptaktion erkennbar ist. Beleg ist der Screenshot plus die URL.

### 2. Verfügbarkeit und Lieferzeit

- Steht auf der Produktseite, ob der Artikel lieferbar ist?
- Steht dort eine Lieferzeit, und ist sie konkret ("in 1 bis 3 Werktagen") oder
  eine Floskel ("schnelle Lieferung")?
- Bei Varianten: ändert sich die Angabe mit der Auswahl, oder gilt sie pauschal?

Fehlende Lieferzeit ist ein `warn`, fehlende Verfügbarkeitsangabe bei einem Shop
mit erkennbarer Lagerhaltung ein `crit`: der Kunde erfährt erst nach der
Bestellung, dass er wartet.

### 3. Versandkosten vor der Kasse

Der wichtigste Punkt dieser Linse, und der am häufigsten verletzte.

- Stehen die Versandkosten auf der Produktseite oder spätestens im Warenkorb,
  also **bevor** jemand seine Daten eingibt?
- Gibt es eine versandkostenfreie Schwelle, und steht sie dort, wo sie wirkt?
- Ist der Hinweis konkret oder nur ein Link auf eine Versandseite?

`crit`, wenn Versandkosten erst nach Eingabe der Adresse sichtbar werden. Das ist
zugleich rechtlich heikel, gehört aber als Befund hierher und als Prüfauftrag zu
`lens-trust`, nicht als Rechtsurteil.

### 4. Der Warenkorb

- Kommt man nach dem Hinzufügen zurück zum Weiterkaufen, oder landet man in einer
  Sackgasse?
- Menge änderbar, Position entfernbar?
- Zwischensumme, Versand und Gesamtsumme getrennt ausgewiesen?
- Gibt es einen Hinweis auf Zahlarten schon hier?

### 5. Die Kasse

Ohne Bestellung, nur bis zur Zahlungsauswahl. Wenn kein Testwarenkorb erlaubt
ist, aus den öffentlichen Seiten ableiten, was geht.

- **Gastbestellung möglich?** Kontozwang ist einer der härtesten Abbruchgründe.
  `crit`, wenn ein Konto Pflicht ist.
- Wie viele Schritte bis zur Zahlungsauswahl? Ein Schritt ist gut, drei sind
  normal, fünf sind ein Befund.
- Wie viele Pflichtfelder? Wird die Adresse doppelt abgefragt (Liefer- und
  Rechnungsadresse ohne "gleich wie")?
- Ist erkennbar, wo man im Ablauf steht?

### 6. Zahlarten

- Welche werden angeboten, und wo stehen sie? Nur im Footer, oder auch am
  Kaufpunkt?
- Fehlt eine, die der Zielgruppe entspricht (Rechnung im Handwerk, PayPal und
  Klarna im Endkundengeschäft, SEPA bei Abos)?
- Werden Zahlungsanbieter-Logos als Vertrauenssignal genutzt oder nur als
  Fußnote?

### 7. Handy

Der Shop wird mehrheitlich am Handy angesehen, der Screenshot liegt vor.

- Sind Buttons und Formularfelder groß genug zum Treffen?
- Muss horizontal gescrollt werden?
- Verdeckt ein Banner, ein Cookie-Dialog oder eine Chat-Blase den Kaufbutton?
  **Diesen Befund hart nachprüfen**, nicht aus einem Screenshot herauslesen: eine
  Einblendung, die beim Screenshot zufällig oben lag, ist kein Beleg für eine
  dauerhafte Verdeckung.

## Ausgabe

Zwei Dateien nach `<run>/findings/`:

**`L3-purchase-path.json`**: Array. Je Befund: `severity` (crit|warn|ok),
`title`, `detail` (was ist der Fall, mit Beleg), `recommendation` (der konkrete
nächste Schritt), `evidence` (URL, wörtliches Zitat oder benanntes Element),
`url` (der eine klickbare Deep-Link), `impact` (Geschäftswirkung in einem Satz),
`effort` (0,5 Tag / 1 bis 2 Tage / 1 bis 2 Wochen), `confidence`, `lens: "purchase-path"`.

**`L3-purchase-path.coverage.json`**: `{"checked": [...], "not_checkable": [{"what", "reason"}]}`.
Jeder der sieben Punkte oben steht in genau einer der beiden Listen. Ein Punkt,
der nicht geprüft werden konnte, weil die Kasse einen Login verlangt, gehört in
`not_checkable` mit genau diesem Grund, nicht in einen erfundenen Befund.

**Ein bis zwei `ok`-Befunde sind Pflicht.** Was hier gut läuft, soll der Leser
sehen und behalten. Ein Shop, dessen Kaufstrecke sauber ist, bekommt das gesagt.
