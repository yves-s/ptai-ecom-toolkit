# Zugänge für den Initialaudit

Zwei Teile, weil es zwei verschiedene Dinge sind. **Teil A** richtet der
Betreiber einmal ein, danach gilt er für jeden Kunden. **Teil B** geht nach Vertragsschluss an
den Kunden und ist so geschrieben, dass er direkt rausgehen kann.

Der Setup-Wizard (`/ptai-ecom:setup`) prüft gegen genau diese Liste und meldet
je Zeile OK, fehlt oder kaputt.

---

## Teil A: einmalig beim Betreiber

Die Reihenfolge ist nicht beliebig, jeder Schritt baut auf dem vorherigen auf.
Schritt 6 zuerst anstoßen, er wartet auf eine Freigabe durch Google.

### 1. Google-Cloud-Projekt

console.cloud.google.com, neues Projekt anlegen. Ein Projekt für alle Kunden
reicht, die Trennung passiert über die Property-Freigaben beim Kunden.

### 2. APIs aktivieren

Im Projekt unter "APIs & Dienste" aktivieren:
- Google Analytics Data API
- Google Analytics Admin API (liest Name und Mess-IDs der Property, siehe unten)
- Google Search Console API
- PageSpeed Insights API
- Chrome UX Report API (für die Wochenhistorie der Core Web Vitals)

**Die Admin API ist seit dem 07.09.2026 dabei, und der Grund ist ein realer
Fall.** Ein Shop lud zwei GA4-Mess-IDs auf jeder Seite, der Audit zog eine
Property, und niemand konnte sagen, ob es die war, in der die Bestellungen
ankommen. Genau daran hing der schwerste Befund des Reports: vier Monate ohne
gemessenen Umsatz, mit zwei möglichen Erklärungen, einem gebrochenen Tag und
einer Umstellung auf serverseitiges Tracking in eine andere Property. Ohne die
Admin API bleibt diese Frage in jedem Lauf offen. Der Scope ist derselbe wie
für die Data API (`analytics.readonly`), es fehlt nur die Freischaltung.

### 3. Service-Account plus Schlüssel

"IAM & Verwaltung" → "Dienstkonten" → Dienstkonto erstellen. Danach unter
"Schlüssel" einen JSON-Schlüssel erzeugen und lokal ablegen, außerhalb von Git.
Der Pfad steht als `PTAI_GOOGLE_CREDENTIALS` in der `.env` des Workspace, nie
in der Config und nie zentral.

**Die Mailadresse des Dienstkontos ist der Zugang, den der Kunde freischaltet**,
nicht die persönliche Adresse des Betreibers. Sie sieht aus wie
`ptai-reporting@<projekt>.iam.gserviceaccount.com` und gehört in Teil B
eingesetzt.

### 4. PageSpeed-Insights-Key

Unter "APIs & Dienste" → "Anmeldedaten" einen API-Schlüssel erzeugen. Ohne Key
läuft der Abruf gegen ein enges Kontingent.

**Der Schlüssel muss zwei APIs erlauben, nicht eine.** Wird er unter
API-Einschränkungen auf die PageSpeed Insights API allein eingeschränkt,
antwortet die CrUX-History-API mit 403 "blocked", und die Wochenhistorie der
Core Web Vitals fällt still aus: `psi_pull.sh` ruft beide mit demselben
Schlüssel. Freigeben also **PageSpeed Insights API und Chrome UX Report API**.
Beide müssen im Projekt außerdem unter "APIs & Dienste" aktiviert sein.
`check_env.sh` prüft die zweite seit dem 06.09.2026 mit.

Der Schlüssel gehört als `PTAI_PSI_KEY` in `~/.config/ptai-ecom/.env`.

### 5. DataForSEO

Eigenes Konto auf dataforseo.com. Im Dashboard unter "API Access" stehen Login
und API-Passwort; das API-Passwort ist nicht das Konto-Passwort und wird nur in
den ersten 24 Stunden angezeigt, danach über "Send by e-mail". Beides gehört als
`PTAI_DFS_LOGIN` und `PTAI_DFS_PASSWORD` in `~/.config/ptai-ecom/.env`. Das
Startguthaben von 1 USD reicht nicht sicher für einen Audit; aufladen geht ab
50 USD, das Guthaben verfällt nicht. Die Durchleitung samt Test-Call steht in
der Setup-Skill, Abschnitt "DataForSEO".

