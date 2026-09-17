#!/usr/bin/env python3
"""GA4-Snapshot über die Analytics Data API (runReport).

Aufruf:
  ga4_pull.py --property <id> --creds <sa.json> --start YYYY-MM-DD --end YYYY-MM-DD --out <dir>
              [--compare-start YYYY-MM-DD --compare-end YYYY-MM-DD] [--pulse] [--audit-checks]
  ga4_pull.py --property <id> --creds <sa.json> --max-history --out <dir> [--end YYYY-MM-DD]
              [--audit-checks]
  ga4_pull.py --property <id> --creds <sa.json> --check

Schreibt <out>/ga4.json (bzw. ga4-pulse.json bei --pulse, ga4-max-history.json bei
--max-history) mit period, currency, channels, campaigns, devices, countries,
landing_pages, funnel und totals sowie optional site_search, comparison, notes und
(nur bei --max-history) history_from und by_month (Sessions, Umsatz und Käufe
je Monat und Kanal, die Monatsreihe der Baseline). --max-history ermittelt --start selbst: gemessen statt
angenommen, weil aggregierte Standarddimensionen oft weiter zurückreichen als die
GA4-Aufbewahrungseinstellung (siehe measure_history_start).
--audit-checks prüft vor jeder Rate auf Bot-Profile und auf einen zweiten
Absender je Mess-ID und schreibt bot_profiles, senders und primary_sender dazu
(siehe read_audit_checks).
Nur Stdlib plus google-auth (über den geteilten Token-Helfer), kein requests.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# Geteilte Helfer aus dem Plugin-Root (scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from api_common import describe_error  # noqa: E402
from audit import bots, senders  # noqa: E402
from google_token import get_access_token  # noqa: E402

API_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport"

# view_cart steht bewusst mit in der Liste: fehlt das Ereignis komplett, ist der
# Warenkorb ein Drawer ohne eigene Adresse und ein Schritt "Warenkorb angesehen"
# existiert in diesem Shop nicht. Das ist eine Aussage, kein Messfehler.
FUNNEL_EVENTS = ["view_item", "add_to_cart", "view_cart", "begin_checkout", "purchase"]

# Käufe zählt ausschließlich `ecommercePurchases`, nie `transactions`.
#
# **`transactions` zählt Refunds mit.** Laut GA4-Metadaten umfasst die Metrik
# die Ereignisse purchase, ecommerce_purchase, in_app_purchase, die
# App-Store-Abos und refund. Serverseitige Connectoren wie Littledata senden
# Refunds, und dann liegt die Metrik um die Erstattungen über den Käufen. Bis
# zum 11.09.2026 stand `transactions` in jedem Call, und ein echter Audit hat
# daraus eine Abweichung gegen Shopify gemacht, die es so nicht gab.
#
# `ecommercePurchases` zählt laut Metadaten nur purchase-Ereignisse. Am
# 11.09.2026 gegen zwei echte Properties nachgeprüft, jeder Monat über mehr
# als ein Jahr: der Wert war identisch mit eventCount unter
# eventName = purchase, auch in der Property mit Refunds. Ein Filter auf
# eventName ist hier keine Alternative, er schränkt jede Metrik im selben
# Call ein, also auch sessions und purchaseRevenue.
PURCHASE_METRIC = "ecommercePurchases"

# Metriken des Kanal-Calls. Die Käufe tragen die Conversion Rate je Kanal
# (Formel im Kennzahlen-Katalog, reference/metrics.md); lehnt eine Property
# die Metrik ab, greift der Fallback in run_channels().
# `engagedSessions` ist seit 08.09.2026 dabei. Ohne die Kennzahl je Kanal
# laesst sich automatisierter Traffic nicht von schwachem echtem Traffic
# unterscheiden: ein Kanal ohne Wiederkehrer und ohne Kaeufe kann eine
# schlechte Kampagne sein, ein Kanal ohne Wiederkehrer, ohne Kaeufe und ohne
# eine einzige Sitzung ueber zehn Sekunden nicht mehr. Siehe `audit/bots.py`.
#
# **`purchaseRevenue` ist Umsatz abzüglich Erstattungen, in der Währung der
# Property.** Am 11.09.2026 nachgerechnet: in jedem Monat gleich
# grossPurchaseRevenue minus refundAmount, auf den Cent. Eine Property ohne
# refund-Ereignisse liefert damit Bruttoumsatz, eine mit ihnen Nettoumsatz,
# und beide heißen gleich. Die Währung ist die Berichtswährung der Property,
# nicht die des Shops: dieselbe Prüfung fand eine Property in USD neben einem
# Shop in Euro. Deshalb steht `currency` im Snapshot.
CHANNEL_METRICS = ["sessions", "totalUsers", "purchaseRevenue", PURCHASE_METRIC,
                   "engagedSessions"]

# Metriken der einfachen Aufschlüsselungen (Kampagne, Gerät, Land): dieselben
# Basiszahlen wie beim Kanal-Call, ohne dessen Fallback.
# Die Käufe sind seit 07.09.2026 dabei. Ohne die Kennzahl lässt sich je
# Gerät, Kampagne und Land keine Conversion Rate bilden, und der Report hat
# im ersten echten Lauf für jedes Gerät "0,00 %" gedruckt, weil er die
# fehlende Zahl durch die Sessions geteilt hat.
BREAKDOWN_METRICS = ["sessions", "totalUsers", "purchaseRevenue", PURCHASE_METRIC]

# Metriken der Einstiegsseiten. Umsatz und Käufe gehören dazu, seit
# 07.09.2026: eine Einstiegsseite mit viel Traffic und wenig Umsatz ist ein
# anderer Fall als eine mit wenig Traffic und viel, und ohne diese beiden
# Kennzahlen lässt sich das nicht unterscheiden.
LANDING_METRICS = ["sessions", "engagementRate", "purchaseRevenue", PURCHASE_METRIC]

# Hinweis Pilot: exakter Dimension-Name landingPage vs. landingPagePlusQueryString
# wird im Pilot gegen die echte API validiert (Plan Task 4 Step 2).
LANDING_DIMENSION = "landingPage"

# Sicher vor jeder realistischen GA4-Property (frühestens App+Web-Beta 2019).
# Die eigentliche Grenze der Historie kommt nie aus diesem Datum, sondern
# ausschliesslich aus den Zeilen, die measure_history_start() zurückbekommt.
HISTORY_ANCHOR = "2015-08-14"

# Die Metriken der Profilabfragen in read_bot_profiles(). Engagement und Käufe
# entscheiden, ob ein Profil automatisiert ist; lehnt die Property die
# Kaufmetrik ab, gibt es kein Urteil und die Prüfung meldet den Grund.
PROFILE_METRICS = ["sessions", "engagedSessions", PURCHASE_METRIC]

# Die Dimension, an der ein Shopify-Connector seine Ereignisse kennzeichnet.
# Es gibt sie nur, wo die Property den Parameter registriert hat, siehe
# read_senders().
APP_NAME_DIMENSION = "customEvent:app_name"

# Die Artikelmetriken der Formatprüfung in read_senders(), GA4-Name zu dem
# Feldnamen, den `audit/senders.py` liest.
ITEM_METRICS = {"itemsViewed": "items_viewed", "itemsAddedToCart": "items_added_to_cart",
                "itemsCheckedOut": "items_checked_out", "itemsPurchased": "items_purchased"}


def _num(value):
    """GA4 liefert Metriken als Strings; nach int bzw. float wandeln."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return 0


