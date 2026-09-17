---
name: ecom-language
description: Die Fachsprache für jedes E-Commerce-Dokument mit Zahlen darin, und der Aufbau eines Befunds. Hält die fünf Elemente eines Befunds (Zustand, Einordnung, Ursache, Folge, Empfehlung), die Regel "Fachbegriff verwenden und beim ersten Auftreten erklären", das Vokabular selbst mit seinen Erklärsätzen und die Liste der Laienwörter, die nie in einem Kundendokument stehen. Wird von ptai-ecom:audit, ptai-ecom:report und den Analyse-Agents des Audits vor dem ersten Befund geladen, ebenso von workos:report, falls installiert, und gilt genauso für Angebote und Analysen, die E-Commerce-Zahlen tragen. Nutze sie, wenn ein Befund, eine Kennzahl oder eine Maßnahme formuliert wird. Nicht verwenden für Mails und Nachrichten und nicht für den Aufbau eines Reports insgesamt.
---

# ecom-language: die Fachsprache und der Aufbau eines Befunds

Ein Report, der Fachbegriffe umschreibt, ist nicht verständlicher, er ist unbrauchbar. Der
Leser ist Geschäftsführer oder E-Commerce-Verantwortlicher: er kennt sein Geschäft, er kennt
seine Tools, und er merkt sofort, wenn jemand um einen Begriff herumredet.

## Die eine Regel

**Nimm den Fachbegriff und erklär ihn beim ersten Auftreten in einem Halbsatz.** Nie ein
Laienwort erfinden, nie umschreiben, nie weglassen.

> Im Produkt-Schema, den strukturierten Daten, aus denen Google den Preis für
> Shopping-Einträge liest, ist das Feld `priceValidUntil` bei jedem geprüften Produkt exakt auf
> das Abrufdatum gesetzt.

Der Begriff steht da, die Erklärung ist ein Nebensatz, und wer den Begriff kennt, liest über
sie hinweg. Das ist die Bauform, in jedem Befund, bei jedem Begriff, einmal pro Dokument.

## Die fünf Elemente eines Befunds

Aus dem IIA Audit Report Writing Toolkit, der Standardform für Prüfberichte. Ein Befund, dem
eines fehlt, lässt den Leser mit einer Zahl allein.

| Element | Was es beantwortet | Woran man merkt, dass es fehlt |
|---|---|---|
| **Zustand** | Was ist der Fall, mit Zahl und Zeitraum | Der Titel nennt keine Zahl |
| **Einordnung** | Woran gemessen, was wäre normal | "4,7 Prozent" steht da, und niemand weiss, ob das gut ist |
| **Ursache** | Warum ist es so | Die Empfehlung wirkt geraten |
| **Folge** | Was heisst das geschäftlich | Der Leser fragt "und?" |
| **Empfehlung** | Was ist konkret zu tun, wo | Es bleibt bei "sollte optimiert werden" |

**Die Einordnung ist die, die am häufigsten fehlt, und sie ist die wertvollste.** Drei Formen,
in dieser Reihenfolge:

1. **Gegen eine Benchmark**, mit Quelle und Abrufdatum. Die belegten Bänder stehen in
   `${CLAUDE_PLUGIN_ROOT}/reference/metrics.md`, sie sind Fremdquellen und ordnen ein, sie bewerten nicht.
2. **Gegen den eigenen Datensatz**, wenn es keine Benchmark gibt: die Nachbarstufe im Funnel,
   der Vorjahresmonat, der Rest des Sortiments.
3. **Mit dem Satz, dass es keine gibt.** *"Für die Add-to-Cart-Rate gibt es keine belastbare
   Branchen-Benchmark, deshalb der interne Vergleich."* Das ist eine vollwertige Einordnung
   und allemal besser als eine erfundene Schwelle.

## Der Titel ist die Aussage, nicht ihr Anfang

Ein Befundtitel trägt die Zahl und sagt, was der Fall ist. Er ist kein Thema und kein
Halbsatz.

