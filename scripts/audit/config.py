#!/usr/bin/env python3
"""Prüfung der reporting/config.json für einen Audit-Lauf (Spec Abschnitt 12).

`account_slug` und `drive_path` sind seit dieser Erweiterung Pflichtfelder:
ohne sie weiß der Lauf nicht, in welchen Kundenordner Screenshots und
Deliverables gehören, und legt sie mangels Ziel im Repo ab. Das verletzt
die PII-Regel aus Abschnitt 13, denn `reporting/` wird im Kunden-Repo
committet.

`validate()` ist die harte Schranke (fehlt ein Pflichtfeld oder ist ein Wert in
sich widersprüchlich, steht das im Ergebnis), `hints()` sind weiche
Empfehlungen, die den Lauf nie aufhalten. Ein Setup-Wizard zeigt beide Listen,
ein Lauf selbst bricht nur auf `validate()` ab. `validate()` wirft nie, auch
nicht, wenn die Config selbst kein Objekt ist: eine handgeschriebene
`config.json` kann auf oberster Ebene eine Liste oder eine Zeichenkette sein.
"""
import difflib
import os

from audit import run, tiers

#: Ohne diese sieben Felder kann kein Lauf starten (Spec Abschnitt 12).
REQUIRED_FIELDS = (
    "brand", "domain", "cwv_urls", "sources", "account_slug", "drive_path", "market",
)

#: Felder, die nur Pflicht sind, solange ihre Quelle an ist. Bis 11.09.2026
#: standen sie in REQUIRED_FIELDS, und ein Shop ohne GA4 ließ sich gar nicht
#: konfigurieren (Spec 2026-09-11, Abschnitt 7.1).
SOURCE_FIELDS = {"shopify": "shopify_store", "ga4": "ga4_property_id", "gsc": "gsc_site"}


def source_switched_off(config: dict, key: str) -> bool:
    """Ob eine eingestufte Quelle in der Config abgeschaltet ist.

    Ein fehlender Schlüssel unter `sources` heißt an, nur `false` schaltet ab.
    Eine Quelle mit mehreren Lauf-Quellen ist erst aus, wenn alle aus sind:
    `sources.shopify: false` allein lässt Katalog und Shop-Technik laufen, und
    beide brauchen `shopify_store`.
    """
    sources = config.get("sources")
    if not isinstance(sources, dict):
        return False
    return all(sources.get(rs) is False for rs in tiers.by_key(key).run_sources)

#: Konservativer Default für den DataForSEO-Budgetdeckel, in US-Dollar.
#: DataForSEO rechnet in Dollar (`cost` je Antwort), deshalb tut der Deckel
#: das auch: eine Umrechnung bräuchte einen Kurs, den niemand pflegt, und ein
#: Deckel in der falschen Währung greift um den Kurs zu spät. Der reale Wert ist
#: laut Spec Abschnitt 20 erst nach dem ersten Lauf bekannt.
BUDGET_DEFAULT = 10.0

#: Seitentypen, für die Crawl, Core Web Vitals und Screenshots je eine
#: Beispiel-URL brauchen (Spec Abschnitt 5 und 7).
PAGE_TYPES_DEFAULT = ("start", "collection", "product", "cart", "search", "blog")


