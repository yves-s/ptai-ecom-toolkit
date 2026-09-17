---
name: lens-trust
description: Vertrauen und Pflichtangaben eines Shops von außen prüfen, also Impressum, Widerrufsbelehrung, AGB, Datenschutzerklärung, Preisangaben samt Grundpreis, Versandkostenhinweis, Bewertungen am Kaufpunkt und Prüfsiegel. Stellt fest, was vorhanden und auffindbar ist, und bewertet ausdrücklich nicht juristisch. Nutzen als Linse L4 in ptai-ecom:audit-light, oder wenn der Nutzer wissen will, ob ein Shop die Angaben zeigt, die ein deutscher Käufer erwartet. Liefert belegte Befunde mit Deep-Link.
---

# lens-trust: Pflichtangaben und Vertrauen, von außen

Der Teil des Audits, der einem Händler am schnellsten weh tut und am schnellsten
zu schließen ist. Ein fehlendes Impressum kostet nichts in der Umsetzung und
viel im Ernstfall.

## Die eine Regel, die über allem steht

**Diese Linse stellt fest, sie urteilt nicht.** Ein Befund lautet "vorhanden",
"nicht auffindbar" oder "unvollständig gegenüber der üblichen Praxis". Er lautet
**nie** "rechtswidrig", "abmahnfähig" oder "verstößt gegen". Der Report ist kein
Rechtsrat, und ein falsches Rechtsurteil im Anschreiben eines kalten Leads ist
schlimmer als ein fehlender Befund.

Die richtige Formulierung für einen Mangel: *"Auf der Produktseite ist kein
Grundpreis je Kilogramm ausgewiesen. Bei Waren nach Gewicht ist das üblich und
sollte anwaltlich geprüft werden."* Nicht: *"Verstoß gegen die
Preisangabenverordnung."*

## Was diese Linse nicht kann

- **Keine Vollständigkeitsprüfung eines Rechtstexts.** Ob eine
  Widerrufsbelehrung inhaltlich trägt, entscheidet ein Anwalt. Geprüft wird, ob
  sie existiert, erreichbar ist und die üblichen Bestandteile benennt.
- **Was hinter der Kasse liegt, bleibt ungeprüft**, solange kein Testkauf
  stattfindet. Die Pflichtangaben im Bestellprozess (Button-Beschriftung,
  Bestellübersicht) sind dann `not_checkable` mit genau diesem Grund.
- **Siegel-Echtheit** ist nur prüfbar, wenn das Siegel verlinkt ist. Ein Bild
  ohne Link ist ein Befund, kein Betrugsvorwurf.

## Die Prüfpunkte

### 1. Impressum

- Aus dem Footer jeder Seite erreichbar, mit maximal einem Klick?
- Enthält es Firmenname mit Rechtsform, Anschrift, vertretungsberechtigte Person,
  eine Kontaktmöglichkeit und, bei einer eingetragenen Gesellschaft, Register und
  Nummer?
- Stimmt der Firmenname mit dem überein, der im Shop auftritt? Eine Marke, die
  im Impressum plötzlich einer fremd klingenden GmbH gehört, ist kein Mangel,
  aber ein Punkt fürs Gespräch.

`crit`, wenn kein Impressum auffindbar ist. `warn` bei fehlenden Einzelangaben.

### 2. Widerruf, AGB, Datenschutz

Je Dokument: erreichbar aus dem Footer, eigene URL, lesbar ohne Login.

- **Widerrufsbelehrung:** vorhanden? Wird eine Frist genannt? Gibt es ein
  Muster-Formular oder einen Hinweis darauf?
- **AGB:** vorhanden und datiert?
- **Datenschutzerklärung:** vorhanden? Nennt sie die eingesetzten Dienste? Der
  Crawl-Snapshot listet die eingebundenen Fremdskripte, das ist der Gegencheck:
  ein Shop, der Google Analytics lädt, es aber nicht nennt, ist ein Befund.

