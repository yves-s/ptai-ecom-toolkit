#!/usr/bin/env python3
"""Mehrere Absender je GA4-Mess-ID erkennen, bevor daraus eine Rate entsteht.

**Warum das hier steht.** Am 13.09.2026 in einem echten Audit nachgerechnet:
seit einem Stichtag schickte eine App mit eigenem Web-Pixel dieselben
Ereignisse an dieselbe Mess-ID wie der bestehende Connector. Vier von fünf
Stufen des Kaufwegs zählten doppelt, die Käufe lagen weit über dem, was der
Connector allein meldete, und die Sitzungen änderten sich kaum,
weil der Pixel in dieselben Besuche schrieb. Der Audit hatte doppelte Käufe
nur als Summe gegen Shopify geprüft und doppelte Tags nur im Quelltext. Beides
fand nichts, ein App-Pixel steht in keinem Quelltext. Der Befund lautete
"Messkette vollständig, kein Eingriff nötig".

**Woran ein Absender zu erkennen ist.** An zwei Merkmalen je Ereignis, und nur
daran, ob sie gesetzt sind, nicht an ihrem Wert:

- `hostName` fehlt bei Ereignissen, die ein Server schickt. Mehrere Domains
  eines Shops sind deshalb kein zweiter Absender, ein serverseitiger neben
  einem clientseitigen schon.
- `customEvent:app_name` setzt ein Shopify-Connector auf den Verkaufskanal,
  ein gtag-Pixel lässt es leer. Einzelne Käufe aus einem anderen Kanal
  desselben Connectors sind kein zweiter Absender. Die Dimension gibt es nur,
  wo die Property den Parameter registriert hat; ohne sie trennt der
  Hostname allein, und zwei clientseitige Absender fallen dann nur noch an
  der Artikel-ID auf.

Ein Merkmal zählt als Absender eines Ereignisses, wenn es an mindestens
MIN_ACTIVE_DAYS Tagen mindestens MIN_SENDER_SHARE der Ereignisse trägt.

**Wann zwei Absender doppelt zählen.** Wenn der zweite in dieselben Besuche
schreibt wie der erste. Das zeigt die Überschneidung der Sitzungen an den
Tagen, an denen beide senden: Sitzungen mit dem Ereignis vom ersten plus die
vom zweiten minus alle Sitzungen mit dem Ereignis, geteilt durch die vom
zweiten. Liegt sie ab OVERLAP_THRESHOLD, meldet der zweite überwiegend Besuche,
die der erste schon gemeldet hat (`duplicated`). Darunter bringt er eigene
Sitzungen mit (`separate_sessions`), etwa Bots, die nur er zählt. Das ist ein
anderer Fehler, aber auch dann ist keine Summe über beide eine Kennzahl.

**Die Überschneidung wird ohne Bot-Profil gerechnet, wo eins erkannt ist.**
Im selben echten Fall zählte der Pixel ein Bot-Netz mit, das der Connector
nicht sah, und die Überschneidung bei `view_item` fiel dadurch unter die
Schwelle; ohne das Profil lag sie nahe bei eins. Der Pull ruft diese Prüfung
deshalb nach der Profilerkennung auf.

**Die Artikel-ID als Gegenprobe.** Verschiedene Einbindungen senden Artikel in
verschiedenen Formaten: ein Shopify-Connector die numerische Produkt-ID, die
Google-App `shopify_<Land>_<Produkt>_<Variante>`, ein Tag-Manager oft die
Artikelnummer. Zwei Formate mit Gewicht heißen zwei Absender, auch wo die
Merkmale oben beide gleich aussehen.
"""
import re

#: Die Ereignisse, deren Absender geprüft werden: der Kaufweg plus
#: `page_view`, weil ein doppelter Seitenaufruf die Engagement Rate und die
#: Seiten je Sitzung aufbläht.
SENDER_EVENTS = ("page_view", "view_item", "add_to_cart", "view_cart",
                 "begin_checkout", "add_payment_info", "purchase")

#: Ab diesem Anteil an den Ereignissen eines Tages sendet ein Merkmal an
#: diesem Tag. Darunter liegen einzelne Käufe aus einem Nebenkanal oder
#: Vorschau-Domains.
MIN_SENDER_SHARE = 0.10

#: An so vielen Tagen muss ein Merkmal senden, um ein Absender zu sein. Ein
#: Test über ein paar Tage ist keine Einbindung, die jede Zahl verdoppelt.
MIN_ACTIVE_DAYS = 7

#: Ab dieser Überschneidung der Sitzungen meldet der zweite Absender dieselben
#: Besuche wie der erste: mehr als die Hälfte seiner Sitzungen trägt das
#: Ereignis schon vom ersten.
OVERLAP_THRESHOLD = 0.5