def validate(config: dict) -> list[str]:
    """Prüft eine Config gegen die harten Regeln, wirft nie.

    Gibt eine Liste von Fehlermeldungen zurück, leer heißt: der Lauf kann
    starten. Ein kaputter Einzelwert (falscher Typ, negative Zahl) darf die
    Prüfung nicht abbrechen, sonst sieht der Wizard nur den ersten Fehler
    statt aller auf einmal. Das gilt auch für die Config als Ganzes: ist das
    Argument selbst kein Objekt (eine handgeschriebene JSON-Datei kann auf
    oberster Ebene eine Liste oder eine Zeichenkette sein), kommt genau eine
    Meldung zurück statt eines Absturzes.
    """
    if not isinstance(config, dict):
        return [
            f"Config ist kein Objekt (die JSON-Wurzel muss ein Objekt sein), "
            f"ist {type(config).__name__}"
        ]

    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in config:
            errors.append(f"Pflichtfeld fehlt: {field}")
            continue
        # Anwesenheit allein reicht nicht. Ein leerer String besteht die harte
        # Schranke, und der Lauf scheitert erst beim Pull, dort dann mit einer
        # Fehlermeldung der API statt mit dem echten Grund. Am 06.09.2026 im
        # ersten echten Lauf mit leerem gsc_site aufgefallen.
        value = config[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(
                f"Pflichtfeld leer: {field} (steht in der Config, hat aber "
                f"keinen Wert: {value!r})"
            )

    for key, field in SOURCE_FIELDS.items():
        if source_switched_off(config, key):
            continue
        if field not in config:
            errors.append(f"Pflichtfeld fehlt: {field} (die Quelle ist an; "
                          f"abschalten über sources, siehe /ptai-ecom:setup)")
            continue
        value = config[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Pflichtfeld leer: {field} (steht in der Config, hat aber "
                          f"keinen Wert: {value!r})")

    # Absolut, wie check_env.sh es verlangt: ein relativer Pfad, auch einer mit
    # Tilde, die keine Shell mehr auflöst, landete relativ zum Workspace und
    # damit im Kunden-Repo (Abschnitt 13). Leer oder fehlend meldet schon die
    # Schleife über REQUIRED_FIELDS.
    drive = config.get("drive_path")
    if isinstance(drive, str) and drive.strip() and not os.path.isabs(drive):
        errors.append(f"drive_path muss ein absoluter Pfad sein, ist {drive!r}. Den "
                      f"vollen Pfad zum Kundenordner eintragen, siehe /ptai-ecom:setup")

    budget = config.get("dfs_budget_usd")
    if budget is not None:
        try:
            if float(budget) < 0:
                errors.append(f"dfs_budget_usd darf nicht negativ sein: {budget!r}")
        except (TypeError, ValueError):
            errors.append(f"dfs_budget_usd ist keine Zahl: {budget!r}")
    if "dfs_budget_eur" in config:
        # Der alte Name aus Stufe 1. Nicht still ignorieren: der Lauf liefe
        # sonst mit dem Vorgabewert statt mit dem gesetzten Deckel weiter.
        errors.append(
            "dfs_budget_eur heißt jetzt dfs_budget_usd (DataForSEO rechnet in "
            "US-Dollar). Feld umbenennen, der Wert bleibt derselbe Zahlenwert."
        )

    market_block = config.get("market")
    if isinstance(market_block, dict):
        location = market_block.get("location_code")
        # isinstance(True, int) ist wahr. Ohne die bool-Prüfung ginge True
        # als Standortcode durch und die Abfrage schlüge erst nach der
        # Bezahlung fehl.
        if not isinstance(location, int) or isinstance(location, bool):
            errors.append(
                f"market.location_code muss der numerische DataForSEO-Standortcode "
                f"sein (Deutschland 2276, Österreich 2040, Schweiz 2756), ist "
                f"{location!r}"
            )
        language = market_block.get("language_code")
        if not isinstance(language, str) or not 2 <= len(language) <= 5:
            errors.append(
                f'market.language_code muss ein kurzer Sprachcode sein '
                f'("de", "en"), ist {language!r}'
            )
    elif market_block is not None:
        errors.append(f"market muss ein Objekt sein, ist {type(market_block).__name__}")

    cadences = config.get("cadences", {})
    if isinstance(cadences, dict):
        allowed_sources = list(run.SOURCE_CADENCE)
        for source, source_cadence in cadences.items():
            # Beide Seiten prüfen: ein vertippter Schlüssel (`dfs_ranking`
            # statt `dfs_rankings`) ist von "kein Eintrag" sonst nicht zu
            # unterscheiden. Die Quelle liefe still mit ihrer Voreinstellung
            # weiter, ohne dass die Konfiguration je gegriffen hätte.
            if source not in run.SOURCE_CADENCE:
                errors.append(_typo_error(
                    "cadences", "unbekannte Quelle", source, allowed_sources,
                ))
            if source_cadence not in run.SOURCE_CADENCES:
                errors.append(
                    f"cadences: unbekannte Kadenz {source_cadence!r} bei Quelle "
                    f"{source!r}, erlaubt sind: {', '.join(run.SOURCE_CADENCES)}"
                )
    else:
        errors.append(f"cadences muss ein Objekt sein, ist {type(cadences).__name__}")

    page_types_config = config.get("page_types", {})
    if isinstance(page_types_config, dict):
        for page_type in page_types_config:
            # Derselbe stille Fehler wie bei cadences: `produkte` statt
            # `product` bliebe für immer unkonfiguriert, ohne dass Crawl
            # oder Core-Web-Vitals-Abruf das je bemerken.
            if page_type not in PAGE_TYPES_DEFAULT:
                errors.append(_typo_error(
                    "page_types", "unbekannter Typ", page_type, PAGE_TYPES_DEFAULT,
                ))
    else:
        errors.append(
            f"page_types muss ein Objekt sein, ist {type(page_types_config).__name__}"
        )

    return errors


def _typo_error(field: str, phrase: str, value: str, allowed) -> str:
    """Baut eine Fehlermeldung für einen unbekannten Schlüssel samt Vorschlag.

    Der Verdacht "vermutlich vertippt" wird eingelöst statt nur behauptet:
    `difflib.get_close_matches` findet zu einem Tippfehler wie `dfs_ranking`
    den echten Namen `dfs_rankings`. Der Vorschlag steht vor der
    vollständigen Liste, die Liste selbst als Klartext statt als
    Python-Tupel. `phrase` kommt bereits grammatisch fertig von der
    Aufrufstelle ("unbekannte Quelle", "unbekannter Typ"), damit hier kein
    Behelf für die Endung nötig ist.
    """
    # Nur Text geht an difflib. Ein JSON-Schlüssel ist immer Text, aber
    # validate() verspricht "wirft nie", und das gilt auch für den Fall,
    # den nur ein Aufruf aus Code erzeugen kann.
    suggestion = difflib.get_close_matches(value, list(allowed), n=1) if isinstance(value, str) else []
    hint = f"meinst du {suggestion[0]!r}? " if suggestion else ""
    return (
        f"{field}: {phrase} {value!r}, vermutlich vertippt, "
        f"{hint}erlaubt sind: {', '.join(allowed)}"
    )


def compare_properties(config: dict) -> list[str]:
    """Weitere GA4-Properties, die derselbe Shop beliefert.

    Ein Shop kann denselben Kauf in mehrere Properties senden, etwa weil ein
    serverseitiges Werkzeug neben das clientseitige Tag getreten ist. Der
    Audit zieht genau eine Property; ohne diese Liste sieht er die andere nie,
    und jede Aussage ueber fehlende oder doppelte Kaeufe haengt daran, welche
    er zufaellig erwischt hat.

    Die Hauptproperty faellt raus, falls sie hier versehentlich noch einmal
    steht: sie doppelt gegen sich selbst zu vergleichen ergaebe nur Rauschen.
    """
    raw = config.get("ga4_compare_properties") or []
    if not isinstance(raw, list):
        return []
    haupt = str(config.get("ga4_property_id") or "").strip()
    return [str(p).strip() for p in raw
            if str(p).strip() and str(p).strip() != haupt]


def checkout_capture(config: dict) -> bool | None:
    """Ob der Kaufweg bis zur Zahlungsauswahl aufgenommen wird.

    **Ohne Vorgabewert, und das ist Absicht.** Die Aufnahme legt einen echten
    Testwarenkorb im Produktivshop an; daraus entsteht ein
    Abandoned-Checkout-Datensatz, auf den ein E-Mail-Werkzeug eine
    Warenkorbabbrecher-Strecke ausloesen kann. Ein stillschweigendes Ja
    entscheidet das fuer den Kunden, ein stillschweigendes Nein laesst eine
    Luecke im Report, die niemand bemerkt.

    `None` heisst deshalb: die Frage ist offen und gehoert ins Setup, nicht
    mitten in den Lauf. Am 08.09.2026 fehlte das Feld in einer Config, und der
    Audit fragte danach in Phase 1, mit einer Frage, die ohne Vorwissen ueber
    Klaviyo-Strecken nicht zu beantworten war.
    """
    value = config.get("checkout_capture")
    return value if isinstance(value, bool) else None


def hints(config: dict) -> list[str]:
    """Nicht blockierende Hinweise für den Setup-Wizard.

    Anders als `validate()` hält hier nichts den Lauf auf. Was hier steht, ist
    eine Entscheidung, die ein Mensch treffen muss und die kein Pull sich
    selbst beantworten kann.

    **Was hier bewusst nicht mehr steht: Wettbewerber und Keyword-Seeds.** Bis
    zum 08.09.2026 mahnte diese Funktion beide an, als wäre eine leere Liste
    ein halbfertiges Setup. Beide Felder wurden von genau einer Stelle gelesen,
    nämlich von diesem Hinweis. Kein Pull benutzt sie: `pull-dfs-competitors`
    sät mit den Kategorie-Begriffen aus `geo_queries` und findet die
    Wettbewerber über die Überschneidung in den Suchergebnissen,
    `pull-dfs-keywords` nimmt die Top-Anfragen aus der Search Console. Yves
    dazu: *"Die Wettbewerber sollen sich ja gezogen werden. Gibt ja gar keinen
    Grund, dass man das selbst hinzufügen müsste."* Ein Hinweis, der zu einer
    Arbeit auffordert, die niemand liest, macht ein fertiges Setup unfertig.
    """
    result: list[str] = []
    if checkout_capture(config) is None:
        result.append(
            "checkout_capture fehlt in der Config. Der Audit fragt sonst "
            "mitten im Lauf, ob er einen Testwarenkorb im Produktivshop "
            "anlegen darf. Die Entscheidung gehoert hierher, einmal je Kunde: "
            "true nimmt den Kaufweg bis zur Zahlungsauswahl auf, false laesst "
            "ihn aus und weist die Luecke im Report aus.")
    return result


def market(config: dict) -> tuple[int, str]:
    """Standort- und Sprachcode für die DataForSEO-Abfragen.

    Bewusst ohne Vorgabewert. Ein stillschweigendes "Deutschland" misst für
    einen Shop in Österreich oder der Schweiz den falschen Markt: die
    Rankings kommen zurück, sie sehen plausibel aus, und sie gehören zu einem
    anderen Land. Das ist genau die Fehlerklasse, gegen die dieses Repo
    gebaut ist, deshalb bricht der Zugriff hier ab statt zu raten.
    """
    block = config.get("market")
    if not isinstance(block, dict) or "location_code" not in block \
            or "language_code" not in block:
        raise ValueError(
            "market fehlt in der Config oder ist unvollständig. Ohne "
            "location_code und language_code misst jede DataForSEO-Abfrage "
            "einen Markt, den niemand gewählt hat. /ptai-ecom:setup trägt das "
            "Feld nach."
        )
    return block["location_code"], block["language_code"]


def budget_cap(config: dict) -> float:
    """Der Kostendeckel für DataForSEO-Abfragen je Lauf, in US-Dollar."""
    return float(config.get("dfs_budget_usd", BUDGET_DEFAULT))


#: Vorgabe fuer den Crawl-Umfang, wenn die Config nichts sagt. Bewusst
#: grosszuegig: ein zu kleiner Crawl faellt niemandem auf, weil der Snapshot
#: aussieht wie ein fertiger Crawl.
CRAWL_MAX_URLS_DEFAULT = 5000

#: Vorgabe fuer die Pause zwischen zwei Abrufen, Sekunden.
CRAWL_DELAY_DEFAULT = 0.3


def crawl_budget(config: dict) -> tuple[int, float]:
    """Wie weit der Crawl gehen darf und wie schnell, aus der Config.

    **Warum das ein Config-Feld ist und kein Prompt-Argument.** Der Umfang
    haengt am Shop, nicht am Lauf: wie viele URLs seine Sitemap fuehrt, wie
    viele davon Sprachdubletten sind, wie schnell er antwortet, ob eine
    Bot-Erkennung davorsitzt. Das ist jedes Mal dieselbe Antwort, und wer sie
    im Prompt mitgibt, gibt sie beim naechsten Lauf entweder wieder mit oder
    faellt still auf die Vorgabe zurueck. Am 08.09.2026 hat genau diese Luecke
    dazu gefuehrt, dass ein Mensch den Wert von Hand nachreichen musste,
    obwohl `crawl-site` das Feld seit jeher zu lesen behauptet hat.

    Rueckgabe ist immer ein Paar, nie None: ein Aufrufer soll den Crawl nicht
    versehentlich ungebremst starten, weil ein Feld fehlt.
    """
    max_urls = config.get("crawl_max_urls", CRAWL_MAX_URLS_DEFAULT)
    delay = config.get("crawl_delay_sec", CRAWL_DELAY_DEFAULT)
    try:
        max_urls = int(max_urls)
    except (TypeError, ValueError):
        max_urls = CRAWL_MAX_URLS_DEFAULT
    try:
        delay = float(delay)
    except (TypeError, ValueError):
        delay = CRAWL_DELAY_DEFAULT
    if max_urls < 1:
        max_urls = CRAWL_MAX_URLS_DEFAULT
    if delay < 0:
        delay = CRAWL_DELAY_DEFAULT
    return max_urls, delay


def page_types(config: dict) -> dict[str, str | None]:
    """Seitentyp zu Beispiel-URL, für Crawl, CWV und Screenshots.

    Jeder der sechs Standard-Seitentypen ist immer ein Schlüssel, auch ohne
    Override in der Config: ein Crawl, der einen Typ überspringt, weil er in
    `config["page_types"]` fehlt, würde ihn still nie prüfen.

    Garantiert wird nur der Schlüssel, nicht ein sichtbarer Umgang mit dem
    Wert `None`: ein nicht konfigurierter Seitentyp liefert `None`, keine
    URL. Wer `if not url: continue` schreibt, wirft den Vorteil weg, denn
    `None` ist genauso falsy wie ein fehlender Schlüssel. Ein Aufrufer muss
    explizit auf `is None` prüfen, um "kein Override" sichtbar zu behandeln.
    """
    result: dict[str, str | None] = {page_type: None for page_type in PAGE_TYPES_DEFAULT}
    result.update(config.get("page_types", {}))
    return result
