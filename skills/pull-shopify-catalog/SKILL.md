---
name: pull-shopify-catalog
description: Den Produktkatalog eines Shopify-Shops ziehen (Produkte, Varianten, SEO-Felder, Bilder samt Alt-Text, Preise, Einkaufspreise, Collections) und als aggregierten Snapshot ablegen. Nutzen, wenn ein Audit den Baseline-Block Katalog braucht oder der Nutzer wissen will, wie vollständig Produktdaten und SEO-Felder gepflegt sind. Werkzeug ist die Shopify CLI, kein eigener Auth-Weg; liest reporting/config.json im Kunden-Workspace.
---

# pull-shopify-catalog: Katalog-Snapshot ziehen

Holt den Produktkatalog über die Shopify CLI und rechnet daraus einen
aggregierten Snapshot: wie vollständig sind SEO-Felder, Alt-Texte, SKUs und
Einkaufspreise gepflegt, wie sind Beschreibungslängen und Preise verteilt.

## Arbeitsteilung

Die Skill holt die Rohseiten (nur die CLI hat den Auth-Kontext), das Script
`catalog_build.py` rechnet daraus den Snapshot. Der Rechenteil ist der, der
falsche Zahlen erzeugen kann, und genau der ist getestet.

## Voraussetzungen

- `reporting/config.json` mit `shopify_store` und `sources.catalogue` nicht `false`
- Shopify CLI installiert, Store authentifiziert
- Scopes `read_products` und `read_inventory` (letzterer für `unitCost`)

**Die Scope- und Union-Regel steht in `pull-shopify/SKILL.md` und wird hier
nicht wiederholt.** Bei einer Re-Auth immer die Vereinigung senden, nie nur die
neuen Scopes.

## Drosselung: dieselbe Regel wie bei pull-shopify

Beide Pulls teilen sich das Punktebudget der Admin-API. Am ersten echten Lauf
war rund die Hälfte der Calls beim ersten Versuch gedrosselt. **Exit-Code
prüfen, nicht nur stdout lesen**, dann warten und erneut versuchen; der genaue
Ablauf steht in `pull-shopify/SKILL.md`, Abschnitt Ablauf, Schritt 4.

**Die Seitenschleife ist hier der teuerste Teil.** Ein Shop mit 2.000 Produkten
sind acht Seiten zu 250, und jede davon kann gedrosselt werden. Die Schleife
wartet nach einem gedrosselten Versuch und bricht **nicht** ab: sonst entsteht
ein halber Katalog, der wie ein vollständiger aussieht, und die Zahlen darunter
sind alle falsch, ohne dass etwas fehlschlägt.

## Ablauf

1. `reporting/config.json` lesen, Auth nach der Regel aus `pull-shopify` sichern.
2. Produkte seitenweise holen. `description`, **nicht** `descriptionHtml`: in
   den Snapshot geht nur die Länge, und der Rohtext ist kürzer als das Markup.

   ```graphql
   query($cursor: String) {
     products(first: 250, after: $cursor) {
       pageInfo { hasNextPage endCursor }
       nodes {
         handle title status productType vendor description
         seo { title description }
         images(first: 50) { nodes { url altText } }
         variants(first: 100) {
           nodes { sku price inventoryItem { unitCost { amount } } }
         }
       }
     }
   }
   ```

3. Jede Antwortseite **unverändert** in eine Liste sammeln und als JSON-Array
   nach `/tmp` schreiben, nicht nach `reporting/`. Der Rohtext gehört nicht ins
   Kunden-Repo; dort landet nur `catalog.json`.
4. Collections analog über `collections(first: 250, after: $cursor)` mit
   `handle`, `title`, `description`, `seo`.