DataForSEO kennt weder Projekte noch Unterkonten. Die Zuordnung je Kunde
passiert über das Feld `tag` und die Datei `dfs-ledger.jsonl` im
Kunden-Workspace, siehe Spec Abschnitt 13.

### 6. Google-Ads-Entwicklertoken

**Zuerst anstoßen, das dauert.** Ein Entwicklertoken hängt an einem
Google-Ads-Verwaltungskonto und wird von Google freigegeben. Ohne Token kommt
die SEA-Baseline aus einem Berichtsexport des Kunden, der Audit läuft trotzdem.

Weg: Google-Ads-Verwaltungskonto anlegen oder verwenden, dort unter "Tools und
Einstellungen" → "API-Center" das Token beantragen.

**Der Antrag endet nicht mit "Token da".** Ein Token bekommt eine
Zugriffsebene, und die niedrigste erlaubt ausschließlich Aufrufe gegen
Testkonten. Für einen Kundenaudit reicht das nicht. Nach der Freigabe deshalb
prüfen, welche Ebene das Token hat, und gegebenenfalls die Höherstufung
beantragen. Das Token und der Zugang zum Werbekonto des Kunden sind zwei
verschiedene Dinge: das Token gehört uns, den Zugang gibt der Kunde. Der Antrag fragt nach dem
Verwendungszweck; hier zählt die Beschreibung als Reporting-Werkzeug für
betreute Konten.

Das Token gehört als `PTAI_GOOGLE_ADS_TOKEN` in `~/.config/ptai-ecom/.env`.

### Offen, im ersten Setup zu klären

- **Shopify-Bestellhistorie über 60 Tage.** Die Admin-API liefert ältere
  Bestellungen nur mit dem Scope `read_all_orders`. Wie der bei einem
  Mitarbeiterzugang über die Shopify CLI genau beantragt wird, ist am ersten
  Kunden zu verifizieren. Bis dahin gilt: nach dem ersten Pull prüfen, ob die
  Historie wirklich vollständig ist, statt der Zahl zu vertrauen.
- **Scope-Namen** für Theme, Skript-Tags und Marktkonfiguration je nach App-Typ.
- **Judge.me** und andere Bewertungstools: Zugang über den Shopify-Account oder
  über einen eigenen API-Key, je nach Installation.

---

## Teil B: was wir vom Kunden brauchen

Ab hier ist der Text für den Kunden. Vor dem Verschicken vier Platzhalter
ersetzen: `<betreiber-name>`, `<betreiber-mail>`, `<dienstkonto-mail>`,
`<shop-domain>`.

---

# Zugänge für den Audit

Bevor wir loslegen, brauche ich lesenden Zugriff auf eure Systeme. Damit ziehe
ich einmal alle Zahlen, die es zu <shop-domain> gibt, und lege daraus die
Baseline an. Die Baseline ist der Startpunkt, gegen den wir ab dann jeden Monat
messen, was unsere Arbeit gebracht hat.

## Was ich mit den Zugängen mache

Ich lese, und ich schreibe nichts. In euren Systemen ändert sich durch den
Audit nichts. Deshalb reicht mir überall die niedrigste Stufe, die die Berichte
sichtbar macht.

Personenbezogene Daten bleiben bei euch. Ich ziehe Bestellungen als Summen und
Auswertungen, keine Namen, keine Adressen, keine Mailadressen. Was ich
speichere, sind Kennzahlen und Screenshots eures Shops.

## Pflicht

**Shopify**

Einen Mitarbeiterzugang für `<betreiber-mail>` mit Leserechten auf Analysen,
Produkte, Bestellungen und Design. Dabei brauche ich die vollständige
Bestellhistorie, weil Shopify nach außen sonst nur die letzten 60 Tage
herausgibt. Die Baseline reicht dann keine zwei Monate zurück, und der
Vergleich zum Vorjahr fehlt uns danach das ganze Jahr über.