Der Abgleich Fremdskripte gegen Datenschutzerklärung ist der stärkste Fund
dieser Gruppe, weil er belegbar ist: Skript-Host aus `crawl.json`, Volltext der
Erklärung, keine Erwähnung.

### 3. Cookie-Dialog

- Gibt es einen, bevor nicht notwendige Dienste laden?
- Ist "Ablehnen" gleichwertig sichtbar wie "Akzeptieren", oder muss man sich
  durch eine zweite Ebene klicken?
- Laden Tracking-Skripte schon vor der Einwilligung? Im Crawl sichtbar, wenn ein
  Skript-Host ohne Interaktion auftaucht.

**Diesen Befund hart nachprüfen.** Ein aus einem Screenshot abgeleiteter
Cookie-Befund war schon einmal falsch. Wenn nur das Bild vorliegt und nicht der
Ladevorgang, ist es ein Prüfauftrag mit `confidence: "low"`.

### 4. Preisangaben

- Steht bei jedem Preis, dass er die Mehrwertsteuer enthält, und dass Versand
  hinzukommt?
- **Grundpreis:** bei Waren nach Gewicht, Volumen, Länge oder Stückzahl je
  Einheit ausgewiesen (je Kilogramm, je Liter, je 100 Stück)? Das fehlt häufig
  und ist billig zu beheben.
- Streichpreise: ist erkennbar, worauf sie sich beziehen?

### 5. Versandkosten

- Aus dem Footer eine eigene Seite mit Kosten und Lieferzeiten?
- Steht der Hinweis auch am Preis, nicht nur in der Fußzeile?

Überschneidet sich bewusst mit `lens-purchase-path` Punkt 3. Dort ist es ein
Conversion-Fund, hier ein Pflichtangaben-Fund. **Beim Konsolidieren wird daraus
ein Befund**, der stärkere Beleg gewinnt.

### 6. Bewertungen am Kaufpunkt

- Gibt es Bewertungen, und stehen sie auf der Produktseite oder nur auf einer
  Unterseite?
- Ist die Zahl der Bewertungen genannt, oder nur Sterne?
- Steht dabei, woher sie stammen und ob sie geprüft sind?
- Ist ein Durchschnitt sichtbar, den die Suchmaschine auch lesen kann? Der
  Gegencheck kommt aus dem Schema-Befund von L1: Sterne im Bild, aber kein
  `aggregateRating` in den strukturierten Daten, ist ein häufiger und gut
  belegbarer Fund.

**Ohne Screenshot kein Absenz-Befund.** Review-Widgets werden fast immer erst im
Browser gerendert.

### 7. Siegel und Mitgliedschaften

- Welche werden gezeigt (Trusted Shops, Käufersiegel, Zahlungsanbieter, eigene
  Garantien)?
- Sind sie verlinkt und beim Aussteller nachprüfbar? Ein nicht verlinktes Siegel
  ist ein `warn`: es wirkt nur, wenn es prüfbar ist.
- Stehen sie am Kaufpunkt oder nur im Footer?

### 8. Kontaktweg

- Findet ein Käufer eine Telefonnummer, eine Mailadresse oder ein Formular ohne
  zu suchen?
- Gibt es Angaben zu Erreichbarkeit oder Antwortzeit?

## Ausgabe

Zwei Dateien nach `<run>/findings/`:

**`L4-trust.json`**: Array mit denselben Feldern wie die übrigen Linsen:
`severity`, `title`, `detail`, `recommendation`, `evidence`, `url`, `impact`,
`effort`, `confidence`, `lens: "trust"`.

**`L4-trust.coverage.json`**: jeder der acht Punkte steht in `checked` oder
in `not_checkable` mit Grund.

**Zwei Dinge, die im Report stehen müssen**, sobald diese Linse einen Mangel
meldet: der Satz, dass es sich um eine Feststellung und keine Rechtsprüfung
handelt, und die Empfehlung, die betroffenen Punkte anwaltlich prüfen zu lassen.
Beides gehört in `recommendation`, nicht in eine Fußnote, die niemand liest.