def _iso(value: str) -> str:
    """Ein GA4-Datum (YYYYMMDD) als ISO-Datum."""
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def run_report(prop: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        API_URL.format(prop=prop),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        try:
            return json.load(resp)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ungültige JSON-Antwort der GA4-API: {exc}") from exc


def run_report_all(prop: str, token: str, body: dict) -> dict:
    """run_report über alle Seiten der Antwort.

    GA4 liefert höchstens `limit` Zeilen je Antwort und nennt die Gesamtzahl
    unter `rowCount`. Ohne Nachfassen fehlen die übrigen Zeilen still, und
    die Tagesreihen der Audit-Prüfungen reichen bei einem großen Shop über
    jedes Limit hinaus.
    """
    resp = run_report(prop, token, body)
    rows = list(resp.get("rows") or [])
    total = resp.get("rowCount", len(rows))
    while len(rows) < total:
        page = run_report(prop, token, dict(body, offset=len(rows)))
        new = page.get("rows") or []
        if not new:
            break
        rows.extend(new)
    resp["rows"] = rows
    return resp


def response_currency(resp: dict) -> str | None:
    """Die Berichtswährung der Property aus den Metadaten einer Antwort.

    Jede runReport-Antwort trägt sie unter metadata.currencyCode, auch ohne
    die Admin API. Jeder Umsatz der Property steht in dieser Währung, und die
    muss nicht die des Shops sein. None, wenn die Antwort sie nicht nennt.
    """
    return (resp.get("metadata") or {}).get("currencyCode")


def run_channels(prop: str, token: str, body: dict):
    """Kanal-Call mit genau einem Fallback ohne die Kaufmetrik.

    Lehnt eine Property den Metrik-Namen ab (HTTP 400), würde sonst der ganze
    GA4-Pull scheitern, obwohl die Käufe nur die Conversion Rate je Kanal
    tragen. Also einmal ohne sie nachfassen; die Kanäle tragen `purchases`
    dann null, nie 0, und der Grund landet als notes im Snapshot. Rückgabe:
    (Antwort, Note oder None).
    """
    try:
        return run_report(prop, token, body), None
    except urllib.error.HTTPError as exc:
        # Der Body eines HTTPError ist nur einmal lesbar: describe_error liest
        # ihn hier, deshalb darf die Exception danach nicht noch einmal dorthin.
        # Ein anderer Fehler wird als RuntimeError mit derselben Meldung weiter
        # nach oben gereicht.
        detail = describe_error(exc)
        if exc.code != 400 or PURCHASE_METRIC not in detail:
            raise RuntimeError(detail) from exc
    retry = {**body, "metrics": [m for m in body["metrics"]
                                 if m.get("name") != PURCHASE_METRIC]}
    return (run_report(prop, token, retry),
            f"Metrik {PURCHASE_METRIC} von der Property abgelehnt: {detail}")


def run_site_search(prop: str, token: str, body: dict):
    """Interne Suchbegriffe: customEvent:search_term ist eine optionale, im
    Property manuell registrierte Custom Dimension (Enhanced-Measurement-
    Ereignis view_search_results, Parameter search_term). Fehlt die
    Registrierung, lehnt die API die Dimension mit HTTP 400 ab; das ist eine
    fehlende Konfiguration in der Property, kein Fehler des Pulls, deshalb nie
    fatal. Rückgabe: (Buckets aus parse_rows, oder None) und (Hinweis oder None).
    """
    try:
        resp = run_report(prop, token, body)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        return None, f"interne Suchbegriffe nicht verfügbar: {describe_error(exc)}"
    return parse_rows(resp), None


def parse_rows(resp: dict) -> dict:
    """Zeilen der Antwort nach dateRange aufteilen.

    Bei zwei dateRanges hängt die API automatisch eine dateRange-Dimension an
    (Werte date_range_0 und date_range_1); ihre Position wird über den Header
    bestimmt, nicht angenommen. Rückgabe: {"date_range_0": [(dims, metrics)], ...}
    """
    dim_headers = [h.get("name") for h in resp.get("dimensionHeaders", [])]
    met_headers = [h.get("name") for h in resp.get("metricHeaders", [])]
    dr_idx = dim_headers.index("dateRange") if "dateRange" in dim_headers else None

    buckets = {"date_range_0": []}
    for row in resp.get("rows", []):
        dim_values = [v.get("value") for v in row.get("dimensionValues", [])]
        met_values = [v.get("value") for v in row.get("metricValues", [])]
        if dr_idx is None:
            key, dims = "date_range_0", dim_values
        else:
            key = dim_values[dr_idx]
            dims = [v for i, v in enumerate(dim_values) if i != dr_idx]
        metrics = {name: _num(val) for name, val in zip(met_headers, met_values)}
        buckets.setdefault(key, []).append((dims, metrics))
    return buckets


def parse_totals(resp: dict) -> dict:
    """Die von der API gerechnete Gesamtzeile je dateRange.

    `metricAggregations: ["TOTAL"]` lässt GA4 die Summe selbst bilden. Das ist
    nicht dasselbe wie eine Summe über die Kanalzeilen: nutzerbezogene
    Metriken werden je Dimensionskombination entdoppelt, `totalUsers` über
    Kanäle aufzuaddieren zählt deshalb jeden Menschen mehrfach, der über mehr
    als einen Kanal kam. Rückgabe wie parse_rows: {"date_range_0": {...}}.
    """
    dim_headers = [h.get("name") for h in resp.get("dimensionHeaders", [])]
    met_headers = [h.get("name") for h in resp.get("metricHeaders", [])]
    dr_idx = dim_headers.index("dateRange") if "dateRange" in dim_headers else None

    buckets = {}
    for row in resp.get("totals", []):
        dim_values = [v.get("value") for v in row.get("dimensionValues", [])]
        key = (dim_values[dr_idx]
               if dr_idx is not None and dr_idx < len(dim_values) else "date_range_0")
        met_values = [v.get("value") for v in row.get("metricValues", [])]
        buckets[key] = {name: _num(val) for name, val in zip(met_headers, met_values)}
    return buckets


def build_breakdown(rows: list, key_name: str) -> list:
    """Aufschlüsselung nach Gerät, Kampagne oder Land.

    `purchases` ist seit 07.09.2026 dabei, damit sich je Zeile eine
    Conversion Rate bilden lässt (bis 11.09.2026 als `transactions` und mit
    Refunds, siehe PURCHASE_METRIC). Fehlt die Kennzahl in der Antwort, steht
    `None` und nicht 0: der Report zeigt dann "nicht messbar" statt einer
    Conversion Rate von 0,00 Prozent neben fünf Millionen Euro Umsatz.
    """
    items = [
        {
            key_name: dims[0] if dims else "(not set)",
            "sessions": metrics.get("sessions", 0),
            "total_users": metrics.get("totalUsers", 0),
            "purchase_revenue": round(float(metrics.get("purchaseRevenue", 0)), 2),
            "purchases": (_num(metrics[PURCHASE_METRIC])
                          if PURCHASE_METRIC in metrics else None),
        }
        for dims, metrics in rows
    ]
    items.sort(key=lambda i: i["sessions"], reverse=True)
    return items


def build_by_month(rows: list) -> list:
    """Monatsreihe aus (yearMonth, Kanal)-Zeilen, chronologisch sortiert.

    Die Baseline braucht Sessions je Monat und Kanal (Spec Abschnitt 10). Der
    übrige Pull aggregiert über den ganzen Zeitraum zu einer Summe, deshalb
    diese eigene Reihe. Feldname `by_month` wie im Shopify-Snapshot, damit die
    Baseline beide Quellen gleich liest.

    **Die Monatssumme trägt bewusst keine Nutzerzahl.** Sessions, Umsatz und
    Käufe sind sitzungs- oder ereignisbezogen und addieren sich über
    Kanäle. `totalUsers` tut das nicht: GA4 entdoppelt Nutzer je
    Dimensionskombination, wer im selben Monat über Organic und über E-Mail
    kommt, steht in beiden Zeilen. Eine Summe wäre größer als die tatsächliche
    Nutzerzahl. Je Kanal ist die Zahl richtig und steht deshalb dort.
    """
    months: dict[str, list] = {}
    for dims, metrics in rows:
        year_month = dims[0] if dims else ""
        channel = dims[1] if len(dims) > 1 else "(not set)"
        months.setdefault(year_month, []).append({
            "channel": channel,
            "sessions": metrics.get("sessions", 0),
            "total_users": metrics.get("totalUsers", 0),
            "purchase_revenue": round(float(metrics.get("purchaseRevenue", 0)), 2),
            # Ohne Default, gleiche Regel wie in build_block: hat der Fallback
            # die Kaufmetrik aus dem Call genommen, steht hier null (unbekannt)
            # statt 0 (kein Kauf).
            "purchases": metrics.get(PURCHASE_METRIC),
        })

    series = []
    for year_month in sorted(months):
        channels = sorted(months[year_month], key=lambda c: c["sessions"], reverse=True)
        measured = [c["purchases"] for c in channels if c["purchases"] is not None]
        series.append({
            "month": f"{year_month[0:4]}-{year_month[4:6]}",
            "sessions": sum(c["sessions"] for c in channels),
            "purchase_revenue": round(sum(c["purchase_revenue"] for c in channels), 2),
            "purchases": sum(measured) if measured else None,
            "channels": channels,
        })
    return series


def build_site_search(rows: list) -> list:
    """Interne Suchbegriffe nach demselben events/sessions-Muster wie der
    Funnel: events ist, wie oft gesucht wurde, sessions, in wie vielen
    Besuchen. Sortiert nach events, nicht nach sessions: derselbe Begriff kann
    in einer Session mehrfach gesucht werden."""
    items = [
        {
            "search_term": dims[0] if dims else "(not set)",
            "events": metrics.get("eventCount", 0),
            "sessions": metrics.get("sessions", 0),
        }
        for dims, metrics in rows
    ]
    items.sort(key=lambda i: i["events"], reverse=True)
    return items


def build_block(period: dict, channel_rows: list, landing_rows: list, funnel_rows: list,
                campaign_rows: list, device_rows: list, country_rows: list,
                site_search_rows: list | None = None,
                channel_totals: dict | None = None) -> dict:
    """Einen Snapshot-Block (Hauptteil oder comparison) aus den Zeilen bauen.

    `channel_totals` ist die von der API gerechnete Gesamtzeile des Kanal-Calls
    (siehe parse_totals) und die einzige richtige Quelle für die Nutzerzahl."""
    channels = [
        {
            "channel": dims[0] if dims else "(not set)",
            "sessions": metrics.get("sessions", 0),
            "total_users": metrics.get("totalUsers", 0),
            "purchase_revenue": round(float(metrics.get("purchaseRevenue", 0)), 2),
            # Ohne Default: hat der Fallback die Kaufmetrik aus dem Call
            # genommen, steht hier null (unbekannt) statt 0 (kein Kauf).
            "purchases": metrics.get(PURCHASE_METRIC),
            # Dieselbe Regel: null heisst nicht abgefragt, nie null Sitzungen.
            "engaged_sessions": metrics.get("engagedSessions"),
        }
        for dims, metrics in channel_rows
    ]
    channels.sort(key=lambda c: c["sessions"], reverse=True)

    # Sessions und Umsatz sind sitzungs- beziehungsweise ereignisbezogen und
    # addieren sich über Kanäle korrekt. Die Nutzerzahl tut das nicht, GA4
    # entdoppelt sie je Dimensionskombination. Sie kommt deshalb ausschließlich
    # aus der Gesamtzeile der API; fehlt die, steht null (unbekannt) statt
    # einer zu hohen Summe. Eine fehlende Zahl fällt auf, eine um Prozente zu
    # hohe nicht.
    if channel_totals:
        totals = {
            "sessions": channel_totals.get("sessions", 0),
            "total_users": channel_totals.get("totalUsers"),
            "purchase_revenue": round(float(channel_totals.get("purchaseRevenue", 0)), 2),
        }
    else:
        totals = {
            "sessions": sum(c["sessions"] for c in channels),
            "total_users": None,
            "purchase_revenue": round(sum(c["purchase_revenue"] for c in channels), 2),
        }

    landing_pages = [
        {
            "landing_page": dims[0] if dims else "(not set)",
            "sessions": metrics.get("sessions", 0),
            "engagement_rate": round(float(metrics.get("engagementRate", 0)), 4),
            # `None` statt 0, wenn die API die Kennzahl nicht mitgeliefert hat:
            # eine fehlende Zahl fällt auf, eine Null liest sich als Messung.
            "purchase_revenue": (round(float(metrics["purchaseRevenue"]), 2)
                                 if "purchaseRevenue" in metrics else None),
            "purchases": (_num(metrics[PURCHASE_METRIC])
                          if PURCHASE_METRIC in metrics else None),
        }
        for dims, metrics in landing_rows
    ]
    landing_pages.sort(key=lambda p: p["sessions"], reverse=True)

    # Je Ereignis zwei Zahlen: events (wie oft ausgelöst) und sessions (in wie
    # vielen Besuchen). Für jede Quote im Report zählt sessions, nie events:
    # eine Person sieht mehrere Produkte an, im Pilotmonat standen 457
    # view_item-Ereignisse für 273 Sessions. Siehe reference/kennzahlen.md,
    # Abschnitt Funnel.
    funnel = {"sessions": totals["sessions"]}
    funnel.update({event: {"events": 0, "sessions": 0} for event in FUNNEL_EVENTS})
    for dims, metrics in funnel_rows:
        if dims and dims[0] in FUNNEL_EVENTS:
            funnel[dims[0]] = {
                "events": metrics.get("eventCount", 0),
                "sessions": metrics.get("sessions", 0),
            }

    block = {
        "period": period,
        "channels": channels,
        "campaigns": build_breakdown(campaign_rows, "campaign"),
        "devices": build_breakdown(device_rows, "device"),
        "countries": build_breakdown(country_rows, "country"),
        "landing_pages": landing_pages,
        "funnel": funnel,
        "totals": totals,
    }
    if site_search_rows is not None:
        block["site_search"] = build_site_search(site_search_rows)
    return block


# Feldnamen, die eine bot_filter-Regel ansprechen darf. Bewusst eng gehalten:
# es sind die Session-Dimensionen, an denen sich automatisierter Traffic
# zuverlässig festmachen lässt, ohne echte Besuche mitzunehmen.
# `screen_resolution_in` ist seit 13.09.2026 dabei: die Bildschirmauflösung
# trägt zusammen mit Betriebssystem, Gerät und Browser das Geräteprofil, auf
# das `audit/bots.py` den Filter vorschlägt, statt auf einen ganzen Kanal.
FILTER_FIELDS = {
    "country_in": ("country", False),
    "country_not_in": ("country", True),
    "channel_in": ("sessionDefaultChannelGroup", False),
    "channel_not_in": ("sessionDefaultChannelGroup", True),
    "device_in": ("deviceCategory", False),
    "source_in": ("sessionSource", False),
    "operating_system_in": ("operatingSystem", False),
    "browser_in": ("browser", False),
    "screen_resolution_in": ("screenResolution", False),
}


def rule_expression(rule: dict):
    """Eine bot_filter-Regel als GA4-Ausdruck, der die beschriebenen
    Sessions trifft: die UND-Verknüpfung ihrer Bedingungen. None, wenn die
    Regel keine verwertbare Bedingung trägt."""
    conditions = []
    for key, values in rule.items():
        field = FILTER_FIELDS.get(key)
        if not field or not values:
            continue
        field_name, negate = field
        expr = {"filter": {"fieldName": field_name,
                           "inListFilter": {"values": list(values)}}}
        conditions.append({"notExpression": expr} if negate else expr)
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"andGroup": {"expressions": conditions}}