*Einstellungen → Benutzer → Mitarbeiter hinzufügen*

**Google Analytics 4**

Die Rolle "Betrachter" auf der Property für `<dienstkonto-mail>`. Das ist eine
technische Adresse und kein Postfach. Über sie lese ich die Zahlen aus.

*Verwaltung → Property-Zugriffsverwaltung → Nutzer hinzufügen*

**Google Search Console**

Berechtigung für `<dienstkonto-mail>`, dieselbe Adresse wie bei Analytics.
"Vollständig" ist mir lieber als "Eingeschränkt", weil die Berichte zur
Indexierung sonst fehlen.

*Einstellungen → Nutzer und Berechtigungen → Nutzer hinzufügen*

## Empfohlen

**Klaviyo**

Ein Nutzer für `<betreiber-mail>` in der Rolle "Analyst". Ohne den Umsatz aus
E-Mail kann ich die anderen Kanäle nicht einordnen, weil mir der Nenner fehlt.

*Settings → Users → Invite user*

## Optional

**Google Ads**

Nur, wenn ihr Suchanzeigen schaltet. Zugriffsebene "Nur Lesen" für die
Dienstkonto-Mailadresse, dieselbe wie bei Analytics und der Search Console. Der
Audit liest über die API, und die läuft über das Dienstkonto, nicht über einen
persönlichen Zugang. Zusätzlich gern "Nur Lesen" für `<betreiber-mail>`. Damit
sehe ich, welche Suchbegriffe tatsächlich Geld kosten und welche davon etwas
einbringen.

*Tools und Einstellungen → Zugriff und Sicherheit → Nutzer → Hinzufügen*

**Der Crawler in eurer Firewall**

Falls vor dem Shop eine Bot-Erkennung läuft (bei Shopify ist das fast immer
Cloudflare), eine Ausnahme für den User-Agent `ptai-audit`. Ohne sie weist die
Firewall den Crawl auf einem Teil der Seiten ab, und genau die Kategorieseiten
sind davon am häufigsten betroffen. Langsamer crawlen hilft dagegen nicht: die
Abweisung hängt nicht am Tempo, sondern daran, dass die Firewall einen
unbekannten Crawler sieht.

*Cloudflare → Security → WAF → Tools → User Agent Blocking, oder eine
Custom Rule mit Action "Skip" für diesen User-Agent*

Ohne die Ausnahme läuft der Audit trotzdem. Die abgewiesenen Seiten stehen im
Report als nicht messbar samt Zahl, statt still zu fehlen.

## Wenn etwas fehlt

Ich kann den Audit auch mit einem Teil der Zugänge fahren. Jede Quelle, die
fehlt, steht im Report als fehlend samt Grund, und ihre Kennzahlen bleiben leer,
statt geschätzt zu werden. Kommt ein Zugang später dazu, trage ich seinen Teil
nach.

Bei einer Sache bitte ich euch um Eile. Screenshots, Crawl und Ladezeiten kann
ich nur so lange aufnehmen, wie der Shop im heutigen Stand steht. Ändert ihr
das Theme vorher, ist der Vorher-Zustand weg, und wir können später nicht
zeigen, was sich verbessert hat.

Sollte ansonsten irgendwas sein, meldet euch gerne jederzeit.

Ich freue mich auf den Start.

<betreiber-name>

---

## Die Mail, mit der Teil B rausgeht

Register R6, Gruppe. Empfänger sind die Ansprechpartner beim Kunden.

**Betreff:** Zugänge für den Audit

Hey zusammen,

wie besprochen ziehe ich als erstes den Audit und lege daraus die Baseline an,
also den Startpunkt, gegen den wir ab dann messen.

Dafür brauche ich von euch lesenden Zugriff auf eure Systeme. Was genau und wo
ihr jeweils klicken müsst, steht im Dokument im Anhang. Ich lese damit nur, ich
ändere in keinem eurer Systeme etwas.

Schreibt mir kurz Bescheid, sobald ihr durch seid, dann starte ich den Lauf.

Sollte ansonsten irgendwas sein, meldet euch gerne jederzeit.

Ich freue mich auf den Start.

BG
<betreiber-name>
