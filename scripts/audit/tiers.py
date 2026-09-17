#!/usr/bin/env python3
"""Einstufung der Quellen: Pflicht, Empfohlen, Optional.

Eine Stelle für die Frage, welche Quelle ein brauchbares Audit braucht.
`check_env.sh`, der Setup-Wizard, `reference/access.md` und Phase 0 des Audits
lesen von hier; keine dieser Stellen führt die Liste ein zweites Mal
(Spec "Betreiber-Setup und Einstufung der Quellen" vom 11.09.2026).

Die Stufe sagt, was dem Ergebnis ohne die Quelle fehlt, nicht, wie aufwendig
sie anzuschließen ist. Rechner-Voraussetzungen (Python, jq, Chrome) haben keine
Stufe: ohne sie läuft der betroffene Teil gar nicht.

CLI für die Shell, weil bash 3.2 keine assoziativen Arrays kennt:
  python3 -m audit.tiers
Je Quelle eine tabulatorgetrennte Zeile:
  key, tier, Stufen-Label, Label, provider, run_sources (Komma), without
"""
from dataclasses import dataclass

TIERS = ("required", "recommended", "optional")
TIER_LABELS = {"required": "Pflicht", "recommended": "Empfohlen", "optional": "Optional"}

#: Wer die Quelle stellt. "both": der Kunde gibt den Zugang, der Betreiber
#: braucht zusätzlich etwas Eigenes (CLI-Autorisierung, Entwicklertoken).
#: "both" heißt, der Betreiber braucht etwas Eigenes genau für diese Quelle;
#: das gemeinsame Google-Dienstkonto für GA4 und Search Console zählt nicht
#: dazu, check_env.sh führt es eigens.
PROVIDERS = ("customer", "operator", "both")


@dataclass(frozen=True)
class Source:
    key: str
    #: Stellt der Kunde die Quelle, steht genau dieses Label fett in Teil B
    #: von reference/access.md.
    label: str
    tier: str
    provider: str
    #: Schlüssel aus run.SOURCE_CADENCE, die an dieser Quelle hängen.
    run_sources: tuple[str, ...]
    #: Was ohne die Quelle fehlt, in Kundensprache: steht wörtlich im Check,
    #: im Wizard und in der Rückfrage vor dem Audit.
    without: str


SOURCES = (
    Source("shopify", "Shopify", "required", "both",
           ("shopify", "catalogue", "shop_tech"),
           "Handel, Katalog, Conversion und Messung"),
    Source("ga4", "Google Analytics 4", "required", "customer", ("ga4",),
           "Traffic, Conversion und Messung, dazu die Datenqualitäts-Analyse, "
           "die im Report vorne steht"),
    Source("gsc", "Google Search Console", "required", "customer", ("gsc",),
           "SEO Suche, dazu die Keyword-Liste für DataForSEO"),
    Source("dataforseo", "DataForSEO", "recommended", "operator",
           ("dfs_rankings", "competitors", "shopping", "dfs_keywords", "backlinks"),
           "SEO-Sichtbarkeit, Wettbewerb und Shopping-Präsenz"),
    Source("pagespeed", "PageSpeed-Key", "recommended", "operator", ("cwv", "cwv_lab"),
           "Core Web Vitals, der Block Technik bleibt leer"),
    Source("geo", "GEO-Keys", "recommended", "operator", ("geo",),
           "GEO-Sichtbarkeit per API. Es bleibt der Browser-Weg mit Login in jedem Lauf"),
    Source("ads", "Google Ads", "optional", "both", ("ads",),
           "SEA. Betrifft nur Shops mit Suchanzeigen, und das Token muss Google "
           "erst freigeben"),
)

#: Lauf-Quellen ohne Stufe, je mit Grund.
UNTIERED = {
    "crawl": "läuft ohne Zugang",
    "screens": "läuft ohne Zugang, braucht nur Chrome",
    "measures": "entsteht in Phase 3, kein Pull",
    "esp": "Pull noch nicht angebunden",
    "meta": "Pull noch nicht gebaut",
    "reviews": "Pull noch nicht gebaut",
}


def by_key(key: str) -> Source:
    """Die Quelle zu einem Schlüssel. Ein unbekannter Schlüssel ist ein Fehler."""
    for source in SOURCES:
        if source.key == key:
            return source
    raise KeyError(f"unbekannte Quelle: {key!r}")


def for_run_source(run_source: str) -> Source | None:
    """Die eingestufte Quelle, an der eine Lauf-Quelle hängt.

    None nur, wenn die Lauf-Quelle bewusst ohne Stufe geführt wird
    (`UNTIERED`). Für alles andere, also auch einen Tippfehler, wird ein
    KeyError geworfen: sonst läse ein verschriebener Schlüssel wie "gsc_typo"
    als "ohne Stufe" statt als Fehler.
    """
    for source in SOURCES:
        if run_source in source.run_sources:
            return source
    if run_source in UNTIERED:
        return None
    raise KeyError(f"unbekannte Lauf-Quelle: {run_source!r}")


def rows() -> list[str]:
    """Die CLI-Zeilen, eine je Quelle."""
    return ["\t".join((s.key, s.tier, TIER_LABELS[s.tier], s.label, s.provider,
                       ",".join(s.run_sources), s.without)) for s in SOURCES]


if __name__ == "__main__":
    print("\n".join(rows()))
