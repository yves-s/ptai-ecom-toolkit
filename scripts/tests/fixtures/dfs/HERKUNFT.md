# Herkunft dieser Fixtures

**Echte Produktiv-Antworten** der DataForSEO-API v3, aufgenommen am
07.09.2026 gegen `path-to-ai.com` beziehungsweise, bei `bulk_ranks` und
`bulk_spam_score`, zusätzlich gegen zwei große öffentliche Domains ohne
Geschäftsbeziehung zu Path to AI. Keine Kundendomain.

**Warum nicht aus der Sandbox.** DataForSEO betreibt eine kostenlose Sandbox
mit identischer Struktur und erfundenen Werten. Sie beweist Feldnamen und
sonst nichts. Der Prüfmaßstab dieses Repos ist aber die Richtigkeit der
Zahlen, und die ist gegen Dummy-Werte unsichtbar.

**Was die Aufnahme gekostet hat:** 0,33835 USD für sieben Aufrufe.

| Endpunkt | Kosten |
|---|---:|
| `keywords_data/google_ads/search_volume/live` | 0,09000 USD |
| `backlinks/summary/live` | 0,02404 USD |
| `backlinks/referring_domains/live` | 0,02483 USD |
| `backlinks/anchors/live` | 0,02407 USD |
| `backlinks/bulk_ranks/live` | 0,02411 USD |
| `backlinks/bulk_spam_score/live` | 0,02411 USD |
| `dataforseo_labs/.../historical_rank_overview/live` | 0,12720 USD |

**Was die Aufnahme geklärt hat**, und zwar so, dass es ohne sie falsch
geblieben wäre:

- `search_volume` liefert die Zeilen **flach in `result`**, die vier
  Backlinks-Endpunkte und die Historie **verschachtelt unter
  `result[0].items`**. `summary` ist flach.
- Ein Feld `dofollow` gibt es an den verweisenden Domains **nicht**. Es gibt
  `referring_pages` und `referring_pages_nofollow`. Der erste Entwurf las
  `dofollow`, bekam immer `falsy` und schrieb eine Dofollow-Quote von 0,0 für
  ein Profil, dessen Links zu 83 Prozent folgen.
- `metrics.organic` in der Historie ist `null`, wenn die Domain im Markt keine
  organische Sichtbarkeit hat. Eine Reihe voller `null` ist ein Befund, kein
  fehlgeschlagener Abruf.
- **`tag` wird von allen sieben Live-Endpunkten gespiegelt.** Damit ist der
  offene Punkt aus Spec Abschnitt 19 beantwortet.

**Beim Erneuern:** dieselben Ziele verwenden, nie eine Kundendomain, und die
Kosten wieder festhalten.