def build_exclusion_filter(spec: dict):
    """Aus einem bot_filter-Block einen GA4-dimensionFilter bauen, der die
    beschriebenen Sessions ausschliesst.

    Jede Regel unter "exclude" ist eine UND-Verknüpfung ihrer Bedingungen,
    die Regeln untereinander sind ODER-verknüpft, und das Ganze wird negiert.
    Eine Regel ohne verwertbare Bedingung wird übersprungen, statt still
    alles oder nichts zu filtern.

    Gibt (filter, angewandte_regeln) zurück; filter ist None, wenn nichts greift.
    """
    if not spec or not spec.get("enabled"):
        return None, []

    rules, applied = [], []
    for rule in spec.get("exclude", []):
        expr = rule_expression(rule)
        if expr is None:
            continue
        rules.append(expr)
        applied.append(rule.get("reason", "ohne Begründung"))

    if not rules:
        return None, []
    matched = rules[0] if len(rules) == 1 else {"orGroup": {"expressions": rules}}
    return {"notExpression": matched}, applied


def merge_filters(base, extra):
    """Zwei dimensionFilter mit UND verbinden; None-Seiten fallen weg."""
    if not extra:
        return base
    if not base:
        return extra
    return {"andGroup": {"expressions": [base, extra]}}


def landing_body(date_range: dict, bot_filter) -> dict:
    """Query-Body der Einstiegsseiten, immer für genau einen Zeitraum.

    Im Vergleichsmodus laufen die Einstiegsseiten als zwei getrennte Calls,
    weil Limit und Sortierung bei zwei Ranges über beide Zeiträume gemeinsam
    gehen: ein starker Zeitraum verdrängt sonst still die Top-20 des anderen.
    """
    return {
        "dateRanges": [date_range],
        "dimensions": [{"name": LANDING_DIMENSION}],
        "metrics": [{"name": name} for name in LANDING_METRICS],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 20,
        **({"dimensionFilter": bot_filter} if bot_filter else {}),
    }


