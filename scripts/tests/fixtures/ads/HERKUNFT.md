# Herkunft dieser Fixtures

**Von Hand gebaut, nicht aufgezeichnet.** Grundlage ist die REST-Referenz von
`customers.googleAds.search` und die Feldliste der Google Ads API, Stand
07.09.2026.

Der Grund: das Google-Ads-Entwicklertoken war zum Zeitpunkt des Baus nicht
beantragt, es gab also keinen einzigen echten Aufruf. Anders als bei den
DataForSEO-Pulls, deren Fixtures aus echten Produktiv-Antworten stammen, sind
diese Dateien nur so gut wie die Doku.

**Was sie beweisen und was nicht.** Sie beweisen, dass der Code die
dokumentierte Struktur richtig liest: Paginierung über `nextPageToken`,
Micros-Umrechnung, Monatsaggregation, die gewichtete Mittelung des Impression
Share. Sie beweisen **nicht**, dass die echte Antwort so aussieht.

**Nach Eintreffen des Tokens** sind sie durch aufgezeichnete Antworten zu
ersetzen, und die Verifikationsliste in `skills/pull-ads/SKILL.md` ist
abzuarbeiten. Erst danach darf eine Zahl aus diesem Pull in ein
Kundendokument.
