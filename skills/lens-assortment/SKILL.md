---
name: lens-assortment
description: Sortiment und Produktdaten eines Shops von außen prüfen, also Filter und Sortierung auf der Kategorieseite, Varianten, Produkttexte, Bildanzahl und Bildqualität, Cross-Selling und den Umgang mit ausverkauften Artikeln. Nutzen als Linse L5 in ptai-ecom:audit-light, oder wenn der Nutzer wissen will, ob ein Shop sein Sortiment auffindbar und kaufbar macht. Nimmt den Produktseiten-Teil aus claude-seo:seo-ecommerce mit, ohne dessen kostenpflichtige Marktplatz-Abfragen. Liefert belegte Befunde mit Deep-Link.
---

# lens-assortment: Sortiment und Produktdaten

Zwischen "der Shop wird gefunden" und "der Kauf klappt" liegt die Frage, ob der
Kunde überhaupt zu dem Produkt kommt, das er will, und ob er dort genug erfährt,
um sich zu entscheiden. Das ist diese Linse.

**Aus `claude-seo:seo-ecommerce` kommt Abschnitt 1**, die Produktseiten-Analyse
ohne DataForSEO: Title, Meta-Description, Überschriften-Struktur, Bilder,
interne Verlinkung, Contentqualität. **Nicht** übernommen werden Abschnitt 2
(Google Shopping) und Abschnitt 3 (Amazon): beide brauchen die kostenpflichtige
Merchant-API. Wo diese Fragen gebraucht werden, deckt sie `pull-dfs-shopping`
direkt ab, und dann steht die Antwort als Snapshot im Lauf statt als Vermutung
im Befund.

## Was diese Linse nicht kann

- **Keine Aussage über Absatz.** Welches Produkt sich verkauft, steht in
  Shopify, nicht im Shop. "Bestseller" und "umsatzstärkste Seite" sind
  verboten. Erlaubt ist "prominenteste laut Navigation" mit dem Beleg, wo es
  verlinkt ist.
- **Keine vollständige Katalogprüfung.** Geprüft werden die Seitentypen aus dem
  Lauf plus Stichproben, nicht 3.000 Produkte. Ein Befund über den Katalog
  insgesamt braucht die Zahlen aus dem Crawl-Snapshot, nicht ein Gefühl aus drei
  Seiten.
- **Galeriebilder sieht auch der Screenshot nur teilweise.** Nie behaupten, es
  gebe "nur ein Bild", wenn nur die Erstansicht vorlag.

## Die Prüfpunkte

### 1. Die Kategorieseite

- Gibt es **Filter**, und filtern sie nach dem, wonach dieser Markt sucht? Ein
  Modeshop ohne Größenfilter und ein Werkzeugshop ohne Filter nach Anwendung
  sind derselbe Fund in zwei Märkten.
- Wie viele Filter? Drei sind oft zu wenig, um ein Sortiment ab ein paar hundert
  Artikeln beherrschbar zu machen.
- Gibt es eine **Sortierung**, und ist sie sinnvoll vorbelegt?
- Wie viele Produkte pro Ansicht, und wie kommt man zu den nächsten (Paginierung,
  Nachladen, "Mehr anzeigen")?
- Trägt die Kategorieseite einen eigenen Text, der erklärt, was hier drin ist?
  Der Crawl liefert die Wortzahl, das ist der Beleg.

`crit`, wenn eine Kategorie mit vielen Artikeln keinerlei Filter hat.

### 2. Varianten

- Wie werden Größe, Farbe oder Ausführung ausgewählt, und ist erkennbar, was
  gewählt ist?
- Ändert sich das Bild mit der Variante?
- Ändert sich der Preis sichtbar, wenn Varianten unterschiedlich kosten?
- Werden nicht lieferbare Varianten ausgegraut oder verschwinden sie kommentarlos?

### 3. Produkttexte

- Gibt es überhaupt eine Beschreibung, oder nur Stichpunkte aus dem Datenblatt?
- Ist der Text eigen oder vom Hersteller? Prüfbar: eine markante Textzeile
  wörtlich per `WebSearch` suchen. Taucht sie bei mehreren Händlern auf, ist es
  Herstellertext. **Das ist ein belegter Fund**, keine Vermutung, und er ist für
  die Auffindbarkeit relevant.
- Beantwortet der Text die Fragen, die vor dem Kauf entstehen (Maße, Material,
  Pflege, Kompatibilität, Lieferumfang)?
- Der Crawl liefert die Wortzahl je Seite: eine Produktseite mit unter 100
  Wörtern ist ein belegbarer Befund über den ganzen Katalog, nicht nur über die
  eine Stichprobe.

### 4. Bilder

- Wie viele je Produkt, und zeigen sie mehr als die Vorderansicht (Detail,
  Rückseite, Größenverhältnis, im Einsatz)?
- Gibt es eine Zoom-Funktion?
- **Alt-Texte:** der Crawl zählt Bilder ohne Alt-Text. Das ist gleichzeitig ein
  Auffindbarkeits- und ein Zugänglichkeitsbefund und gehört mit der Zahl aus dem
  Snapshot belegt.
- Sind die Bilder einheitlich (Freisteller gegen Milieu gemischt wirkt unfertig)?

### 5. Ausverkaufte Artikel

- Was passiert mit einem nicht lieferbaren Produkt: bleibt die Seite mit Hinweis,
  wird sie weitergeleitet, oder läuft sie auf 404?
- Gibt es eine Benachrichtigung bei Verfügbarkeit oder einen Hinweis auf
  Alternativen?
- Der Crawl liefert die Statuscode-Verteilung: viele 404 in Produktpfaden sind
  der Beleg dafür, dass ausgelistete Artikel ersatzlos verschwinden. Das kostet
  Sichtbarkeit, die schon aufgebaut war.

### 6. Cross-Selling

- Werden verwandte oder ergänzende Artikel gezeigt, und passen sie?
- Auf der Produktseite, im Warenkorb, oder gar nicht?
- Ist erkennbar, warum ein Artikel vorgeschlagen wird (Zubehör, Set, ähnlich)?

### 7. Produktseiten-SEO

Aus `claude-seo:seo-ecommerce` Abschnitt 1, gegen den Crawl-Snapshot:

- Title: enthält er Produktname und eine unterscheidende Eigenschaft, oder ist er
  überall gleich aufgebaut? Der Crawl meldet doppelte Titles, das ist der Beleg.
- Meta-Description: vorhanden? Der Crawl liefert den Anteil ohne.
- Genau eine H1? Der Crawl meldet Seiten mit mehreren.
- Interne Verlinkung und Klicktiefe: wie viele Klicks von der Startseite bis zum
  Produkt? Der Crawl liefert die maximale Tiefe und verwaiste Seiten.

**Diese Punkte kommen aus dem Snapshot, nicht aus eigenen Abrufen.** Sie gelten
für den ganzen Katalog und sind damit stärker als jede Stichprobe.

## Ausgabe

Zwei Dateien nach `<run>/findings/`:

**`L5-assortment.json`**: Array, Felder wie in den übrigen Linsen: `severity`,
`title`, `detail`, `recommendation`, `evidence`, `url`, `impact`, `effort`,
`confidence`, `lens: "assortment"`.

**`L5-assortment.coverage.json`**: die sieben Punkte, aufgeteilt in `checked`
und `not_checkable` mit Grund.

**Zahlen aus dem Crawl gehören in die `evidence`.** "37 Bilder ohne Alt-Text bei
842 gecrawlten Seiten" ist ein Beleg. "Viele Bilder ohne Alt-Text" ist keiner,
und der Leser merkt den Unterschied sofort.