| Nicht | Sondern |
|---|---|
| Zwischen Produktansicht und Warenkorb-Zugabe bricht der Kaufweg am stärksten ein | Nur 4,7 Prozent der Produktansichten führen zu einer Warenkorb-Zugabe |
| Mehrere Skripte fremder Anbieter fehlen in der Datenschutzerklärung | Acht von zwölf eingebundenen Drittanbieter-Diensten fehlen in der Datenschutzerklärung |
| Auf allen geprüften Seiten läuft ein Werkzeug für Bewertungen | Trustpilot blendet auf allen geprüften Produktseiten Bewertungen ein |
| Alle fünf Schritte des Kaufwegs werden gemessen, keiner steht auf null | Alle fünf Funnel-Stufen senden Events, die Messkette ist vollständig |

## Laienwörter, die nie in einem Kundendokument stehen

Jedes davon ist ein Fehler, kein Stilproblem. Links steht, was tatsächlich vorkam.

| Laienwort | Was stattdessen dasteht |
|---|---|
| ein Werkzeug, Testwerkzeug | der Produktname (Klaviyo, Doofinder, Trustpilot), sonst die Kategorie: A/B-Testing-Tool, E-Mail-Marketing-Tool |
| Menschen, echte Menschen | Sessions, Unique Visitors, Nutzer, je nachdem was gezählt wurde |
| mehrere, einige, viele, praktisch alle | die Zahl: acht von zwölf, 284 von 333 |
| Skripte fremder Anbieter | Drittanbieter-Dienste, Third-Party-Scripts |
| Trichter | Funnel |
| Ladezeit-Werte | Core Web Vitals, oder die einzelne Metrik: LCP, INP, CLS |
| Suchmaschinen-Vorschautext | Meta-Description |
| Haupt-Adresse einer Seite | Canonical-URL |
| KI-Suche allgemein | die Plattform: ChatGPT, Perplexity, Google AI Overviews |
| Besuche, die bis zur Kasse kamen | Sessions mit `begin_checkout`, oder Checkout-Einstiege |

**Umgekehrt gilt genauso:** unsere Pipeline hat im Kundendokument nichts verloren. Nie
`crawl.json`, `jq`, DataForSEO, run-id, Snapshot, Pull. Der Beleg nennt die Quelle in
Kundensprache: *"Quelltext der Startseite"*, *"GA4-Funnel, Sessions je Ereignis"*, *"Crawl vom
08.09.2026"*.

## Das Vokabular

Die Begriffe, die in E-Commerce-Dokumenten vorkommen, mit dem Halbsatz, der sie erklärt. Nicht
auswendig lernen, nachschlagen, wenn einer gebraucht wird.

### Traffic und Messung

| Begriff | Erklärsatz beim ersten Auftreten |
|---|---|
| Session | eine zusammenhängende Besuchsfolge eines Nutzers, die nach 30 Minuten Inaktivität endet |
| Unique Visitor | ein einzelner Besucher, unabhängig davon, wie oft er wiederkommt |
| Bounce Rate | der Anteil der Sessions mit nur einer Seitenansicht und ohne Interaktion |
| Attribution | die Zuordnung eines Kaufs zu dem Kanal, über den der Nutzer kam |
| Consent Layer | das Einwilligungsfenster, das vor dem Laden nicht notwendiger Dienste erscheint |
| Server-side Tracking | die Messung über den eigenen Server statt über ein Skript im Browser |

### Conversion

| Begriff | Erklärsatz beim ersten Auftreten |
|---|---|
| Conversion Rate | der Anteil der Sessions, die zu einer Bestellung führen |
| Conversion Funnel | die Stufenfolge von der Produktansicht bis zum Kauf |
| Add-to-Cart-Rate | der Anteil der Sessions mit Produktansicht, in denen ein Artikel in den Warenkorb gelegt wird |
| Cart Abandonment Rate | der Anteil der gefüllten Warenkörbe, die nicht zur Bestellung führen |
| AOV, Bestellwert | der durchschnittliche Umsatz je Bestellung |
| Repeat-Rate | der Anteil der Bestellungen von Kunden, die schon einmal gekauft haben |
| Viewport, above the fold | der Bereich, der ohne Scrollen sichtbar ist |
| PDP, PLP | Produktdetailseite und Produktlistenseite, also Kategorieseite |