#: Ab diesem Anteil zählt ein Format der Artikel-ID als eigener Absender.
MIN_FORMAT_SHARE = 0.10

NOT_SET = "(not set)"

#: Die Artikelmetriken, wie der Pull sie benennt. `items_added_to_cart` und
#: `items_checked_out` zählen Stück und sind in echten Properties schon auf ein
#: Vielfaches der Ereignisse gesprungen; über Formatanteile entscheiden deshalb
#: nur die angesehenen oder, ohne sie, die gekauften Artikel.
ITEM_METRICS = ("items_viewed", "items_added_to_cart", "items_checked_out", "items_purchased")


def signature(app_name: str | None, host_name: str | None) -> dict:
    """Die Merkmale eines Ereignisses als Absender-Signatur.

    `app_name` None heißt, die Dimension war in der Property nicht
    abfragbar, und bleibt None; sonst "set" oder "(not set)".
    """
    return {
        "app_name": None if app_name is None else (NOT_SET if app_name == NOT_SET else "set"),
        "host_name": NOT_SET if host_name == NOT_SET else "set",
    }


def _event_order(event: str) -> tuple:
    return (SENDER_EVENTS.index(event) if event in SENDER_EVENTS else len(SENDER_EVENTS), event)


def _top(counter: dict, limit: int = 3) -> list:
    return [value for value, _ in sorted(counter.items(), key=lambda kv: -kv[1])[:limit]]


def _judge_event(entries: dict, day_totals: dict) -> dict:
    """Absender, Status und Überschneidung eines Ereignisses in einem Stream."""
    def day_events(day):
        if day in day_totals:
            return day_totals[day][0]
        return sum(e["days"].get(day, (0, 0))[0] for e in entries.values())

    total_events = (sum(v[0] for v in day_totals.values())
                    or sum(x[0] for e in entries.values() for x in e["days"].values()))
    signatures = []
    for entry in entries.values():
        events = sum(x[0] for x in entry["days"].values())
        active = sorted(d for d, x in entry["days"].items()
                        if day_events(d) and x[0] / day_events(d) >= MIN_SENDER_SHARE)
        signatures.append({
            "signature": entry["signature"],
            "events": events,
            "share": round(events / total_events, 4) if total_events else None,
            "active_days": len(active),
            "first_day": active[0] if active else None,
            "last_day": active[-1] if active else None,
            "app_names": _top(entry["app_names"]),
            "host_names": _top(entry["host_names"]),
            "_active": active,
            "_days": entry["days"],
        })

    senders = sorted((s for s in signatures if s["active_days"] >= MIN_ACTIVE_DAYS),
                     key=lambda s: (s["first_day"], -s["events"]))
    others = [s for s in signatures if s["active_days"] < MIN_ACTIVE_DAYS]

    def public(items):
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in items]

    result = {"events": total_events, "senders": public(senders),
              "other_signatures": public(sorted(others, key=lambda s: -s["events"])),
              "status": "single"}
    if len(senders) < 2:
        return result

    primary, second = senders[0], senders[1]
    both = sorted(set(primary["_active"]) & set(second["_active"]))
    sessions_primary = sum(primary["_days"][d][1] for d in both)
    sessions_second = sum(second["_days"][d][1] for d in both)
    sessions_event = sum(day_totals.get(d, (0, 0))[1] for d in both)
    events_primary = sum(primary["_days"][d][0] for d in both)
    events_second = sum(second["_days"][d][0] for d in both)
    ratio = None
    if sessions_second and sessions_event:
        ratio = round((sessions_primary + sessions_second - sessions_event) / sessions_second, 4)

    if ratio is None:
        status = "overlap_unmeasured"
    elif ratio >= OVERLAP_THRESHOLD:
        status = "duplicated"
    else:
        status = "separate_sessions"
    result.update({
        "status": status,
        "primary": primary["signature"],
        "second": second["signature"],
        "onset": second["first_day"],
        "overlap": {"days": len(both), "sessions_primary": sessions_primary,
                    "sessions_second": sessions_second, "sessions_event": sessions_event,
                    "ratio": ratio},
        "uplift": round(events_second / events_primary, 4) if events_primary else None,
    })
    return result


