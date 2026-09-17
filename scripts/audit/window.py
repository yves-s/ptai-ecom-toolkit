# -*- coding: utf-8 -*-
"""Das Auswertungsfenster: zwölf Monate gegen das Vorjahr.

CLI: python3 -m audit.window <data-dir>

Warum es das gibt: die Baseline friert die volle Historie ein, das ist ihr
Zweck. Für Befunde und Massnahmen ist dieselbe Historie der falsche Bezug. Ein
Kanalanteil über fünf Jahre sagt nichts über heute, und in zehn Jahren liegen
eine Shop-Migration, Monate ohne Kaufmessung und ein laufender Preistest.

Das Fenster endet mit dem letzten vollen Monat, nicht mit dem Stichtag: ein
angebrochener Monat verwässert jeden Vergleich.
"""
import json
from pathlib import Path


def months(bis_einschliesslich, count=12):
    """Die letzten `anzahl` Monatsschlüssel bis einschliesslich `bis`."""
    j, m = int(bis_einschliesslich[:4]), int(bis_einschliesslich[5:7])
    out = []
    for _ in range(count):
        out.append(f"{j:04d}-{m:02d}")
        m -= 1
        if m == 0:
            j, m = j - 1, 12
    return list(reversed(out))


def build(data_dir):
    """Zwei Fenster plus die Störungen darin, aus den Snapshots gerechnet."""
    d = Path(data_dir)
    ga4 = json.loads((d / "ga4.json").read_text(encoding="utf-8"))
    shop = json.loads((d / "shopify.json").read_text(encoding="utf-8"))
    gm = {m["month"]: m for m in ga4["by_month"]}
    sm = {m["month"][:7]: m for m in shop["by_month"]}
    # Sitzungen bevorzugt aus der Zählung des Shops. Shopify trennt
    # automatisierten Verkehr selbst (`human_or_bot_session`), Analytics nicht.
    # Die Conversion Rate eines Shops gegen eine ungefilterte Analytics-Zahl zu
    # rechnen ergibt eine Rate, die um den Bot-Anteil zu niedrig liegt; im
    # ersten echten Lauf um den Faktor drei bis vier. Fehlt die Shop-Reihe,
    # bleibt Analytics die Quelle, und `sessions_quelle` sagt, welche es war.
    shm = {m["month"][:7]: m for m in (shop.get("sessions_by_month") or [])}
    source = "shop" if shm else "analytics"

    def sitzungen(month):
        """Sitzungen eines Monats aus der belastbareren der beiden Quellen."""
        if source == "shop":
            return shm.get(month, {}).get("sessions") or 0
        return gm.get(month, {}).get("sessions") or 0

    # Letzter voller Monat: der Snapshot endet am 06.09., also ist 08 der letzte.
    end = max(m for m in sm if (sm[m].get("orders") or 0))
    if shop["period"]["end"][8:10] != "31":
        end = months(end, 2)[0]

    jetzt, previous_year = months(end, 12), months(months(end, 13)[0], 12)

    def purchases(ms):
        """Käufe aus Analytics über die Monate, None statt 0, wenn keiner sie trägt.

        Das Feld heißt seit dem 11.09.2026 `purchases`. Ältere Snapshots tragen
        `transactions`, und darin zählt GA4 Refunds mit; die Zahl wird nicht
        als Käufe gelesen. Null hieße "kein Kauf gemessen" und ergäbe im
        Report eine Zuordnungslücke von 100 Prozent.
        """
        measured = [gm[m]["purchases"] for m in ms
                    if gm.get(m, {}).get("purchases") is not None]
        return sum(measured) if measured else None

    def total(ms):
        s = lambda k: sum(sm.get(m, {}).get(k) or 0 for m in ms)
        g = lambda k: sum(gm.get(m, {}).get(k) or 0 for m in ms)
        u, b = s("total_sales"), s("orders")
        ses = sum(sitzungen(m) for m in ms)
        return {"monate": ms, "umsatz": u, "netto": s("net_sales"), "bestellungen": b,
                "sessions": ses, "sessions_quelle": source,
                "ga4_sessions": g("sessions"), "ga4_kaeufe": purchases(ms),
                "ga4_umsatz": g("purchase_revenue"),
                "aov": u / b if b else None,
                "conversion": b / ses if ses else None}

    a, v = total(jetzt), total(previous_year)

    # Störungen im Fenster benennen, statt die Zahlen still zu verrechnen.
    stoerung = []
    for m in jetzt:
        o = sm.get(m, {}).get("orders") or 0
        if not o:
            continue
        # Ein Monat, den Analytics gar nicht führt, ist ohne Kaufmessung. Ein
        # Monat, der da ist, aber keine Käufe trägt (abgelehnte Metrik oder ein
        # Snapshot von vor dem 11.09.2026), ist nicht gemessen: dazu gibt es
        # keine Aussage.
        if m in gm and gm[m].get("purchases") is None:
            continue
        t = gm.get(m, {}).get("purchases") or 0
        if not t:
            stoerung.append((m, "keine Kaufmessung in Analytics"))
        elif t / o < 0.5:
            stoerung.append((m, f"nur {t/o:.0%} der Bestellungen zugeordnet"))
    # Aufgeblähte Sessions: Monat gegen denselben Monat im Vorjahr.
    #
    # **Nur, wenn die Sitzungen aus Analytics kommen.** Der Test sucht ein
    # Mess-Artefakt, keinen Geschäftsverlauf. Zählt der Shop selbst und filtert
    # dabei automatisierten Verkehr, ist ein deutliches Plus gegen den
    # Vorjahresmonat schlicht Wachstum, und wer es herausrechnet, meldet einen
    # Rückgang, den es nicht gibt: im ersten echten Lauf wurde aus einem
    # einstelligen Minus bei den Sitzungen so ein doppelt so grosses.
    blase = []
    for m in (jetzt if source == "analytics" else []):
        v_m = f"{int(m[:4])-1}-{m[5:7]}"
        a_s, v_s = sitzungen(m), sitzungen(v_m)
        if v_s and a_s / v_s > 1.35:
            blase.append((m, a_s / v_s))

    def delta(k):
        x, y = a.get(k), v.get(k)
        return (x / y - 1) if (x and y) else None

    return {"jetzt": a, "vorjahr": v, "ende": end,
            "label": f"{jetzt[0][5:7]}/{jetzt[0][:4]} bis {jetzt[-1][5:7]}/{jetzt[-1][:4]}",
            "label_vorjahr": f"{previous_year[0][5:7]}/{previous_year[0][:4]} bis {previous_year[-1][5:7]}/{previous_year[-1][:4]}",
            "stoerungen": stoerung, "session_blase": blase,
            "sessions_quelle": source,
            "delta": {k: delta(k) for k in ("umsatz", "netto", "bestellungen", "sessions",
                                            "ga4_kaeufe", "aov", "conversion")},
            "bereinigt": _adjusted(sitzungen, sm, jetzt, previous_year,
                                     {m for m, _ in blase})}


