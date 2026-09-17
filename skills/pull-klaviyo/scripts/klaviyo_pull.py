#!/usr/bin/env python3
"""Klaviyo-Snapshot über die Klaviyo-REST-API (JSON:API, https://a.klaviyo.com/api/).

Aufruf (Key kommt aus PTAI_KLAVIYO_KEY in der Umgebung, --api-key nur als
Rückfallweg mit Warnung, siehe resolve_key()):
  klaviyo_pull.py --out <dir> [--days 365] [--report-days 90]
                   [--revision 2025-07-15]
  klaviyo_pull.py --check

Schreibt <out>/klaviyo.json mit account, metrics, flows, campaigns,
flow_reports, campaign_reports, placed_order_aggregate, lists, segments,
forms und notes. Jeder Teil scheitert isoliert (Muster wie shopify_pull/
gsc_pull): ein Fehler macht das jeweilige Feld null plus Begründung in
notes, bricht nie den Gesamtlauf ab.

Kampagnen und Flow-Nachrichten (SEND_MESSAGE-Actions) tragen zusätzlich den
tatsächlichen Content: subject, preview_text, from_email/from_label und
body_text (aus dem verknüpften Template-HTML zu Klartext gestrippt). Das ist
Marken-Content für ein CRM-Voice-Profil, keine Kunden-PII, und fällt nicht
unter die Profil-Export-Sperre unten.

Pilot-Status: die Report-Endpunkte (campaign-values-reports,
flow-values-reports, metric-aggregates) sowie der Content-Pull über
campaign-messages/flow-messages/templates sind noch nie gegen einen echten
Account gelaufen. Siehe SKILL.md, Abschnitt Pilot-Status.

Nur Stdlib, kein requests.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

KEY_ENV_VAR = "PTAI_KLAVIYO_KEY"


class _TextExtractor(HTMLParser):
    """Minimaler HTML-zu-Text-Stripper für E-Mail-Templates, nur Stdlib.

    Kein Layout-Anspruch: Tags raus, style/script-Inhalt raus, Blöcke durch
    Zeilenumbruch getrennt, Mehrfach-Leerzeilen zusammengefasst. Für eine
    Voice-Analyse reicht das; ein echtes HTML-zu-Markdown wäre hier
    overengineered.
    """

    BLOCK_TAGS = {"p", "div", "br", "tr", "td", "li", "h1", "h2", "h3", "h4"}
    SKIP_TAGS = {"style", "script"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self.chunks.append(data.strip())


def strip_html(html: str) -> str:
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    text = " ".join(parser.chunks)
    # Zeilenumbruch-Marker aus handle_starttag wieder in echte Umbrüche wandeln,
    # dabei Mehrfach-Leerzeichen und -Umbrüche zusammenfassen.
    text = text.replace(" \n ", "\n").replace("\n ", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)

API_ROOT = "https://a.klaviyo.com/api"
DEFAULT_REVISION = "2025-07-15"
MAX_RETRIES = 1

# Am Pilot-Account bestätigt (11.09.2026): Flow-Actions heißen
# SEND_EMAIL/SEND_SMS/SEND_PUSH je Kanal, nie SEND_MESSAGE (Kanal-neutraler
# Name existiert in der API nicht). SEND_MESSAGE bleibt als Fallback für den
# Fall, dass Klaviyo künftig einen kanal-neutralen Typ einführt.
SEND_ACTION_TYPES = {"SEND_EMAIL", "SEND_SMS", "SEND_PUSH", "SEND_MESSAGE"}


def resolve_key(from_argument: str | None) -> str:
    """Der Key kommt bevorzugt aus der Umgebung, das Argument bleibt Rückfallweg.

    Ein per --api-key übergebener Schlüssel steht in ps und damit für jeden
    Nutzer der Maschine offen. Muster wie resolve_key() in
    skills/check-geo/scripts/geo_api.py.
    """
    from_env = os.environ.get(KEY_ENV_VAR, "").strip()
    if from_env:
        return from_env
    if from_argument:
        print(f"Warnung: der Key wurde als Argument übergeben und steht damit "
              f"in der Prozessliste. Besser: {KEY_ENV_VAR} in der Umgebung "
              f"setzen (z. B. per .env im Kunden-Workspace).", file=sys.stderr)
        return from_argument
    sys.exit(f"Fehler: kein Key gefunden. {KEY_ENV_VAR} in der Umgebung setzen "
              f"(empfohlen, z. B. via .env) oder --api-key übergeben.")


def describe_error(exc: Exception) -> str:
    """Eine Exception aus einem Klaviyo-Call in eine klare Meldung wandeln.

    Klaviyo folgt JSON:API: Fehler stehen unter errors[].detail. HTTPError
    muss vor URLError geprüft werden, er ist eine Subklasse davon.
    """
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            errors = body.get("errors") or []
            if errors:
                return "; ".join(e.get("detail", "") for e in errors if e.get("detail"))
            return f"HTTP {exc.code}"
        except Exception:
            return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"API nicht erreichbar: {exc.reason}"
    return str(exc)


def api_request(url: str, api_key: str, revision: str, method: str = "GET",
                 body: dict | None = None) -> tuple[dict, dict]:
    """Ein API-Call. Gibt (json_body, response_headers) zurück.

    429 wird einmal mit der Retry-After-Frist wiederholt, alle anderen
    Fehler wandern zum Aufrufer hoch.
    """
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": revision,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return (json.loads(raw) if raw else {}), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < MAX_RETRIES:
                wait = int(exc.headers.get("Retry-After", "5")) if exc.headers else 5
                time.sleep(max(wait, 1))
                attempt += 1
                continue
            raise
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ungültige JSON-Antwort der Klaviyo-API: {exc}") from exc


def fetch(name: str, url: str, api_key: str, revision: str, method: str = "GET",
          body: dict | None = None, fatal: bool = False):
    """api_request mit klarer Fehlerbehandlung statt Traceback.

    fatal=True bricht den Lauf ab (nur für den --check-Pfad genutzt).
    fatal=False (Default) gibt (None, Fehlermeldung) zurück, der Aufrufer
    schreibt das als notes-Eintrag und macht mit den übrigen Teilen weiter.
    """
    try:
        result, _ = api_request(url, api_key, revision, method=method, body=body)
        return result, None
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        message = f"Klaviyo-Abfrage {name}: {describe_error(exc)}"
        if fatal:
            sys.exit(f"Fehler bei {message}")
        return None, message


def paginate(first_page: dict, api_key: str, revision: str, name: str,
             max_pages: int = 20) -> tuple[list, str | None]:
    """Über links.next blättern, bis kein next mehr da ist oder max_pages erreicht.

    Gibt (alle_data_zeilen, fehlermeldung_oder_none) zurück; ein Fehler beim
    Blättern bricht die Sammlung ab, die bereits gesammelten Zeilen bleiben.
    """
    rows = list(first_page.get("data") or [])
    next_url = (first_page.get("links") or {}).get("next")
    pages = 1
    while next_url and pages < max_pages:
        result, err = fetch(f"{name} (Seite {pages + 1})", next_url, api_key, revision)
        if err:
            return rows, err
        rows.extend(result.get("data") or [])
        next_url = (result.get("links") or {}).get("next")
        pages += 1
    if next_url:
        return rows, f"{name}: mehr als {max_pages} Seiten, Liste evtl. unvollständig"
    return rows, None


def paginate_with_included(first_page: dict, api_key: str, revision: str, name: str,
                            included_type: str, max_pages: int = 20) -> tuple[list, dict, str | None]:
    """Wie paginate(), sammelt zusätzlich `included`-Objekte eines Typs über alle Seiten.

    Klaviyo liefert included nur zur jeweiligen Seite, nicht kumulativ; ohne
    das würden Kampagnen/Flow-Nachrichten ab Seite 2 ihren Content verlieren.
    """
    rows = list(first_page.get("data") or [])
    included: dict = {
        item["id"]: item for item in (first_page.get("included") or [])
        if item.get("type") == included_type
    }
    next_url = (first_page.get("links") or {}).get("next")
    pages = 1
    while next_url and pages < max_pages:
        result, err = fetch(f"{name} (Seite {pages + 1})", next_url, api_key, revision)
        if err:
            return rows, included, err
        rows.extend(result.get("data") or [])
        included.update({
            item["id"]: item for item in (result.get("included") or [])
            if item.get("type") == included_type
        })
        next_url = (result.get("links") or {}).get("next")
        pages += 1
    if next_url:
        return rows, included, f"{name}: mehr als {max_pages} Seiten, Liste evtl. unvollständig"
    return rows, included, None


def resolve_template_text(template_ref: dict | None, api_key: str, revision: str,
                           template_cache: dict, notes: dict) -> str | None:
    """Template-Relationship auf gestrippten Klartext auflösen, mit Cache je Template-ID.

    Kampagnen/Flows teilen sich häufig ein Basis-Template; ohne Cache würde
    jede Nachricht dasselbe Template erneut abrufen.
    """
    if not template_ref or not template_ref.get("data"):
        return None
    template_id = template_ref["data"].get("id")
    if not template_id:
        return None
    if template_id in template_cache:
        return template_cache[template_id]
    result, err = fetch(f"template {template_id}", f"{API_ROOT}/templates/{template_id}/",
                         api_key, revision)
    if err:
        notes.setdefault("template_fetch_errors", []).append(err)
        template_cache[template_id] = None
        return None
    html = (result.get("data", {}).get("attributes", {}) or {}).get("html")
    text = strip_html(html) if html else None
    template_cache[template_id] = text
    return text


def message_content(message_obj: dict, nested_under_definition: bool) -> dict:
    """subject/preview_text/from_* aus einem campaign-message- oder flow-message-Objekt.

    Am Pilot-Account bestätigt (11.09.2026): die beiden Ressourcen verschachteln
    content unterschiedlich tief. campaign-message: attributes.definition.content.
    flow-message: attributes.content, kein definition-Wrapper.
    """
    attrs = message_obj.get("attributes", {}) or {}
    if nested_under_definition:
        content = (attrs.get("definition") or {}).get("content") or {}
    else:
        content = attrs.get("content") or {}
    return {
        "subject": content.get("subject"),
        "preview_text": content.get("preview_text"),
        "from_email": content.get("from_email"),
        "from_label": content.get("from_label"),
    }


def check_auth(api_key: str, revision: str) -> int:
    url = f"{API_ROOT}/accounts/"
    result, err = fetch("accounts (check)", url, api_key, revision, fatal=False)
    if err:
        print(f"FEHLER: {err}", file=sys.stderr)
        return 1
    print("OK: Klaviyo-Key gültig, /api/accounts erreichbar.")
    return 0


def pull_account(api_key: str, revision: str, notes: dict) -> dict | None:
    result, err = fetch("accounts", f"{API_ROOT}/accounts/", api_key, revision)
    if err:
        notes["account"] = err
        return None
    rows = result.get("data") or []
    if not rows:
        notes["account"] = "keine Account-Zeile in der Antwort"
        return None
    attrs = rows[0].get("attributes", {})
    return {
        "id": rows[0].get("id"),
        "timezone": attrs.get("timezone"),
        "public_api_key": attrs.get("public_api_key"),
    }


def pull_metrics(api_key: str, revision: str, notes: dict) -> list:
    # Am Pilot-Account bestätigt: /api/metrics/ akzeptiert kein page[size] und
    # liefert ohne den Parameter alle Metriken in einer Seite.
    result, err = fetch("metrics", f"{API_ROOT}/metrics/", api_key, revision)
    if err:
        notes["metrics"] = err
        return []
    rows, page_err = paginate(result, api_key, revision, "metrics")
    if page_err:
        notes["metrics"] = page_err
    return [
        {
            "id": r.get("id"),
            "name": r.get("attributes", {}).get("name"),
            "integration": (r.get("attributes", {}).get("integration") or {}).get("name"),
        }
        for r in rows
    ]


def pull_flows(api_key: str, revision: str, template_cache: dict,
                pull_content: bool, notes: dict) -> list:
    url = f"{API_ROOT}/flows/?page[size]=50&include=flow-actions"
    result, err = fetch("flows", url, api_key, revision)
    if err:
        notes["flows"] = err
        return []
    rows, action_included, page_err = paginate_with_included(
        result, api_key, revision, "flows", "flow-action"
    )
    if page_err:
        notes["flows"] = page_err
    flows = []
    for r in rows:
        attrs = r.get("attributes", {})
        action_refs = (
            r.get("relationships", {}).get("flow-actions", {}).get("data") or []
        )
        actions = []
        for ref in action_refs:
            action_obj = action_included.get(ref["id"], {})
            action_attrs = action_obj.get("attributes", {})
            action = {
                "id": ref["id"],
                "action_type": action_attrs.get("action_type"),
                "status": action_attrs.get("status"),
            }
            if pull_content and action_attrs.get("action_type") in SEND_ACTION_TYPES:
                action.update(pull_flow_message_content(
                    ref["id"], api_key, revision, template_cache, notes
                ))
            actions.append(action)
        flows.append({
            "id": r.get("id"),
            "name": attrs.get("name"),
            "status": attrs.get("status"),
            "trigger_type": attrs.get("trigger_type"),
            "created": attrs.get("created"),
            "updated": attrs.get("updated"),
            "actions": actions,
        })
    return flows


def pull_flow_message_content(action_id: str, api_key: str, revision: str,
                               template_cache: dict, notes: dict) -> dict:
    """Für eine SEND_MESSAGE-Flow-Action: verknüpfte Nachricht(en) plus Template-Text.

    Related-Resource-Endpoint. Am Pilot-Account bestätigt (11.09.2026):
    ?include=template wird hier abgelehnt ("'template' include is not
    currently supported for the requested operation on this resource"),
    anders als bei campaign-messages. Template kommt deshalb immer über
    resolve_template_text() als eigener Call, mit Cache je Template-ID.
    Mehrere Nachrichten (A/B-Test-Actions) werden zu einer Liste, das Feld
    heißt im Snapshot messages statt message.
    """
    result, err = fetch(
        f"flow-messages von Action {action_id}",
        f"{API_ROOT}/flow-actions/{action_id}/flow-messages/",
        api_key, revision,
    )
    if err:
        notes.setdefault("flow_message_content_errors", []).append(err)
        return {"messages": []}
    messages = []
    for msg in result.get("data") or []:
        content = message_content(msg, nested_under_definition=False)
        template_ref = msg.get("relationships", {}).get("template")
        body_text = None
        if template_ref and template_ref.get("data"):
            body_text = resolve_template_text(template_ref, api_key, revision,
                                               template_cache, notes)
        messages.append({"id": msg.get("id"), **content, "body_text": body_text})
    return {"messages": messages}


def pull_campaigns(api_key: str, revision: str, since: str, template_cache: dict,
                    pull_content: bool, notes: dict) -> list:
    # campaign_type ist Pflichtfilter; email-Kanal, seit <since>.
    filt = f"and(equals(messages.channel,'email'),greater-or-equal(created_at,{since}))"
    safe_chars = "(),'"
    url = (
        f"{API_ROOT}/campaigns/?filter={urllib.parse.quote(filt, safe=safe_chars)}"
        f"&page[size]=50&include=campaign-messages"
    )
    result, err = fetch("campaigns", url, api_key, revision)
    if err:
        notes["campaigns"] = err
        return []
    rows, message_included, page_err = paginate_with_included(
        result, api_key, revision, "campaigns", "campaign-message"
    )
    if page_err:
        notes["campaigns"] = page_err
    campaigns = []
    for r in rows:
        attrs = r.get("attributes", {})
        message_refs = (
            r.get("relationships", {}).get("campaign-messages", {}).get("data") or []
        )
        messages = []
        for ref in message_refs:
            msg_obj = message_included.get(ref["id"], {})
            content = message_content(msg_obj, nested_under_definition=True)
            body_text = None
            if pull_content:
                body_text = pull_campaign_message_body(
                    ref["id"], api_key, revision, template_cache, notes
                )
            messages.append({"id": ref["id"], **content, "body_text": body_text})
        campaigns.append({
            "id": r.get("id"),
            "name": attrs.get("name"),
            "status": attrs.get("status"),
            "channel": "email",
            "send_time": attrs.get("send_time"),
            "created_at": attrs.get("created_at"),
            "messages": messages,
        })
    return campaigns


def pull_campaign_message_body(message_id: str, api_key: str, revision: str,
                                template_cache: dict, notes: dict) -> str | None:
    """Für eine Campaign-Message gezielt das Template nachladen (include auf der
    Listen-Antwort deckt nur campaign-messages ab, nicht deren Template)."""
    result, err = fetch(
        f"campaign-message {message_id}",
        f"{API_ROOT}/campaign-messages/{message_id}/?include=template",
        api_key, revision,
    )
    if err:
        notes.setdefault("campaign_message_content_errors", []).append(err)
        return None
    template_ref = result.get("data", {}).get("relationships", {}).get("template")
    return resolve_template_text(template_ref, api_key, revision, template_cache, notes)


REPORT_STATISTICS = [
    "recipients", "opens", "open_rate", "clicks", "click_rate",
    "conversions", "conversion_rate", "conversion_value",
    "revenue_per_recipient", "unsubscribes", "unsubscribe_rate",
    "spam_complaints", "spam_complaint_rate", "bounced", "bounce_rate",
]


def pull_values_report(kind: str, api_key: str, revision: str, since: str,
                        until: str, conversion_metric_id: str | None, notes: dict) -> dict:
    """campaign-values-reports oder flow-values-reports (POST).

    Am Pilot-Account bestätigt: conversion_metric_id ist Pflicht (ohne sie
    400 "conversion_metric_id is a required field"), groupings trägt
    <kind>_id direkt. Fehlt die Metrik-ID (accounts:read/metrics-Scope
    fehlt), wird der Report gar nicht erst versucht.
    """
    if not conversion_metric_id:
        notes[f"{kind}_reports"] = "keine conversion_metric_id (Placed-Order-Metrik nicht gefunden)"
        return {"by_" + kind: [], "raw_response_shape_confirmed": False}
    report_type = f"{kind}-values-report"
    body = {
        "data": {
            "type": report_type,
            "attributes": {
                "timeframe": {"start": since, "end": until},
                "statistics": REPORT_STATISTICS,
                "conversion_metric_id": conversion_metric_id,
            },
        }
    }
    result, err = fetch(
        f"{kind}-values-report", f"{API_ROOT}/{kind}-values-reports/",
        api_key, revision, method="POST", body=body,
    )
    if err:
        notes[f"{kind}_reports"] = err
        return {"by_" + kind: [], "raw_response_shape_confirmed": False}
    try:
        rows = (result.get("data", {}).get("attributes", {}) or {}).get("results") or []
        parsed = []
        for row in rows:
            groupings = row.get("groupings") or {}
            stats = row.get("statistics") or {}
            parsed.append({f"{kind}_id": groupings.get(f"{kind}_id")} | stats)
        return {"by_" + kind: parsed, "raw_response_shape_confirmed": bool(parsed)}
    except Exception as exc:  # Antwortform weicht ab: Pilot-Fall, nicht crashen
        notes[f"{kind}_reports"] = f"unerwartete Antwortform: {exc}"
        return {"by_" + kind: [], "raw_response_shape_confirmed": False, "raw": result}


def pull_placed_order_aggregate(api_key: str, revision: str, placed_order_id: str | None,
                                 since: str, until: str, notes: dict) -> dict:
    if not placed_order_id:
        notes["placed_order_aggregate"] = "Metrik 'Placed Order' nicht gefunden"
        return {"by_attributed_channel": [], "by_attributed_flow": [],
                "raw_response_shape_confirmed": False}

    def aggregate_by(dimension: str) -> tuple[list, str | None]:
        """Ein metric-aggregate-Call. Antwortform am Pilot-Account bestätigt:

        {"dates": [...monatlich...], "data": [{"dimensions": [wert],
        "measurements": {"count": [...je Monat...], "sum_value": [...]}}]}
        Wird hier in eine flache Liste je Dimensionswert und Monat gewandelt,
        statt drei parallele Arrays roh zu übernehmen.
        """
        body = {
            "data": {
                "type": "metric-aggregate",
                "attributes": {
                    "metric_id": placed_order_id,
                    "measurements": ["count", "sum_value"],
                    "interval": "month",
                    "by": [dimension],
                    "filter": [f"greater-or-equal(datetime,{since})", f"less-than(datetime,{until})"],
                },
            }
        }
        result, err = fetch(
            f"metric-aggregate ({dimension})", f"{API_ROOT}/metric-aggregates/",
            api_key, revision, method="POST", body=body,
        )
        if err:
            return [], err
        try:
            attrs = result.get("data", {}).get("attributes", {}) or {}
            dates = attrs.get("dates") or []
            rows = []
            for series in attrs.get("data") or []:
                dim_value = (series.get("dimensions") or [None])[0]
                counts = (series.get("measurements") or {}).get("count") or []
                sums = (series.get("measurements") or {}).get("sum_value") or []
                for i, month in enumerate(dates):
                    rows.append({
                        dimension: dim_value,
                        "month": month[:7],  # YYYY-MM
                        "count": counts[i] if i < len(counts) else None,
                        "sum_value": sums[i] if i < len(sums) else None,
                    })
            return rows, None
        except Exception as exc:
            return [], f"unerwartete Antwortform: {exc}"

    by_channel, err_channel = aggregate_by("$attributed_channel")
    by_flow, err_flow = aggregate_by("$attributed_flow")
    if err_channel or err_flow:
        notes["placed_order_aggregate"] = "; ".join(filter(None, [err_channel, err_flow]))
    return {
        "by_attributed_channel": by_channel,
        "by_attributed_flow": by_flow,
        "raw_response_shape_confirmed": bool(by_channel or by_flow),
    }


def pull_lists(api_key: str, revision: str, notes: dict) -> list:
    # Am Pilot-Account bestätigt (11.09.2026): page[size] max. 10, und
    # additional-fields[list]=profile_count wird abgelehnt ("additional-fields
    # must be in []"): diese Revision liefert profile_count über lists nicht.
    # profile_count bleibt deshalb None plus Note, kein Absturz.
    url = f"{API_ROOT}/lists/?page[size]=10"
    result, err = fetch("lists", url, api_key, revision)
    if err:
        notes["lists"] = err
        return []
    rows, page_err = paginate(result, api_key, revision, "lists", max_pages=60)
    if page_err:
        notes["lists"] = page_err
    notes.setdefault("lists_profile_count", "additional-fields=profile_count von der API abgelehnt, nicht gezogen")
    return [
        {
            "id": r.get("id"),
            "name": r.get("attributes", {}).get("name"),
            "profile_count": None,
        }
        for r in rows
    ]


def pull_segments(api_key: str, revision: str, notes: dict) -> list:
    # Am Pilot-Account bestätigt (11.09.2026): dieselbe additional-fields-
    # Ablehnung wie bei lists, siehe pull_lists().
    url = f"{API_ROOT}/segments/?page[size]=10"
    result, err = fetch("segments", url, api_key, revision)
    if err:
        notes["segments"] = err
        return []
    rows, page_err = paginate(result, api_key, revision, "segments", max_pages=60)
    if page_err:
        notes["segments"] = page_err
    notes.setdefault("segments_profile_count", "additional-fields=profile_count von der API abgelehnt, nicht gezogen")
    return [
        {
            "id": r.get("id"),
            "name": r.get("attributes", {}).get("name"),
            "profile_count": None,
        }
        for r in rows
    ]


def pull_forms(api_key: str, revision: str, notes: dict) -> list:
    url = f"{API_ROOT}/forms/?page[size]=50"
    result, err = fetch("forms", url, api_key, revision)
    if err:
        notes["forms"] = err
        return []
    rows, page_err = paginate(result, api_key, revision, "forms")
    if page_err:
        notes["forms"] = page_err
    return [
        {
            "id": r.get("id"),
            "name": r.get("attributes", {}).get("name"),
            "status": r.get("attributes", {}).get("status"),
        }
        for r in rows
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key",
                         help=f"Nur als Rückfallweg, steht damit in ps. Besser: {KEY_ENV_VAR} "
                              f"in der Umgebung setzen (z. B. via .env im Kunden-Workspace).")
    parser.add_argument("--out")
    parser.add_argument("--days", type=int, default=365, help="Bestandsfenster Flows/Kampagnen")
    parser.add_argument("--report-days", type=int, default=90, help="Fenster für Report-Endpunkte")
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--skip-content", action="store_true",
                         help="Nur Metadaten zu Kampagnen/Flows, ohne Betreff/Text/Template "
                              "(schneller, weniger API-Calls, kein Voice-Profil möglich)")
    args = parser.parse_args()
    api_key = resolve_key(args.api_key)

    if args.check:
        sys.exit(check_auth(api_key, args.revision))

    if not args.out:
        parser.error("--out ist erforderlich außer bei --check")

    now = datetime.now(timezone.utc)
    since_inventory = (now - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")
    since_report = (now - timedelta(days=args.report_days)).strftime("%Y-%m-%dT00:00:00Z")
    until = now.strftime("%Y-%m-%dT00:00:00Z")

    notes: dict = {}
    template_cache: dict = {}
    pull_content = not args.skip_content
    account = pull_account(api_key, args.revision, notes)
    metrics = pull_metrics(api_key, args.revision, notes)
    placed_order_id = next(
        (m["id"] for m in metrics if (m.get("name") or "").lower() == "placed order"), None
    )
    flows = pull_flows(api_key, args.revision, template_cache, pull_content, notes)
    campaigns = pull_campaigns(api_key, args.revision, since_inventory,
                                template_cache, pull_content, notes)
    flow_reports = pull_values_report("flow", api_key, args.revision,
                                       since_report, until, placed_order_id, notes)
    campaign_reports = pull_values_report("campaign", api_key, args.revision,
                                           since_report, until, placed_order_id, notes)
    placed_order_aggregate = pull_placed_order_aggregate(
        api_key, args.revision, placed_order_id, since_report, until, notes
    )
    lists = pull_lists(api_key, args.revision, notes)
    segments = pull_segments(api_key, args.revision, notes)
    forms = pull_forms(api_key, args.revision, notes)

    notes["profiles"] = "kein Einzelprofil-Export, nur aggregierte Zaehler (Listen/Segmente)"

    snapshot = {
        "period": {
            "inventory_days": args.days,
            "report_days": args.report_days,
            "pulled_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "account": account,
        "metrics": metrics,
        "flows": flows,
        "campaigns": campaigns,
        "flow_reports": flow_reports,
        "campaign_reports": campaign_reports,
        "placed_order_aggregate": placed_order_aggregate,
        "lists": lists,
        "segments": segments,
        "forms": forms,
        "notes": notes,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "klaviyo.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    campaign_msg_count = sum(len(c.get("messages") or []) for c in campaigns)
    flow_msg_count = sum(
        1 for f in flows for a in f.get("actions", []) for _ in (a.get("messages") or [])
    )
    print(f"Snapshot geschrieben: {out_path}")
    print(f"  Flows: {len(flows)}, Kampagnen: {len(campaigns)}, Listen: {len(lists)}, "
          f"Segmente: {len(segments)}, Formulare: {len(forms)}")
    if pull_content:
        print(f"  Content gezogen: {campaign_msg_count} Kampagnen-Nachrichten, "
              f"{flow_msg_count} Flow-Nachrichten, {len(template_cache)} Templates aufgelöst")
    if notes:
        print("  Notes:")
        for key, value in notes.items():
            print(f"    - {key}: {value}")


if __name__ == "__main__":
    main()
