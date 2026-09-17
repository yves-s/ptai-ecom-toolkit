#!/usr/bin/env python3
"""Die GA4-Raten eines Audits in jeder Variante nebeneinander.

Aufruf:
  python3 -m audit.ga4_variants reporting/data/<run-id>/ga4.json

**Warum das hier steht.** Am 13.09.2026 nachgerechnet: ein Audit hatte jede
GA4-Rate aus dem Hauptteil von `ga4.json` gerechnet, und darin steckte ein
Bot-Profil mit der Hälfte aller Sitzungen und ein zweiter Absender, der seit
Monaten jede Stufe des Kaufwegs doppelt meldete. Drei Befunde fielen, als die
Zahlen ohne beides dastanden, und die Analysen hatten keine Möglichkeit, das
zu sehen. Seit `ga4_pull.py --audit-checks` stehen die Zahlen ohne Profil
(`bot_profiles.without`) und nur mit dem ersten Absender (`primary_sender`)
im Snapshot. Diese Datei rechnet aus jeder Variante dieselben Raten, damit
eine Analyse sieht, welche Aussage an der Variante hängt, und jeder Befund
sagen kann, auf welcher er steht.

**Die Formeln sind die aus `reference/metrics.md`.** Conversion Rate ist
Käufe durch Sitzungen. Jede Funnel-Rate zählt Sitzungen, nie Ereignisse, und
eine Übergangsrate ist der Anteil der vorherigen Stufe. Käufe sind `purchases`
aus `ecommercePurchases`; ein Snapshot mit nur `transactions` bleibt nicht
berechenbar. Eine fehlende Zahl bleibt None, nie 0.
"""
import json
import sys

from audit import bots

#: Die Stufen des Kaufwegs in der Reihenfolge, in der Übergänge gelesen werden.
FUNNEL_STEPS = ("view_item", "add_to_cart", "view_cart", "begin_checkout", "purchase")

#: So viele Einstiegsseiten stehen je Variante in der Ausgabe.
TOP_LANDING_PAGES = 10

#: So heißt eine Zahl nur aus den Ereignissen des ersten Absenders, im
#: `context` der Befunde und an den Tabellen des Reports.
PRIMARY_SENDER_LABEL = "nur erster Absender"


def _rate(numerator, denominator, digits: int = 6):
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def variants(ga4: dict) -> list[dict]:
    """Die Blöcke, aus denen Raten entstehen: immer alle Sitzungen, dazu ohne
    Bot-Profil, wenn der Pull eins erkannt und die Zahlen dazu gezogen hat."""
    out = [{"key": "all_sessions", "label": "alle Sitzungen", "block": ga4, "filter": []}]
    without = (ga4.get("bot_profiles") or {}).get("without")
    if without:
        out.append({"key": "without_bot_profiles", "label": "ohne Bot-Profil",
                    "block": without, "filter": without.get("filter") or []})
    return out


def _breakdown(items: list | None, key: str, total: int, primary_rows: list | None) -> list:
    primary = None if primary_rows is None else {row.get(key): row for row in primary_rows}
    out = []
    for item in items or []:
        sessions = item.get("sessions") or 0
        row = {key: item.get(key), "sessions": sessions, "share": _rate(sessions, total, 4),
               "purchases": item.get("purchases"),
               "conversion_rate": _rate(item.get("purchases"), sessions)}
        if primary is not None:
            purchases = (primary.get(item.get(key)) or {}).get("purchases", 0)
            row["purchases_primary_sender"] = purchases
            row["conversion_rate_primary_sender"] = _rate(purchases, sessions)
        out.append(row)
    return out


def _funnel(funnel: dict, primary: dict | None) -> list:
    """Übergänge von Stufe zu Stufe, auf Sitzungen. Die erste Stufe steht gegen
    alle Sitzungen. Mit dem ersten Absender zählen Zähler und Nenner beide aus
    dessen Ereignissen; die Sitzungen insgesamt ändert er nicht."""
    def sessions(source, step):
        if step == "sessions":
            return funnel.get("sessions")
        return (source.get(step) or {}).get("sessions")

    steps, previous = [], "sessions"
    for step in FUNNEL_STEPS:
        row = {"from": previous, "to": step,
               "sessions_from": sessions(funnel, previous), "sessions_to": sessions(funnel, step),
               "events_to": (funnel.get(step) or {}).get("events")}
        row["rate"] = _rate(row["sessions_to"], row["sessions_from"])
        if primary is not None:
            row["sessions_from_primary_sender"] = sessions(primary, previous)
            row["sessions_to_primary_sender"] = sessions(primary, step)
            row["events_to_primary_sender"] = (primary.get(step) or {}).get("events")
            row["rate_primary_sender"] = _rate(row["sessions_to_primary_sender"],
                                               row["sessions_from_primary_sender"])
        steps.append(row)
        previous = step
    return steps


def rates(block: dict) -> dict:
    """Kanäle, Geräte, Kaufweg und Einstiegsseiten eines Blocks als Raten mit
    Zähler und Nenner, dazu die Kanalprüfung aus `bots.analyze()` für genau
    diesen Block."""
    total = (block.get("totals") or {}).get("sessions") or 0
    primary = block.get("primary_sender") or {}
    pages = sorted(block.get("landing_pages") or [],
                   key=lambda p: p.get("sessions") or 0, reverse=True)[:TOP_LANDING_PAGES]
    return {
        "sessions": total,
        "channels": _breakdown(block.get("channels"), "channel", total, primary.get("channels")),
        "devices": _breakdown(block.get("devices"), "device", total, primary.get("devices")),
        "funnel": _funnel(block.get("funnel") or {}, primary.get("funnel")),
        "landing_pages": [
            {"landing_page": p.get("landing_page"), "sessions": p.get("sessions") or 0,
             "share": _rate(p.get("sessions") or 0, total, 4),
             "engagement_rate": p.get("engagement_rate"), "purchases": p.get("purchases"),
             "conversion_rate": _rate(p.get("purchases"), p.get("sessions") or 0)}
            for p in pages],
        "suspicious_channels": [{"channel": c["channel"], "signals": c["signals"]}
                                for c in bots.analyze(block)["suspicious_channels"]],
    }


def compare(ga4: dict) -> dict:
    """Alle Varianten eines Snapshots mit ihren Raten und dem Stand der
    Prüfungen. `bot_profiles_checked` und `senders_checked` sind falsch, wenn
    der Pull ohne `--audit-checks` lief oder die Prüfung scheiterte: dann steht
    jede Rate auf ungeprüften Sitzungen, und das gehört in den Befund."""
    profiles = ga4.get("bot_profiles") or {}
    section = ga4.get("senders") or {}
    return {
        "bot_profiles_checked": bool(profiles.get("checked")),
        "flagged_profiles": [p.get("label") for p in profiles.get("profiles") or []
                             if p.get("flagged")],
        "senders_checked": bool(section.get("measurable")),
        "double_counted_events": section.get("double_counted_events") or [],
        "variants": [{"key": v["key"], "label": v["label"], "filter": v["filter"],
                      "rates": rates(v["block"])} for v in variants(ga4)],
    }


def main(argv: list | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.exit("Aufruf: python3 -m audit.ga4_variants reporting/data/<run-id>/ga4.json")
    with open(args[0], encoding="utf-8") as f:
        print(json.dumps(compare(json.load(f)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