5. Aggregieren:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/pull-shopify-catalog/scripts/catalog_build.py" \
     --pages /tmp/catalog-pages.json --collections /tmp/catalog-collections.json \
     --out "reporting/data/<run-id>"
   ```

6. Kernzahlen melden: Produkte, Varianten, Anteil mit vollständigen SEO-Feldern,
   Anteil Bilder mit Alt-Text, und jeden Hinweis aus `notes` wörtlich.

## Feldnamen vor dem ersten Lauf verifizieren

Die Namen der Admin-GraphQL hängen an der API-Version, und eine falsch benannte
Verschachtelung liefert `null` statt eines Fehlers. Vor dem ersten Lauf gegen
die Referenz der eingesetzten Version prüfen, insbesondere `seo` am Produkt und
`inventoryItem.unitCost.amount` an der Variante. Werkzeug dafür ist der
Shopify-Dev-MCP, nicht das Gedächtnis.

**Das Script fängt den Fehler ab, wenn die Prüfung ausfällt.** `check_shape()`
meldet jedes Feld, das in **keinem** Produkt vorkommt, als unvollständige
Abfrage. Einzelne Produkte ohne SEO-Felder sind ein Befund über den Shop; ein
Feld, das nirgends vorkommt, ist ein Fehler in der Query. Ohne diese
Unterscheidung meldet der Snapshot "kein Produkt hat SEO-Felder" für einen
Shop, der sie pflegt.

## Snapshot-Schema

`<out>/catalog.json`:

```json
{
  "source": "catalogue",
  "summary": {
    "products_total": 174, "products_active": 168,
    "products_without_seo_title": 12, "products_without_seo_description": 40,
    "products_without_description": 3, "products_without_image": 1,
    "products_with_missing_alt": 96,
    "description_length_p10": 0, "description_length_p50": 230,
    "description_length_p90": 1400,
    "images_total": 512, "images_with_alt": 96, "share_images_with_alt": 0.1875,
    "variants_total": 3370, "variants_without_sku": 4, "variants_without_cost": 3370,
    "collections_total": 22, "collections_without_description": 14
  },
  "products_without_seo_title": ["handle", "..."],
  "products_without_seo_title_truncated": false,
  "products_without_seo_description": ["..."],
  "products_with_missing_alt": ["..."],
  "products_without_cost": ["..."],
  "notes": ["..."]
}
```

**Kein Fließtext.** Aus der Beschreibung wird `description_length`, nie der
Inhalt. Bei 2.000 Produkten ist das der Unterschied zwischen einem Snapshot,
den ein Analyse-Agent lesen kann, und einem, der ihn sprengt.

**Kein Urteil über "dünn".** Der Pull liefert die Längenverteilung (p10, p50,
p90) und die Zahl der Produkte **ohne** Beschreibung. Ab wann eine Beschreibung
zu kurz ist, steht im Kennzahlen-Katalog und gehört der Analyse.

**Einkaufspreis: `null` und `0.00` sind zwei verschiedene Dinge.** `null` heißt
"cost per item nicht gepflegt", `0.00` ist ein gepflegter Wert (Zugabe,
Werbeartikel). Wer beides zusammenwirft, meldet eine zu hohe Lücke. Hat
**keine** Variante einen Einkaufspreis, steht das als Hinweis in `notes`:
Marge und Deckungsbeitrag sind dann für diesen Shop nicht berechenbar (Spec
Abschnitt 19).

**Anteile sind `null`, wenn der Nenner fehlt.** Ein Katalog ohne Bilder hat
keinen Alt-Text-Anteil; eine 0 läse sich als "kein Bild hat einen Alt-Text".

**Listen sind auf 200 gekappt**, der Zähler im `summary` nennt immer die volle
Menge, und `_truncated` sagt, ob gekürzt wurde. Für mehr fragt die Analyse die
Rohseiten gezielt ab, statt sie zu lesen.

## Fehlerbilder

- **Gedrosselt:** warten und erneut versuchen, nie als "keine Daten" werten.
- **`check_shape`-Hinweis in `notes`:** die Abfrage ist unvollständig, nicht
  der Katalog leer. Feldnamen prüfen und erneut ziehen, bevor der Snapshot in
  eine Analyse geht.
- **Kein Einkaufspreis:** kein Fehler, sondern ein Vermerk. Die Marge entfällt.
