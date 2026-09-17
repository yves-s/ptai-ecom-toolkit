#!/usr/bin/env python3
"""GSC-Snapshot über die Search Console API (Search Analytics, Sitemaps, URL-Inspection).

Aufruf:
  gsc_pull.py --site <siteUrl> --creds <sa.json> --start YYYY-MM-DD --end YYYY-MM-DD --out <dir>
              [--inspect-urls URL[,URL...]] [--compare-start YYYY-MM-DD --compare-end YYYY-MM-DD]
              [--pulse]
  gsc_pull.py --site <siteUrl> --creds <sa.json> --max-history --out <dir> [--end YYYY-MM-DD]
              [--inspect-urls URL[,URL...]]
  gsc_pull.py --site <siteUrl> --creds <sa.json> --check

Schreibt <out>/gsc.json (bzw. gsc-pulse.json bei --pulse, gsc-max-history.json bei
--max-history) mit period, totals, top_queries, top_pages, top_countries, devices,
search_types, daily, sitemaps, index_sample und optional comparison. --max-history
ermittelt --start selbst: gemessen statt angenommen, weil die API für Tage außerhalb
der vorgehaltenen Historie schlicht keine Zeile liefert. Das Ergebnis landet
zusätzlich als history_from im Snapshot.
Nur Stdlib plus google-auth (über den geteilten Token-Helfer), kein requests.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# Geteilte Helfer aus dem Plugin-Root (scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from api_common import describe_error  # noqa: E402
from google_token import get_access_token  # noqa: E402

# {site} muss komplett URL-encodiert sein (quote mit safe=""), sonst zerlegen
# Doppelpunkt und Slashes von sc-domain:- und URL-Properties den Pfad.
SEARCH_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
SITEMAPS_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

# Die API kennt "type" (früher "searchType") nur als Filter im Body, nicht als
# Dimension zum Gruppieren. Deshalb ein Query je Wert statt einer Abfrage mit
# dimensions=["searchType"], das wäre ein ungültiger Dimensionswert.
SEARCH_TYPES = ["web", "image", "video", "news", "discover", "googleNews"]

# Die Search Console API ist bei 16 Monaten dokumentiert (~486 Tage), hält pro
# Property aber unterschiedlich lange Historie vor. Der Puffer macht die Messung
# robust gegen Rundung und Kalendermonate, ohne dass eine Property mit kürzerer
# Historie dadurch mehr zurückliefert: die API gibt ohnehin nur, was sie hat.
MAX_HISTORY_LOOKBACK_DAYS = 550


def api_request(url: str, token: str, body: dict | None = None) -> dict:
    """Ein API-Call: GET ohne Body, POST mit JSON-Body."""
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if body is not None else "GET"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        try:
            return json.load(resp)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ungültige JSON-Antwort der GSC-API: {exc}") from exc


def fetch(name: str, url: str, token: str, body: dict | None = None,
          fatal: bool = True) -> dict:
    """api_request mit klarer Fehlerbehandlung statt Traceback.

    fatal=True bricht den Lauf mit einer Fehlerzeile ab (Haupt-Queries).
    fatal=False wirft einen RuntimeError mit derselben Meldung, damit der
    Aufrufer den Fehler abfangen kann (Vergleichszeitraum).
    """
    try:
        return api_request(url, token, body)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        message = f"GSC-Abfrage {name}: {describe_error(exc)}"
        if fatal:
            sys.exit(f"Fehler bei {message}")
        raise RuntimeError(message) from exc


def parse_rows(resp: dict, key_name: str) -> list:
    """Search-Analytics-Zeilen in flache Dicts wandeln (keys[0] wird key_name)."""
    return [
        {
            key_name: (row.get("keys") or [""])[0],
            "clicks": int(row.get("clicks", 0) or 0),
            "impressions": int(row.get("impressions", 0) or 0),
            "ctr": round(float(row.get("ctr", 0) or 0), 4),
            "position": round(float(row.get("position", 0) or 0), 2),
        }
        for row in resp.get("rows", [])
    ]


def build_totals(daily: list) -> dict:
    """Totals aus der Tagesreihe aggregieren.

    Position ist der impressions-gewichtete Mittelwert der Tageswerte: eine
    Näherung, weil die API pro Tag schon selbst mittelt; für den Report reicht das.
    """
    clicks = sum(d["clicks"] for d in daily)
    impressions = sum(d["impressions"] for d in daily)
    ctr = round(clicks / impressions, 4) if impressions else 0
    position = (
        round(sum(d["position"] * d["impressions"] for d in daily) / impressions, 2)
        if impressions
        else 0
    )
    return {"clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position}


def build_by_month(daily: list) -> list:
    """Monatsreihe aus der Tagesreihe, chronologisch sortiert.

    Die Baseline braucht Klicks, Impressionen, CTR und Position **je Monat**
    (Spec Abschnitt 10). Der übrige Snapshot aggregiert über den ganzen
    Zeitraum zu einer Summe, und aus einer Lebenszeit-Summe lässt sich später
    kein Vergleich gegen denselben Kalendermonat rechnen. Feldname `by_month`
    wie im Shopify- und GA4-Snapshot, damit die Baseline alle drei Quellen
    gleich liest.

    CTR und Position werden neu gerechnet, nie gemittelt: der Mittelwert
    zweier Tages-CTR ist nicht die CTR des Monats, sobald die Tage verschieden
    viele Impressionen haben, und die Position wird aus demselben Grund mit
    den Impressionen gewichtet. Dieselbe Rechnung wie in `build_totals()`,
    nur je Monat statt über alles.
    """
    months: dict[str, dict] = {}
    for row in daily:
        date_value = str(row.get("date") or "")
        if len(date_value) < 7:
            # Eine Zeile ohne brauchbares Datum in irgendeinen Monat zu werfen
            # verfaelscht genau diesen Monat. Lieber weglassen.
            continue
        bucket = months.setdefault(date_value[:7], {"clicks": 0, "impressions": 0,
                                                     "weighted_position": 0.0})
        impressions = int(row.get("impressions", 0) or 0)
        bucket["clicks"] += int(row.get("clicks", 0) or 0)
        bucket["impressions"] += impressions
        bucket["weighted_position"] += float(row.get("position", 0) or 0) * impressions

    result = []
    for month in sorted(months):
        bucket = months[month]
        impressions = bucket["impressions"]
        result.append({
            "month": month,
            "clicks": bucket["clicks"],
            "impressions": impressions,
            "ctr": round(bucket["clicks"] / impressions, 4) if impressions else 0,
            # Keine Impressionen heisst keine Position. Eine 0 stuende im
            # Report als Platz 0, also besser als Platz 1.
            "position": (round(bucket["weighted_position"] / impressions, 2)
                          if impressions else None),
        })
    return result


def pull_search_types(site_enc: str, token: str, start: str, end: str,
                      fatal: bool = True) -> list:
    """Klicks/Impressionen je Suchtyp (web, image, video, news, discover, googleNews).

    Die Search Analytics API kennt keine Suchtyp-Dimension zum Gruppieren, nur den
    type-Filter im Body. Deshalb ein Query je Typ (dimensions leer, eine
    Gesamtzeile pro Aufruf) statt einer einzigen Abfrage. Ein Typ ohne Daten im
    Zeitraum liefert keine Zeile und taucht im Ergebnis schlicht nicht auf.
    """
    url = SEARCH_URL.format(site=site_enc)
    rows = []
    for search_type in SEARCH_TYPES:
        body = {"startDate": start, "endDate": end, "type": search_type, "rowLimit": 1}
        resp = fetch(f"searchAnalytics type={search_type}", url, token, body, fatal=fatal)
        entries = resp.get("rows", [])
        if not entries:
            continue
        entry = entries[0]
        rows.append({
            "search_type": search_type,
            "clicks": int(entry.get("clicks", 0) or 0),
            "impressions": int(entry.get("impressions", 0) or 0),
            "ctr": round(float(entry.get("ctr", 0) or 0), 4),
            "position": round(float(entry.get("position", 0) or 0), 2),
        })
    return rows


def pull_block(site_enc: str, token: str, start: str, end: str, granularity: str,
               fatal: bool = True) -> dict:
    """Einen Snapshot-Block (Hauptteil oder comparison) für einen Zeitraum ziehen.

    Fünf Search-Analytics-Queries: query (Top 50), page (Top 25), country (Top 50),
    device (bis zu 10, praktisch nur 3), date (Tagesreihe) - plus die
    Suchtyp-Aufschlüsselung über pull_search_types (kein Dimensions-Query, siehe
    dort). Die API sortiert selbst nach Klicks absteigend, ein orderBy ist nicht nötig.
    """
    queries = {
        "top_queries": ("query", 50),
        "top_pages": ("page", 25),
        "top_countries": ("country", 50),
        "devices": ("device", 10),
        "daily": ("date", 1000),
    }
    url = SEARCH_URL.format(site=site_enc)
    data = {}
    for name, (dim, row_limit) in queries.items():
        body = {
            "startDate": start,
            "endDate": end,
            "dimensions": [dim],
            "rowLimit": row_limit,
        }
        data[name] = parse_rows(
            fetch(f"searchAnalytics {name}", url, token, body, fatal=fatal), dim
        )
    data["daily"].sort(key=lambda d: d["date"])
    data["search_types"] = pull_search_types(site_enc, token, start, end, fatal=fatal)
    return {
        "period": {"start": start, "end": end, "granularity": granularity},
        "totals": build_totals(data["daily"]),
        "by_month": build_by_month(data["daily"]),
        "top_queries": data["top_queries"],
        "top_pages": data["top_pages"],
        "top_countries": data["top_countries"],
        "devices": data["devices"],
        "search_types": data["search_types"],
        "daily": data["daily"],
    }


def measure_history_start(site_enc: str, token: str, end: str) -> str:
    """Ältestes Datum mit echten Daten für diese Property ermitteln, gemessen statt angenommen.

    Fragt testweise deutlich weiter zurück als die dokumentierten 16 Monate
    (MAX_HISTORY_LOOKBACK_DAYS); für Tage, die die Property nicht mehr vorhält,
    liefert die API schlicht keine Zeile. Das älteste tatsächlich zurückgekommene
    Datum ist die gemessene Grenze. Kommt gar keine Zeile zurück (Property ohne
    jede Historie), gilt end als history_from, damit der anschließende
    pull_block-Aufruf einen validen, wenn auch leeren Zeitraum bekommt.
    """
    candidate_start = (date.fromisoformat(end) - timedelta(days=MAX_HISTORY_LOOKBACK_DAYS)).isoformat()
    url = SEARCH_URL.format(site=site_enc)
    body = {
        "startDate": candidate_start,
        "endDate": end,
        "dimensions": ["date"],
        "rowLimit": 25000,
    }
    daily = parse_rows(fetch("searchAnalytics max-history-probe", url, token, body), "date")
    return min((row["date"] for row in daily), default=end)


def parse_sitemaps(resp: dict) -> list:
    """Sitemap-Liste auf das Wesentliche eindampfen (errors/warnings kommen als String)."""
    return [
        {
            "path": entry.get("path"),
            "last_submitted": entry.get("lastSubmitted"),
            "is_pending": entry.get("isPending", False),
            "errors": int(entry.get("errors", 0) or 0),
            "warnings": int(entry.get("warnings", 0) or 0),
        }
        for entry in resp.get("sitemap", [])
    ]


def inspect_urls(site: str, token: str, urls: list) -> list:
    """Index-Stichprobe je URL über die URL-Inspection-API.

    Hinweis Pilot: ob der readonly-Scope webmasters.readonly für diesen Endpunkt
    reicht, wird im Pilot gegen die echte API validiert. Ein Fehler je URL ist
    deshalb nie fatal, er landet als error-Eintrag im Sample. siteUrl gehört hier
    unencodiert in den Body, encodiert wird nur im URL-Pfad.
    """
    sample = []
    for url in urls:
        try:
            resp = api_request(INSPECT_URL, token, {"inspectionUrl": url, "siteUrl": site})
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            sample.append({"url": url, "error": describe_error(exc)})
            continue
        idx = resp.get("inspectionResult", {}).get("indexStatusResult", {})
        entry = {
            "url": url,
            "verdict": idx.get("verdict"),
            "coverage_state": idx.get("coverageState"),
        }
        if idx.get("lastCrawlTime"):
            entry["last_crawl_time"] = idx["lastCrawlTime"]
        sample.append(entry)
    return sample


def check(site: str, site_enc: str, token: str) -> None:
    """Auth plus 1-Tages-Mini-Query, eine OK-/Fehlerzeile, Exit 0/1."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    body = {"startDate": yesterday, "endDate": yesterday, "rowLimit": 1}
    try:
        resp = api_request(SEARCH_URL.format(site=site_enc), token, body)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        sys.exit(f"Fehler: GSC-Property {site} nicht erreichbar: {describe_error(exc)}")
    rows = resp.get("rows", [])
    clicks = int(rows[0].get("clicks", 0)) if rows else 0
    print(f"OK: GSC-Property {site} erreichbar (Klicks gestern: {clicks})")