def _adjusted(sitzungen, sm, jetzt, previous_year, blase):
    """Das bereinigte Fenster: dieselben Kalendermonate auf beiden Seiten,
    ohne die Monate mit aufgeblähten Sessions.

    Bestellungen und Sessions werden über genau dieselben Monate gerechnet.
    Eine Conversion aus zwölf Monaten Bestellungen und acht Monaten Sessions
    wäre eine Zahl, die es nicht gibt."""
    raus = {m[5:7] for m in blase}
    mj = [m for m in jetzt if m[5:7] not in raus]
    mv = [m for m in previous_year if m[5:7] not in raus]
    ses = lambda ms: sum(sitzungen(m) for m in ms)
    best = lambda ms: sum(sm.get(m, {}).get("orders") or 0 for m in ms)
    sj, sv, bj, bv = ses(mj), ses(mv), best(mj), best(mv)
    cj = bj / sj if sj else None
    cv = bv / sv if sv else None
    return {"monate": len(mj), "ausgelassen": sorted(raus),
            "sessions": sj, "sessions_vorjahr": sv,
            "sessions_delta": (sj / sv - 1) if sv else None,
            "bestellungen": bj, "bestellungen_vorjahr": bv,
            "bestellungen_delta": (bj / bv - 1) if bv else None,
            "conversion": cj, "conversion_vorjahr": cv,
            "conversion_delta": (cj / cv - 1) if (cj and cv) else None}


if __name__ == "__main__":
    import sys
    f = build(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(f"Fenster: {f['label']} gegen {f['label_vorjahr']}")
    for k, v in f["delta"].items():
        if v is not None:
            print(f"  {k:<14} {v * 100:+7.1f} %")
    if f["stoerungen"]:
        print("Störungen im Fenster:")
        for m, g in f["stoerungen"]:
            print(f"  {m}  {g}")
    b = f["bereinigt"]
    if b["ausgelassen"]:
        print(f"Bereinigt auf {b['monate']} Monate (ohne {', '.join(b['ausgelassen'])}): "
              f"Sessions {b['sessions_delta'] * 100:+.1f} %, "
              f"Bestellungen {b['bestellungen_delta'] * 100:+.1f} %")