def analyze(event_rows: list[dict], signature_rows: list[dict]) -> dict:
    """Absender je Stream und Ereignis aus den Tageszeilen des Pulls.

    `event_rows`: je Tag, Stream und Ereignis `date`, `stream_id`, `event`,
    `events`, `sessions`, ohne Aufteilung nach Absender. `signature_rows`:
    dieselben Felder plus `app_name` und `host_name` in ihren Rohwerten.
    Die Gesamtzeilen sind nötig, weil sich Sitzungen nicht über Absender
    addieren lassen: eine Sitzung mit beiden steht in beiden Zeilen.
    """
    if not signature_rows:
        return {"measurable": False, "reason": "keine Ereigniszeilen im Zeitraum",
                "streams": [], "multiple_senders": False,
                "double_counted_events": [], "onset": None}

    totals = {}
    for row in event_rows:
        key = (row["stream_id"], row["event"])
        totals.setdefault(key, {})[row["date"]] = (row.get("events") or 0,
                                                   row.get("sessions") or 0)

    grouped = {}
    for row in signature_rows:
        sig = signature(row.get("app_name"), row.get("host_name"))
        entry = (grouped.setdefault(row["stream_id"], {})
                 .setdefault(row["event"], {})
                 .setdefault((sig["app_name"], sig["host_name"]),
                             {"signature": sig, "days": {}, "app_names": {}, "host_names": {}}))
        events, sessions = entry["days"].get(row["date"], (0, 0))
        entry["days"][row["date"]] = (events + (row.get("events") or 0),
                                      sessions + (row.get("sessions") or 0))
        for field, counter in (("app_name", entry["app_names"]), ("host_name", entry["host_names"])):
            if row.get(field) is not None:
                counter[row[field]] = counter.get(row[field], 0) + (row.get("events") or 0)

    streams = []
    for stream_id in sorted(grouped):
        events = {event: _judge_event(grouped[stream_id][event], totals.get((stream_id, event), {}))
                  for event in sorted(grouped[stream_id], key=_event_order)}
        streams.append({
            "stream_id": stream_id,
            "events": events,
            "multiple_senders": any(v["status"] != "single" for v in events.values()),
            "double_counted_events": [e for e, v in events.items() if v["status"] == "duplicated"],
        })

    double = sorted({e for s in streams for e in s["double_counted_events"]}, key=_event_order)
    onsets = [v["onset"] for s in streams for v in s["events"].values() if v.get("onset")]
    return {
        "measurable": True,
        "streams": streams,
        "multiple_senders": any(s["multiple_senders"] for s in streams),
        "double_counted_events": double,
        "onset": min(onsets) if onsets else None,
    }


def primary_sender(section: dict) -> dict | None:
    """Stream und Signatur des ersten Absenders je Ereignis mit zweitem Absender.

    Daraus baut der Pull die Zahlen nur mit dem ersten Absender. Nur für
    genau einen Stream mit zweitem Absender: tragen mehrere Mess-IDs je einen
    zweiten, gibt es keine eindeutige Rechnung, und None heißt dann, dass der
    Report keine bereinigte Zahl zeigt statt einer falschen.
    """
    streams = [s for s in (section.get("streams") or []) if s.get("multiple_senders")]
    if len(streams) != 1:
        return None
    stream = streams[0]
    signatures = {event: judged["primary"] for event, judged in stream["events"].items()
                  if judged["status"] != "single" and judged.get("primary")}
    if not signatures:
        return None
    return {"stream_id": stream["stream_id"], "signatures": signatures}


def item_id_format(item_id: str) -> str:
    """Das Format einer Artikel-ID: `shopify_id` (12 bis 15 Ziffern, Produkt-
    oder Varianten-ID aus Shopify), `merchant_center_id` (`shopify_<Land>_...`,
    das Angebotsformat der Google-App), `not_set` oder `other`."""
    if item_id == NOT_SET:
        return "not_set"
    if re.fullmatch(r"shopify_[A-Z]{2}_.+", item_id):
        return "merchant_center_id"
    if re.fullmatch(r"\d{12,15}", item_id):
        return "shopify_id"
    return "other"


def item_formats(item_rows: list[dict]) -> dict:
    """Anteil je Format der Artikel-ID, und ob mehr als eins Gewicht hat.

    `item_rows` tragen `item_id` und die ITEM_METRICS. `basis` ist die
    Metrik, an der die Anteile hängen (siehe ITEM_METRICS).
    """
    formats = {}
    for row in item_rows:
        entry = formats.setdefault(item_id_format(row.get("item_id") or NOT_SET),
                                   {metric: 0 for metric in ITEM_METRICS})
        for metric in ITEM_METRICS:
            entry[metric] += row.get(metric) or 0
    basis = ("items_viewed" if sum(f["items_viewed"] for f in formats.values())
             else "items_purchased")
    total = sum(f[basis] for f in formats.values())
    for entry in formats.values():
        entry["share"] = round(entry[basis] / total, 4) if total else None
    weighty = [name for name, entry in formats.items()
               if name != "not_set" and (entry["share"] or 0) >= MIN_FORMAT_SHARE]
    return {"basis": basis, "formats": formats, "multiple_formats": len(weighty) >= 2}