def main():
    parser = argparse.ArgumentParser(
        description="GSC-Snapshot (Queries, Seiten, Tagesreihe, Indexierung) als JSON ziehen."
    )
    parser.add_argument("--site", required=True,
                        help="siteUrl der Property, z. B. sc-domain:example.de")
    parser.add_argument("--creds", required=True, help="Pfad zum Service-Account-JSON")
    parser.add_argument("--start", help="Start des Zeitraums, YYYY-MM-DD")
    parser.add_argument("--end", help="Ende des Zeitraums, YYYY-MM-DD")
    parser.add_argument("--out", help="Zielverzeichnis für den Snapshot")
    parser.add_argument("--inspect-urls", action="append", default=[],
                        help="URLs für die Index-Stichprobe, wiederholbar oder kommagetrennt")
    parser.add_argument("--compare-start", help="Start des Vergleichszeitraums")
    parser.add_argument("--compare-end", help="Ende des Vergleichszeitraums")
    parser.add_argument("--pulse", action="store_true",
                        help="Wochen-Puls: schreibt gsc-pulse.json mit granularity week")
    parser.add_argument("--max-history", action="store_true",
                        help="misst die älteste vorhandene Historie (--start entfällt) und "
                             "schreibt gsc-max-history.json mit granularity max_history "
                             "sowie history_from im Snapshot")
    parser.add_argument("--check", action="store_true",
                        help="Nur Auth plus Mini-Query testen, Exit 0/1")
    args = parser.parse_args()

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
                parser.error("--max-history ermittelt --start selbst, nicht zusätzlich angeben")
            if args.compare_start or args.compare_end:
                parser.error("--max-history und --compare-start/--compare-end schließen sich aus")
            if args.pulse:
                parser.error("--max-history und --pulse schließen sich aus")

    site = args.site
    site_enc = urllib.parse.quote(site, safe="")

    try:
        token = get_access_token(args.creds, "webmasters")
    except Exception as exc:
        sys.exit(f"Fehler beim Holen des Access-Tokens: {exc}")

    if args.check:
        check(site, site_enc, token)
        return

    inspect_list = [u.strip() for chunk in args.inspect_urls
                    for u in chunk.split(",") if u.strip()]

    history_from = None
    if args.max_history:
        # Kein --end heißt: bis gestern, konsistent mit check() und der API-Latenz
        # (der heutige Tag ist noch nicht vollständig ausgezählt).
        end = args.end or (date.today() - timedelta(days=1)).isoformat()
        history_from = measure_history_start(site_enc, token, end)
        granularity = "max_history"
        snapshot = pull_block(site_enc, token, history_from, end, granularity)
        snapshot["history_from"] = history_from
    else:
        granularity = "week" if args.pulse else "month"
        snapshot = pull_block(site_enc, token, args.start, args.end, granularity)

    # Sitemaps und Index-Stichprobe sind punktuelle Momentaufnahmen: sie gehören
    # nur in den Hauptteil, nie in den comparison-Block. Ein Sitemap-Fehler ist
    # nicht fatal: die schon gezogenen Search-Analytics-Daten bleiben erhalten,
    # statt der Liste steht dann ein error-Objekt im Snapshot.
    try:
        snapshot["sitemaps"] = parse_sitemaps(
            api_request(SITEMAPS_URL.format(site=site_enc), token)
        )
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        snapshot["sitemaps"] = {"error": describe_error(exc)}
    snapshot["index_sample"] = inspect_urls(site, token, inspect_list)

    if args.compare_start:
        # GSC kennt keine zwei dateRanges in einem Call, der Vergleich läuft als
        # zweiter Query-Satz über die Compare-Daten. Scheitert er, bleibt der
        # schon gezogene Hauptteil erhalten: statt des Blocks steht ein
        # error-Objekt im Snapshot.
        try:
            snapshot["comparison"] = pull_block(
                site_enc, token, args.compare_start, args.compare_end, granularity,
                fatal=False,
            )
        except RuntimeError as exc:
            snapshot["comparison"] = {"error": str(exc)}
            print(f"Warnung: Vergleichszeitraum fehlgeschlagen ({exc}), "
                  "Snapshot ohne Vergleich geschrieben")

    if args.pulse:
        filename = "gsc-pulse.json"
    elif args.max_history:
        filename = "gsc-max-history.json"
    else:
        filename = "gsc.json"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    totals = snapshot["totals"]
    history_note = f", historie ab: {history_from}" if history_from else ""
    print(f"Geschrieben: {out_path} (Klicks: {totals['clicks']}, "
          f"Impressionen: {totals['impressions']}{history_note})")


if __name__ == "__main__":
    main()