### Sichtbarkeit

| Begriff | Erklärsatz beim ersten Auftreten |
|---|---|
| SERP | die Trefferliste einer Suchmaschine |
| Impression Share | der Anteil der möglichen Einblendungen, den eine Anzeige tatsächlich bekommt |
| Share of Voice | der Anteil an der Gesamtsichtbarkeit einer Wettbewerbsgruppe |
| Canonical-Tag | das Element, das Google mitteilt, welche von mehreren ähnlichen Seiten die Haupt-URL ist |
| Hreflang | die Auszeichnung, die Google sagt, welche Sprachversion für welches Land gilt |
| Orphan Page | eine Seite, auf die kein interner Link zeigt, die also nur über die Sitemap auffindbar ist |
| Klicktiefe | die Zahl der Klicks von der Startseite bis zu einer Seite |
| Crawl-Budget | die Zahl der Seiten, die eine Suchmaschine je Durchgang abruft |
| Structured Data, Schema | ein maschinenlesbares Datenformat im Quelltext, aus dem Google Preis, Verfügbarkeit und Bewertungen liest |
| GEO | die Sichtbarkeit in den ausformulierten Antworten von ChatGPT, Perplexity und Google AI, nicht in der klassischen Trefferliste |

### Technik

| Begriff | Erklärsatz beim ersten Auftreten |
|---|---|
| Core Web Vitals | Googles drei Messwerte für Ladeerlebnis: LCP, INP und CLS |
| LCP | wie lange es dauert, bis der grösste sichtbare Inhalt geladen ist |
| INP | wie lange die Seite braucht, bis sie auf eine Eingabe reagiert |
| CLS | wie stark der Inhalt beim Laden verspringt |
| Third-Party-Script | ein Skript, das der Shop von einem fremden Server nachlädt |

## Die Maßnahme braucht ihre Kennzahl

Eine Maßnahme ohne Kennzahl ist eine Absichtserklärung. Vier Angaben, immer:

| Angabe | Beispiel |
|---|---|
| Kennzahl | Add-to-Cart-Rate, mobil |
| Ausgangswert | 4,7 Prozent (alle Geräte, zwölf Monate bis zum Stichtag) |
| Prüfregel | Button ohne Scrollen sichtbar bei 390 x 844 px, Consent-Layer offen |
| Messbar ab | vier Wochen nach Livegang, gegen denselben Vorjahreszeitraum |

Ohne "messbar ab" wird nach zwei Wochen gegen Rauschen gemessen und die Maßnahme für
wirkungslos erklärt.

## Prüfen

Vor der Freigabe, in dieser Reihenfolge:

1. **Jeder Fachbegriff einmal erklärt?** Beim ersten Auftreten, nicht beim dritten.
2. **Kein Laienwort aus der Tabelle oben?** Maschinell über `python3 -m audit.qa`
   aus `${CLAUDE_PLUGIN_ROOT}/scripts`, sonst per Suche.
3. **Trägt jeder Befund alle fünf Elemente?** Besonders die Einordnung.
4. **Nennt jeder Titel seine Zahl?**
5. **Steht in jedem Beleg die Quelle in Kundensprache**, nicht der Dateiname aus der Pipeline?

## Grenzen

Diese Skill regelt das Vokabular und den Aufbau eines Befunds. Sie regelt **nicht** den Aufbau
eines Reports (`workos:report`, falls installiert), nicht die Stimme in Mails und Posts
und nicht die Cover-Headline. Wo ein Report verkauft statt beschreibt, gilt dort und nur dort
`workos:voice`, falls installiert.