def block_bodies(date_ranges: list, bot_filter) -> dict:
    """Die Abfragen eines Snapshot-Blocks, eine je Sicht.

    Kanäle, Kampagnen, Geräte, Länder und Funnel laufen mit allen dateRanges
    in einem Call, die Einstiegsseiten nur für den ersten (siehe
    landing_body). Jeder Body trägt den Filter, der Funnel zusätzlich den auf
    seine Ereignisse. Der Hauptteil und `bot_profiles.without` entstehen aus
    genau diesen Bodies und unterscheiden sich nur im Filter.
    """
    extra = {"dimensionFilter": bot_filter} if bot_filter else {}

    def breakdown(dimension: str, limit: int) -> dict:
        """Query-Body für eine einfache Session-Aufschlüsselung (Kampagne,
        Gerät, Land): dieselben Basiszahlen wie channels, mit beiden
        dateRanges in einem Call wie Kanäle und Funnel."""
        return {
            "dateRanges": date_ranges,
            "dimensions": [{"name": dimension}],
            "metrics": [{"name": name} for name in BREAKDOWN_METRICS],
            "limit": limit,
            **extra,
        }

    return {
        "channels": {
            "dateRanges": date_ranges,
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": name} for name in CHANNEL_METRICS],
            # Lässt GA4 die Gesamtzeile selbst rechnen. Ohne sie müsste der
            # Pull über die Kanäle summieren, und die Nutzerzahl wäre dann zu
            # hoch (siehe parse_totals).
            "metricAggregations": ["TOTAL"],
            **extra,
        },
        "campaigns": breakdown("sessionCampaignName", 25),
        "devices": breakdown("deviceCategory", 10),
        "countries": breakdown("country", 50),
        "landing_pages": landing_body(date_ranges[0], bot_filter),
        "funnel": {
            "dateRanges": date_ranges,
            "dimensions": [{"name": "eventName"}],
            "metrics": [{"name": "eventCount"}, {"name": "sessions"}],
            "dimensionFilter": merge_filters(
                {"filter": {"fieldName": "eventName",
                            "inListFilter": {"values": FUNNEL_EVENTS}}},
                bot_filter,
            ),
        },
    }


def read_block(prop: str, token: str, period: dict, date_range: dict, bot_filter) -> dict:
    """Ein Snapshot-Block über einen Zeitraum, gebaut wie der Hauptteil, aber
    mit eigenem Filter. Kein interner Suchbegriff und kein Vergleich: der Block
    trägt die Sichten, aus denen die Analysen Raten rechnen."""
    results, channel_totals, purchases_note = {}, {}, None
    for name, body in block_bodies([date_range], bot_filter).items():
        if name == "channels":
            resp, purchases_note = run_channels(prop, token, body)
            channel_totals = parse_totals(resp)
        else:
            resp = run_report(prop, token, body)
        results[name] = parse_rows(resp).get("date_range_0", [])
    block = build_block(period, results["channels"], results["landing_pages"],
                        results["funnel"], results["campaigns"], results["devices"],
                        results["countries"], channel_totals=channel_totals.get("date_range_0"))
    if purchases_note:
        block["notes"] = {"purchases": purchases_note}
    return block


def measure_history_start(prop: str, token: str, end_date: str) -> str:
    """Ermittelt das früheste Datum, für das diese Property tatsächlich Zeilen
    liefert.

    Die GA4-Aufbewahrungseinstellung (2 oder 14 Monate) betrifft vor allem
    nutzer- und ereignisbezogene Abfragen; aggregierte Standarddimensionen wie
    hier reichen oft weiter zurück, und das unterscheidet sich je Property. Die
    Grenze wird deshalb an dieser Property gemessen statt angenommen: ein
    einziger Call über einen sehr weiten Zeitraum ab HISTORY_ANCHOR, GA4 lässt
    Tage ohne Daten in der Antwort automatisch weg (keepEmptyRows ist per
    Default aus). Ungefiltert, damit ein kundenspezifischer Bot-Filter die
    Messung nicht verzerrt. Liefert die Property gar keine Zeile (brandneu),
    gilt end_date selbst als frühestes Datum.
    """
    body = {
        "dateRanges": [{"startDate": HISTORY_ANCHOR, "endDate": end_date}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "sessions"}],
        "limit": 100000,
    }
    resp = run_report(prop, token, body)
    dates = [row["dimensionValues"][0]["value"] for row in resp.get("rows", [])]
    if not dates:
        return end_date
    earliest = min(dates)
    return f"{earliest[0:4]}-{earliest[4:6]}-{earliest[6:8]}"


def read_compare(props: list[str], token: str, start: str, end: str) -> list:
    """Monatsreihe je weiterer Property, nur Sitzungen, Kaeufe und Umsatz.

    **Warum das gebraucht wird.** Ein Shop kann denselben Kauf in mehrere
    GA4-Properties senden, etwa weil ein serverseitiges Werkzeug wie
    Littledata neben das clientseitige Tag getreten ist. Der Audit zieht genau
    eine Property, und ohne den Vergleich sieht er die andere nie.

    Am 07.09.2026 hat genau das einen falschen Befund erzeugt: die gezogene
    Property meldete vier Monate ohne einen einzigen Kauf, und der Report
    schrieb "die Kaufmessung ist ausgefallen". Die Bestellungen standen die
    ganze Zeit in der zweiten Property. Die stand dort ausserdem um den Faktor
    zwei ueber Shopify, und **das** war der eigentliche Befund: wer auf ihr
    optimiert, rechnet mit dem doppelten Umsatz.

    Die Abfrage ist billig, eine je Property, und beantwortet die einzige
    Frage, die zaehlt: welche Property stimmt mit dem Shop ueberein.

    **Käufe, nie Transaktionen, und Umsatz mit Währung.** Bis zum 11.09.2026
    stand hier `transactions`, und darin zählt GA4 Refunds mit (siehe
    PURCHASE_METRIC). Der Umsatz ist nach Erstattungen gerechnet und steht in
    der Berichtswährung der Property, deshalb trägt jeder Block `currency`.
    """
    out = []
    for prop in props:
        block = {"property_id": prop, "currency": None, "by_month": [], "note": None}
        try:
            resp = run_report(prop, token, {
                "dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": "yearMonth"}],
                "metrics": [{"name": "sessions"}, {"name": PURCHASE_METRIC},
                            {"name": "purchaseRevenue"}],
                "orderBys": [{"dimension": {"dimensionName": "yearMonth"}}],
                "limit": 10000,
            })
            block["currency"] = response_currency(resp)
            # Über die Header-Namen statt über die Position: wer die
            # Metrikliste umstellt, vertauscht sonst still zwei Spalten.
            for dims, metrics in parse_rows(resp)["date_range_0"]:
                raw = dims[0] if dims else ""
                block["by_month"].append({
                    "month": f"{raw[:4]}-{raw[4:6]}" if len(raw) == 6 else raw,
                    "sessions": metrics.get("sessions", 0),
                    "purchases": metrics.get(PURCHASE_METRIC, 0),
                    "purchase_revenue": round(float(metrics.get("purchaseRevenue", 0)), 2),
                })
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            block["note"] = (f"Property {prop} nicht abrufbar: "
                             f"{describe_error(exc)}")
        out.append(block)
    return out


def parse_streams(payload: dict) -> list:
    """Stream-ID und Mess-ID je Datenstream aus der Antwort der Admin API.

    Die Data API führt Ereignisse unter `streamId`, der Quelltext eines Shops
    unter der Mess-ID (`G-...`). Erst diese Zuordnung sagt, welche Mess-ID
    einen zweiten Absender hat."""
    return [{"stream_id": (st.get("name") or "").rsplit("/", 1)[-1] or None,
             "measurement_id": (st.get("webStreamData") or {}).get("measurementId")}
            for st in payload.get("dataStreams", [])]


def read_streams(prop: str, token: str):
    """Name und Mess-IDs der Property, aus der Admin-API.

    Der Grund steht in einem echten Fall vom 07.09.2026: der Shop lud zwei
    GA4-Mess-IDs auf jeder Seite, der Audit zog eine Property, und niemand
    konnte sagen, ob es die war, in der die Bestellungen ankommen. Genau
    daran hing der schwerste Befund des ganzen Reports. Mit den Mess-IDs der
    gezogenen Property laesst sich das gegen die im Quelltext gefundenen IDs
    halten, statt es zu vermuten.

    Braucht die Google Analytics Admin API im Cloud-Projekt. Fehlt sie, ist
    das kein Fehlschlag des Pulls: der Snapshot traegt dann den Grund, und
    der Report weist die Frage als offen aus.
    """
    base = "https://analyticsadmin.googleapis.com/v1beta"
    out = {"property_id": prop, "display_name": None, "measurement_ids": [],
           "streams": [], "note": None}
    try:
        req = urllib.request.Request(f"{base}/properties/{prop}",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as f:
            out["display_name"] = json.load(f).get("displayName")
        req = urllib.request.Request(f"{base}/properties/{prop}/dataStreams?pageSize=50",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as f:
            out["streams"] = parse_streams(json.load(f))
        out["measurement_ids"] = [s["measurement_id"] for s in out["streams"]
                                  if s["measurement_id"]]
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        out["note"] = ("Mess-IDs der Property nicht abrufbar: "
                       f"{describe_error(exc)}. Die Google Analytics Admin API "
                       "muss im Cloud-Projekt aktiviert sein.")
    return out


def profile_filter(profile: dict):
    """Der dimensionFilter, der genau die Sitzungen eines Geräteprofils trifft."""
    return rule_expression(bots.profile_rule(profile, ""))


def read_bot_profiles(prop: str, token: str, date_range: dict, total_sessions: int,
                      base_filter=None) -> dict:
    """Geräteprofile finden, die wie automatisierter Zugriff aussehen.

    Drei Schritte, die Regeln dahinter stehen in `audit/bots.py`: Sitzungen je
    Tag; Sitzungen, Engagement und Käufe je Tag und Profil ab der
    Tagesschwelle; dann je Kandidat eine Nachzählung über den ganzen Zeitraum
    ohne Schwelle, nach Kanal aufgeteilt. `total_sessions` ist die
    Gesamtzeile des Hauptteils, damit der Anteil gegen dieselbe Zahl steht wie
    jede andere Rate im Snapshot. `base_filter` ist der Bot-Filter aus der
    Config, falls einer gilt.

    Scheitert eine Abfrage, steht der Grund unter `note`, die Profilliste
    bleibt leer und `flagged` falsch: eine Prüfung, die nicht lief, meldet
    keinen Befund, und der Snapshot sagt, dass sie nicht lief.
    """
    section = {"period": {"start": date_range["startDate"], "end": date_range["endDate"]},
               "dimensions": list(bots.PROFILE_DIMENSIONS), "daily_floor": None,
               "profiles": [], "flagged": False, "filter_proposal": None, "note": None}
    extra = {"dimensionFilter": base_filter} if base_filter else {}
    try:
        daily = run_report_all(prop, token, {
            "dateRanges": [date_range],
            "dimensions": [{"name": "date"}],
            "metrics": [{"name": "sessions"}],
            "limit": 100000,
            **extra,
        })
        daily_totals = {_iso(dims[0]): metrics.get("sessions", 0)
                        for dims, metrics in parse_rows(daily)["date_range_0"]}
        floor = bots.daily_floor(sum(daily_totals.values()), len(daily_totals))
        section["daily_floor"] = floor
        resp = run_report_all(prop, token, {
            "dateRanges": [date_range],
            "dimensions": [{"name": "date"}] + [{"name": d} for d in bots.PROFILE_DIMENSIONS],
            "metrics": [{"name": name} for name in PROFILE_METRICS],
            "metricFilter": {"filter": {"fieldName": "sessions", "numericFilter": {
                "operation": "GREATER_THAN_OR_EQUAL", "value": {"int64Value": str(floor)}}}},
            "limit": 250000,
            **extra,
        })
        if (resp.get("metadata") or {}).get("dataLossFromOtherRow"):
            section["note"] = ("GA4 hat seltene Profile in einer (other)-Zeile gebündelt. "
                               "Kleine Profile fehlen in der Prüfung, die großen nicht.")
        rows = [{"date": _iso(dims[0]),
                 "profile": dict(zip(bots.PROFILE_DIMENSIONS, dims[1:])),
                 "sessions": metrics.get("sessions", 0),
                 "engaged_sessions": metrics.get("engagedSessions"),
                 "purchases": metrics.get(PURCHASE_METRIC)}
                for dims, metrics in parse_rows(resp)["date_range_0"]]

        for candidate in bots.profile_candidates(rows, total_sessions):
            counted = run_report(prop, token, {
                "dateRanges": [date_range],
                "dimensions": [{"name": "sessionDefaultChannelGroup"}],
                "metrics": [{"name": name} for name in PROFILE_METRICS + ["totalUsers"]],
                "metricAggregations": ["TOTAL"],
                "dimensionFilter": merge_filters(profile_filter(candidate["profile"]),
                                                 base_filter),
                "limit": 50,
            })
            totals = parse_totals(counted).get("date_range_0", {})
            channels = sorted(
                ({"channel": dims[0] if dims else "(not set)",
                  "sessions": metrics.get("sessions", 0),
                  "engaged_sessions": metrics.get("engagedSessions"),
                  "purchases": metrics.get(PURCHASE_METRIC)}
                 for dims, metrics in parse_rows(counted)["date_range_0"]),
                key=lambda c: c["sessions"], reverse=True)
            section["profiles"].append(bots.assess_profile(
                candidate["profile"],
                {"sessions": totals.get("sessions", 0),
                 "engaged_sessions": totals.get("engagedSessions"),
                 "purchases": totals.get(PURCHASE_METRIC),
                 "total_users": totals.get("totalUsers")},
                total_sessions, channels=channels,
                windows=bots.wave_windows(daily_totals, candidate["days"])))
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        section["note"] = f"Bot-Profile nicht geprüft: {describe_error(exc)}"
        section["profiles"] = []
        section["checked"] = False
    else:
        # `checked` unterscheidet "geprüft, nichts gefunden" von "nicht
        # geprüft". Beides hat eine leere Profilliste, und nur das erste ist
        # eine Entwarnung.
        section["checked"] = True
    section["flagged"] = any(p["flagged"] for p in section["profiles"])
    section["filter_proposal"] = bots.filter_proposal(section)
    return section


def read_senders(prop: str, token: str, date_range: dict, base_filter=None,
                 streams: list | None = None) -> dict:
    """Mehrere Absender je Mess-ID, die Regeln dahinter in `audit/senders.py`.

    Drei Abfragen: Ereignisse und Sitzungen je Tag, Stream und Ereignis; das
    Gleiche zusätzlich nach `customEvent:app_name` und `hostName`; die
    Artikel-IDs mit ihren Artikelmetriken. `base_filter` schließt die
    auffälligen Bot-Profile aus, wo welche erkannt sind (siehe
    read_audit_checks). `streams` aus read_streams() ordnet jedem Stream
    seine Mess-ID zu.

    **Ohne registriertes `app_name` fällt die Abfrage einmal zurück** auf
    `hostName` allein, der Grund steht unter `notes`. Scheitert sonst etwas,
    ist die Prüfung `measurable: false` mit dem Grund unter `note`.
    """
    event_filter = merge_filters(
        {"filter": {"fieldName": "eventName",
                    "inListFilter": {"values": list(senders.SENDER_EVENTS)}}},
        base_filter)
    period = {"start": date_range["startDate"], "end": date_range["endDate"]}
    notes = []

    def event_body(dims: list) -> dict:
        return {"dateRanges": [date_range], "dimensions": [{"name": d} for d in dims],
                "metrics": [{"name": "eventCount"}, {"name": "sessions"}],
                "dimensionFilter": event_filter, "limit": 250000}

    try:
        totals = run_report_all(prop, token, event_body(["date", "streamId", "eventName"]))
        event_rows = [{"date": _iso(dims[0]), "stream_id": dims[1], "event": dims[2],
                       "events": metrics.get("eventCount", 0),
                       "sessions": metrics.get("sessions", 0)}
                      for dims, metrics in parse_rows(totals)["date_range_0"]]

        dims = ["date", "streamId", "eventName", APP_NAME_DIMENSION, "hostName"]
        try:
            found = run_report_all(prop, token, event_body(dims))
        except urllib.error.HTTPError as exc:
            # Wie in run_channels: der Body ist nur einmal lesbar.
            detail = describe_error(exc)
            if exc.code != 400 or "app_name" not in detail:
                raise RuntimeError(detail) from exc
            notes.append(f"{APP_NAME_DIMENSION} ist in der Property nicht abfragbar, die "
                         f"Absender trennt allein der Hostname: {detail}")
            dims.remove(APP_NAME_DIMENSION)
            found = run_report_all(prop, token, event_body(dims))
        signature_rows = []
        for values, metrics in parse_rows(found)["date_range_0"]:
            row = dict(zip(dims, values))
            signature_rows.append({"date": _iso(row["date"]), "stream_id": row["streamId"],
                                   "event": row["eventName"],
                                   "app_name": row.get(APP_NAME_DIMENSION),
                                   "host_name": row["hostName"],
                                   "events": metrics.get("eventCount", 0),
                                   "sessions": metrics.get("sessions", 0)})
        section = senders.analyze(event_rows, signature_rows)

        items = run_report_all(prop, token, {
            "dateRanges": [date_range],
            "dimensions": [{"name": "itemId"}],
            "metrics": [{"name": name} for name in ITEM_METRICS],
            "limit": 250000,
            **({"dimensionFilter": base_filter} if base_filter else {}),
        })
        section["item_ids"] = senders.item_formats([
            {"item_id": dims[0] if dims else senders.NOT_SET,
             **{field: metrics.get(name, 0) for name, field in ITEM_METRICS.items()}}
            for dims, metrics in parse_rows(items)["date_range_0"]])
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        return {"measurable": False, "note": f"Absender nicht geprüft: {describe_error(exc)}",
                "period": period, "streams": [], "multiple_senders": False,
                "double_counted_events": [], "onset": None, "item_ids": None, "notes": notes}

    measurement_ids = {s.get("stream_id"): s.get("measurement_id") for s in (streams or [])}
    for stream in section["streams"]:
        stream["measurement_id"] = measurement_ids.get(stream["stream_id"])
    section["period"] = period
    section["notes"] = notes
    return section


def _exact(field: str, value: str) -> dict:
    return {"filter": {"fieldName": field,
                       "stringFilter": {"matchType": "EXACT", "value": value}}}


def signature_expression(signature: dict) -> dict:
    """Die Ereignisse eines Absenders als GA4-Ausdruck: `hostName` und, wo
    bekannt, `customEvent:app_name` jeweils gesetzt oder "(not set)"."""
    parts = []
    for field, state in (("hostName", signature.get("host_name")),
                         (APP_NAME_DIMENSION, signature.get("app_name"))):
        if state is None:
            continue
        not_set = _exact(field, senders.NOT_SET)
        parts.append(not_set if state == senders.NOT_SET else {"notExpression": not_set})
    return parts[0] if len(parts) == 1 else {"andGroup": {"expressions": parts}}


def stream_scope(stream_id: str, expression: dict) -> dict:
    """Schränkt nur die Ereignisse des Streams mit zweitem Absender ein. Die
    übrigen Streams der Property zählen unverändert weiter."""
    in_stream = _exact("streamId", stream_id)
    return {"orGroup": {"expressions": [
        {"andGroup": {"expressions": [in_stream, expression]}},
        {"notExpression": in_stream},
    ]}}


def primary_funnel_filter(primary: dict) -> dict:
    """Die Funnel-Ereignisse, und bei zwei Absendern nur die des ersten."""
    parts = []
    for event in FUNNEL_EVENTS:
        name = _exact("eventName", event)
        signature = primary["signatures"].get(event)
        parts.append(name if signature is None else {"andGroup": {"expressions": [
            name, stream_scope(primary["stream_id"], signature_expression(signature))]}})
    return {"orGroup": {"expressions": parts}}


def read_primary_sender(prop: str, token: str, date_range: dict, base_filter,
                        primary: dict) -> dict:
    """Kaufweg und Käufe nur mit dem ersten Absender, für eine Variante.

    `primary` kommt aus `senders.primary_sender()`. Der Funnel trägt je Stufe
    Ereignisse und Sitzungen des ersten Absenders, Stufen mit einem Absender
    unverändert. Käufe und Umsatz je Kanal und Gerät kommen nur, wenn der Kauf
    selbst einen zweiten Absender hat; die Sitzungen dazu stehen im Block
    daneben, sie ändert der zweite Absender nicht. Käufe sind
    `ecommercePurchases`, nie `transactions`.
    """
    block = {"stream_id": primary["stream_id"], "signatures": primary["signatures"],
             "funnel": {event: {"events": 0, "sessions": 0} for event in FUNNEL_EVENTS},
             "channels": None, "devices": None}
    resp = run_report(prop, token, {
        "dateRanges": [date_range],
        "dimensions": [{"name": "eventName"}],
        "metrics": [{"name": "eventCount"}, {"name": "sessions"}],
        "dimensionFilter": merge_filters(primary_funnel_filter(primary), base_filter),
    })
    for dims, metrics in parse_rows(resp)["date_range_0"]:
        if dims and dims[0] in block["funnel"]:
            block["funnel"][dims[0]] = {"events": metrics.get("eventCount", 0),
                                        "sessions": metrics.get("sessions", 0)}

    signature = primary["signatures"].get("purchase")
    if signature:
        purchase_filter = merge_filters(
            stream_scope(primary["stream_id"], signature_expression(signature)), base_filter)
        for key, dimension, name in (("channels", "sessionDefaultChannelGroup", "channel"),
                                     ("devices", "deviceCategory", "device")):
            resp = run_report(prop, token, {
                "dateRanges": [date_range],
                "dimensions": [{"name": dimension}],
                "metrics": [{"name": PURCHASE_METRIC}, {"name": "purchaseRevenue"}],
                "dimensionFilter": purchase_filter,
                "limit": 50,
            })
            block[key] = sorted(
                ({name: dims[0] if dims else "(not set)",
                  "purchases": metrics.get(PURCHASE_METRIC, 0),
                  "purchase_revenue": round(float(metrics.get("purchaseRevenue", 0)), 2)}
                 for dims, metrics in parse_rows(resp)["date_range_0"]),
                key=lambda r: r["purchases"], reverse=True)
    return block


def read_audit_checks(prop: str, token: str, snapshot: dict, date_range: dict,
                      bot_filter=None, streams: list | None = None) -> None:
    """Bot-Profile und Absender prüfen, bevor der Audit eine GA4-Rate rechnet.

    **Warum das im Pull passiert und nicht in der Analyse.** Am 13.09.2026
    nachgerechnet: ein Audit hatte jede GA4-Rate auf Sitzungen gerechnet, von
    denen die Hälfte ein Bot-Profil war, und auf Ereignissen, die ein zweiter
    Absender seit Monaten doppelt schickte. Die Add-to-Cart-Rate stand bei der
    Hälfte ihres Werts, ein Befund über schwache Einstiegsseiten beschrieb fast
    nur Bots, und die Maßnahme schloss einen Kanal mit echten Käufen aus. Die
    Zahlen ohne Profil und nur mit dem ersten Absender brauchen eigene
    Abfragen; eine Analyse, die nur den Snapshot liest, kann sie nicht
    herleiten.

    Schreibt in `snapshot`:

    - `bot_profiles` (read_bot_profiles) und, wenn ein Profil auffällt,
      `bot_profiles.without`: der Hauptteil ohne diese Profile, aus denselben
      Abfragen gebaut, mit den angewandten Regeln unter `filter`.
    - `senders` (read_senders), gerechnet ohne die auffälligen Profile, weil
      ein Bot-Netz, das nur ein Absender zählt, die Überschneidung verdeckt.
      `variant` sagt, auf welchen Sitzungen.
    - `primary_sender` im Hauptteil und in `bot_profiles.without`, wenn ein
      zweiter Absender erkannt ist (read_primary_sender).

    Keine Abfrage legt den Snapshot: der Grund steht im jeweiligen Abschnitt.
    """
    profiles = read_bot_profiles(prop, token, date_range,
                                 (snapshot.get("totals") or {}).get("sessions") or 0,
                                 bot_filter)
    exclusion = None
    if profiles.get("filter_proposal"):
        exclusion, reasons = build_exclusion_filter(dict(profiles["filter_proposal"],
                                                         enabled=True))
        try:
            profiles["without"] = read_block(prop, token, dict(snapshot.get("period") or {}),
                                             date_range, merge_filters(bot_filter, exclusion))
            profiles["without"]["filter"] = reasons
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            profiles["note"] = f"Zahlen ohne Bot-Profil nicht abrufbar: {describe_error(exc)}"
    snapshot["bot_profiles"] = profiles

    clean_filter = merge_filters(bot_filter, exclusion)
    section = read_senders(prop, token, date_range, clean_filter, streams)
    section["variant"] = "without_bot_profiles" if exclusion else "all_sessions"
    snapshot["senders"] = section

    primary = senders.primary_sender(section) if section.get("measurable") else None
    if primary is None:
        if sum(1 for s in section.get("streams") or [] if s.get("multiple_senders")) > 1:
            section["notes"].append("Mehrere Mess-IDs mit zweitem Absender, deshalb keine "
                                    "Zahlen nur mit dem ersten Absender.")
        return
    try:
        snapshot["primary_sender"] = read_primary_sender(prop, token, date_range, bot_filter,
                                                         primary)
        if "without" in profiles:
            profiles["without"]["primary_sender"] = read_primary_sender(
                prop, token, date_range, clean_filter, primary)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        section["notes"].append("Zahlen nur mit dem ersten Absender nicht abrufbar: "
                                f"{describe_error(exc)}")


def check(prop: str, token: str) -> None:
    """Auth plus 1-Tages-Mini-Query, eine OK-/Fehlerzeile, Exit 0/1."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    body = {
        "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
        "metrics": [{"name": "sessions"}],
        "limit": 1,
    }
    try:
        resp = run_report(prop, token, body)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        sys.exit(f"Fehler: GA4-Property {prop} nicht erreichbar: {describe_error(exc)}")
    rows = resp.get("rows", [])
    sessions = rows[0]["metricValues"][0]["value"] if rows else "0"
    info = read_streams(prop, token)
    name = f" \"{info['display_name']}\"" if info.get("display_name") else ""
    ids = ", ".join(info["measurement_ids"])
    print(f"OK: GA4-Property {prop}{name} erreichbar (Sessions gestern: {sessions})")
    if ids:
        print(f"     Mess-IDs dieser Property: {ids}")
    elif info.get("note"):
        print(f"     Hinweis: {info['note']}")


def main():
    parser = argparse.ArgumentParser(
        description="GA4-Snapshot (Kanäle, Kampagnen, Geräte, Länder, Landingpages, "
                     "Funnel) als JSON ziehen."
    )
    parser.add_argument("--property", required=True, help="GA4-Property-ID (nur die Zahl)")
    parser.add_argument("--creds", required=True, help="Pfad zum Service-Account-JSON")
    parser.add_argument("--compare-properties", default="",
                        help="Weitere GA4-Property-IDs, kommagetrennt. Je "
                             "Property kommt eine Monatsreihe aus Sitzungen, "
                             "Käufen und Umsatz in den Snapshot, damit der "
                             "Audit sieht, welche Property mit dem Shop "
                             "übereinstimmt.")
    parser.add_argument("--start", help="Start des Zeitraums, YYYY-MM-DD")
    parser.add_argument("--end", help="Ende des Zeitraums, YYYY-MM-DD")
    parser.add_argument("--out", help="Zielverzeichnis für den Snapshot")
    parser.add_argument("--max-history", action="store_true",
                        help="misst die älteste vorhandene Historie (--start entfällt) und "
                             "schreibt ga4-max-history.json mit granularity max_history "
                             "sowie history_from im Snapshot")
    parser.add_argument("--compare-start", help="Start des Vergleichszeitraums")
    parser.add_argument("--compare-end", help="Ende des Vergleichszeitraums")
    parser.add_argument("--pulse", action="store_true",
                        help="Wochen-Puls: schreibt ga4-pulse.json mit granularity week")
    parser.add_argument("--check", action="store_true",
                        help="Nur Auth plus Mini-Query testen, Exit 0/1")
    parser.add_argument("--config",
                        help="Pfad zu reporting/config.json; liest daraus den "
                             "optionalen bot_filter-Block")
    parser.add_argument("--audit-checks", action="store_true",
                        help="prüft auf Bot-Profile und einen zweiten Absender je "
                             "Mess-ID und schreibt bot_profiles, senders und "
                             "primary_sender in den Snapshot, samt den Zahlen "
                             "ohne Bot-Profil")
    args = parser.parse_args()

    prop = args.property.removeprefix("properties/")

    if not args.check:
        missing = []
        if not args.max_history and not args.start:
            missing.append("--start")
        if not args.max_history and not args.end:
            missing.append("--end")
        if not args.out:
            missing.append("--out")
        if missing:
            parser.error(f"ohne --check erforderlich: {', '.join(missing)}")
        if bool(args.compare_start) != bool(args.compare_end):
            parser.error("--compare-start und --compare-end nur gemeinsam")
        if args.max_history:
            if args.start:
                parser.error("--start und --max-history schliessen sich aus, der "
                             "Start wird gemessen")
            if args.compare_start or args.compare_end:
                parser.error("--compare-start/--compare-end nicht mit --max-history "
                             "kombinierbar")
            if args.pulse:
                parser.error("--pulse nicht mit --max-history kombinierbar")
        if args.audit_checks and args.pulse:
            # Ein zweiter Absender zählt erst ab einer Woche mit Ereignissen
            # (senders.MIN_ACTIVE_DAYS), in einem Wochen-Puls fände die
            # Prüfung nie einen und meldete trotzdem "ein Absender".
            parser.error("--audit-checks nicht mit --pulse kombinierbar")

    try:
        token = get_access_token(args.creds, "analytics")
    except Exception as exc:
        sys.exit(f"Fehler beim Holen des Access-Tokens: {exc}")

    if args.check:
        check(prop, token)
        return

    bot_filter, bot_rules = None, []
    if args.config:
        try:
            spec = json.loads(Path(args.config).read_text(encoding="utf-8")).get("bot_filter")
        except (OSError, ValueError) as exc:
            sys.exit(f"Fehler beim Lesen von {args.config}: {exc}")
        bot_filter, bot_rules = build_exclusion_filter(spec)

    history_from = None
    if args.max_history:
        # Kein --end heisst: bis gestern, konsistent mit check() und der
        # API-Latenz (der heutige Tag ist noch nicht vollständig ausgezählt).
        if not args.end:
            args.end = (date.today() - timedelta(days=1)).isoformat()
        try:
            history_from = measure_history_start(prop, token, args.end)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            sys.exit(f"Fehler bei der Messung der Historie: {describe_error(exc)}")
        args.start = history_from

    compare = bool(args.compare_start)
    main_range = {"startDate": args.start, "endDate": args.end}
    date_ranges = [main_range]
    if compare:
        date_ranges.append({"startDate": args.compare_start, "endDate": args.compare_end})

    calls = block_bodies(date_ranges, bot_filter)
    if compare:
        calls["landing_pages_compare"] = landing_body(date_ranges[1], bot_filter)
    if args.max_history:
        # Nur hier: die Baseline zieht ihre Monatsreihe aus diesem Snapshot,
        # ein Monats- oder Wochenlauf berichtet ohnehin über genau einen
        # Zeitraum und braucht sie nicht. yearMonth statt date, weil eine
        # Tagesreihe über die volle Historie das Vielfache an Zeilen ergäbe
        # und die Baseline Monate verlangt.
        calls["by_month"] = {
            "dateRanges": [main_range],
            "dimensions": [{"name": "yearMonth"},
                           {"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": name} for name in CHANNEL_METRICS],
            "limit": 100000,
            **({"dimensionFilter": bot_filter} if bot_filter else {}),
        }

    results = {}
    comparison_error = None
    purchases_note = None
    currency = None
    channel_totals = {}
    for name, body in calls.items():
        try:
            if name in ("channels", "by_month"):
                # Beide fragen die Käufe ab und brauchen denselben Fallback.
                # Die Notiz kommt aus dem Kanal-Call; scheitert die Metrik,
                # scheitert sie in beiden aus demselben Grund.
                resp, note = run_channels(prop, token, body)
                if name == "channels":
                    purchases_note = note
                    currency = response_currency(resp)
                    channel_totals = parse_totals(resp)
            else:
                resp = run_report(prop, token, body)
            results[name] = parse_rows(resp)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            message = f"GA4-Abfrage {name}: {describe_error(exc)}"
            # Nur der reine Vergleichs-Call darf den Lauf nicht legen: Kanäle
            # und Funnel tragen den Hauptteil bereits mit, der Snapshot wird
            # trotzdem geschrieben und comparison wird zum error-Objekt.
            if name == "landing_pages_compare":
                comparison_error = message
                continue
            sys.exit(f"Fehler bei {message}")

    # Interne Suchbegriffe separat: customEvent:search_term ist eine optionale
    # Custom Dimension, ihr Fehlen ist eine Konfigurationslücke in der Property,
    # nie ein Grund, den Lauf abzubrechen. Deshalb ausserhalb der calls-Schleife,
    # deren Fehlschlag für jeden anderen Namen fatal wäre.
    site_search_results, site_search_note = run_site_search(prop, token, {
        "dateRanges": date_ranges,
        "dimensions": [{"name": "customEvent:search_term"}],
        "metrics": [{"name": "eventCount"}, {"name": "sessions"}],
        "dimensionFilter": merge_filters(
            {"filter": {"fieldName": "eventName",
                        "inListFilter": {"values": ["view_search_results"]}}},
            bot_filter,
        ),
        "limit": 50,
    })

    granularity = "max_history" if args.max_history else ("week" if args.pulse else "month")
    snapshot = build_block(
        {"start": args.start, "end": args.end, "granularity": granularity},
        results["channels"].get("date_range_0", []),
        results["landing_pages"].get("date_range_0", []),
        results["funnel"].get("date_range_0", []),
        results["campaigns"].get("date_range_0", []),
        results["devices"].get("date_range_0", []),
        results["countries"].get("date_range_0", []),
        site_search_results.get("date_range_0", []) if site_search_results else None,
        channel_totals=channel_totals.get("date_range_0"),
    )
    # Die Berichtswährung der Property, in der jeder purchase_revenue dieses
    # Snapshots steht. Sie muss nicht die des Shops sein; wer Umsatz gegen
    # Shopify hält, prüft sie zuerst.
    snapshot["currency"] = currency
    snapshot["property"] = read_streams(args.property, token)
    weitere = [p for p in (args.compare_properties or "").split(",") if p.strip()]
    if weitere:
        snapshot["compare_properties"] = read_compare(
            [p.strip() for p in weitere], token, args.start, args.end)
    if history_from:
        snapshot["history_from"] = history_from
    if "by_month" in results:
        snapshot["by_month"] = build_by_month(results["by_month"].get("date_range_0", []))
    if compare:
        if comparison_error:
            snapshot["comparison"] = {"error": comparison_error}
            print(f"Warnung: Vergleichszeitraum fehlgeschlagen ({comparison_error}), "
                  "Snapshot ohne Vergleich geschrieben")
        else:
            # Der Einzel-Range-Call hat keine dateRange-Dimension, seine Zeilen
            # liegen deshalb unter date_range_0.
            snapshot["comparison"] = build_block(
                {"start": args.compare_start, "end": args.compare_end,
                 "granularity": granularity},
                results["channels"].get("date_range_1", []),
                results["landing_pages_compare"].get("date_range_0", []),
                results["funnel"].get("date_range_1", []),
                results["campaigns"].get("date_range_1", []),
                results["devices"].get("date_range_1", []),
                results["countries"].get("date_range_1", []),
                site_search_results.get("date_range_1", []) if site_search_results else None,
                channel_totals=channel_totals.get("date_range_1"),
            )

    if args.audit_checks:
        read_audit_checks(prop, token, snapshot, main_range, bot_filter,
                          snapshot["property"].get("streams"))

    # notes steht nur in der Datei, wenn wirklich etwas genullt wurde (gleiche
    # Konvention wie in shopify.json).
    # Gefilterte Zahlen müssen sich als gefiltert zu erkennen geben, sonst
    # vergleicht ein späterer Lauf ungefiltert gegen gefiltert.
    if bot_rules:
        snapshot["filters"] = {"bot_filter": bot_rules}

    # Beide Hinweise in einem Dict sammeln statt nacheinander zuzuweisen: sonst
    # würde ein zweiter Hinweis den ersten in snapshot["notes"] stillschweigend
    # überschreiben, sobald beide Fälle in einem Lauf zusammentreffen.
    notes = {}
    if purchases_note:
        notes["purchases"] = purchases_note
        print(f"Warnung: {purchases_note}; Conversion Rate je Kanal ist "
              "damit nicht berechenbar, der übrige Snapshot ist vollständig")
    if site_search_note:
        notes["site_search"] = site_search_note
        print(f"Warnung: {site_search_note}; interne Suchbegriffe fehlen im "
              "Snapshot, der übrige Snapshot ist vollständig")
    if notes:
        snapshot["notes"] = notes

    if args.pulse:
        out_name = "ga4-pulse.json"
    elif args.max_history:
        out_name = "ga4-max-history.json"
    else:
        out_name = "ga4.json"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    totals = snapshot["totals"]
    history_note = f", historie ab: {history_from}" if history_from else ""
    currency_note = f" {currency}" if currency else ""
    print(f"Geschrieben: {out_path} (Sessions: {totals['sessions']}, "
          f"Umsatz: {totals['purchase_revenue']}{currency_note}{history_note})")
    if args.audit_checks:
        profiles = snapshot["bot_profiles"]
        flagged = [p["label"] for p in profiles["profiles"] if p["flagged"]]
        print("Bot-Profile: " + (", ".join(flagged) if flagged else "keins auffällig")
              + (f" (Hinweis: {profiles['note']})" if profiles.get("note") else ""))
        section = snapshot["senders"]
        double = section.get("double_counted_events") or []
        print("Absender: " + ("doppelt gezählt: " + ", ".join(double) if double
                             else "kein zweiter Absender, der doppelt zählt")
              + (f" (Hinweis: {section['note']})" if section.get("note") else ""))


if __name__ == "__main__":
    main()
