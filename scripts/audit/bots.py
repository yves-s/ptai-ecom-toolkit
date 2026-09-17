#!/usr/bin/env python3
"""Automatisierten Traffic in den GA4-Zahlen erkennen, statt ihn zu behaupten.

**Warum das hier steht.** Am 08.09.2026 fragte ein Kunde, ob wir Bot-Traffic
herausrechnen, und nannte fuer seinen Shop 70 bis 80 Prozent. Die Antwort war
ein pauschales Ja. Sie war falsch: der Pull kann filtern (`bot_filter` in
`ga4_pull.py`), aber niemand hat je gemessen, **wonach** gefiltert werden
muesste. Ein Filter ohne Erkennung ist ein leeres Versprechen.

**Was diese Datei kann und was nicht.** Sie erkennt automatisierten Zugriff
nicht an dem, was er ist, sondern an dem, was er nicht tut: er kommt nicht
wieder, er bleibt nicht, und er kauft nicht. Ein Bot, der einen echten Browser
fernsteuert, faellt hier nicht auf. Die belastbare Gesamtzahl kommt weiterhin
nur aus Server- oder CDN-Logs, und wo die fehlen, bleibt der Anteil eine
Spanne, keine Zahl.

**Die drei Anzeichen, und warum gerade die.**

1. **Sitzungen je Nutzer.** Das staerkste Anzeichen, und das am haeufigsten
   uebersehene. Menschen kommen wieder: ueber einen Jahreszeitraum liegt jeder
   menschliche Kanal zwischen 1,2 und 2,5. Ausgerechnet Direct liegt bei
   Menschen am hoechsten, weil Direct die Wiederkehrer sind, die die Adresse
   selbst eintippen. Ein Direct-Kanal bei 1,02 sagt: 98 von 100 Sitzungen sind
   ein Besucher, der nie wiederkommt. Das ist kein Direktverkehr.
2. **Conversion Rate.** Ein Kanal, der ein Viertel der Shop-Rate oder weniger
   schafft und dabei Volumen traegt, kauft nicht.
3. **Engagement Rate.** GA4 zaehlt eine Sitzung als engagiert nach zehn
   Sekunden, zwei Seitenaufrufen oder einer Conversion. Wer keines davon
   schafft, hat die Seite geladen und war weg.

**Ein Anzeichen allein reicht nie.** Jedes hat eine harmlose Erklaerung: eine
Kampagne auf eine Landingpage bringt Einmalbesucher, ein Marken-Kanal
konvertiert schlecht, weil er Support-Anfragen traegt. Zwei zusammen haben
keine harmlose Erklaerung mehr.

**Und der Kanal wird nie ganz abgeschrieben.** In jedem auffaelligen Kanal
stecken echte Besuche. Deshalb liefert dieses Modul eine Spanne: die
Nicht-Engagement-Sitzungen als Untergrenze, die Sitzungen der auffaelligen
Kanaele als Obergrenze. Wer daraus eine einzelne Prozentzahl macht, behauptet
mehr, als gemessen ist.

**Das Geräteprofil, seit dem 13.09.2026.** Die drei Anzeichen oben sehen
automatisierten Zugriff nur als Kanal, und genau daran ist ein echter Audit
gescheitert. Ein einziges Geräteprofil trug die Hälfte aller Sitzungen, in
Wellen über Monate, und die Kanalprüfung schlug für Direct an. Die Maßnahme
lautete, Direct auszuschließen. Das hätte die echten Besuche in Direct samt
ihren Käufen entfernt und die Bot-Sitzungen in Unassigned stehen lassen. Und
jede Rate des Audits stand auf dem falschen
Nenner: die Add-to-Cart-Rate bei der Hälfte, die Conversion Rate auf Desktop
bei einem Viertel ihres Werts.

Ein Profil aus Bildschirmauflösung, Betriebssystem, Gerätekategorie und
Browser trifft die Bots selbst, nicht den Kanal, über den sie kommen. Es gilt
als automatisiert, wenn drei Dinge zusammenkommen: ein nennenswerter Anteil an
allen Sitzungen, kaum Engagement und praktisch kein Kauf. Ein menschliches
Gerät kauft, und deshalb nimmt ein Filter auf so ein Profil keinen Umsatz mit,
den das Ergebnis nicht ausweist.
"""
import statistics
from datetime import date

#: Unter diesem Wert kommt praktisch niemand wieder. Menschliche Kanaele
#: liegen ueber einen Jahreszeitraum zwischen 1,2 und 2,5.
SESSIONS_PER_USER_THRESHOLD = 1.10

#: Anteil der **Referenz**-Conversion-Rate, unter dem ein Kanal auffaellt.
#:
#: Die Referenz ist der Median der grossen Kanaele, nicht der Shop-Durchschnitt.
#: Das ist keine Feinheit, sondern der Unterschied zwischen erkennen und nicht
#: erkennen: traegt ein einzelner Kanal die Haelfte aller Sitzungen und kauft
#: nicht, zieht er den Shop-Durchschnitt so weit herunter, dass er selbst
#: dagegen unauffaellig wirkt. Genau das war am 08.09.2026 der Fall, ein Kanal
#: mit 57 Prozent der Sitzungen und einem Drittel der Conversion des naechsten
#: Kanals fiel gegen den Durchschnitt knapp nicht auf. Ein Median aus mehreren
#: Kanaelen laesst sich von einem einzelnen nicht verschieben.
CR_SHARE_THRESHOLD = 0.25

#: Engagement Rate, unter der ein Kanal auffaellt. GA4 zaehlt engagiert ab
#: zehn Sekunden, zwei Seitenaufrufen oder einer Conversion.
ENGAGEMENT_THRESHOLD = 0.20

#: Mindestanteil an allen Sitzungen, ab dem ein Kanal ueberhaupt geprueft
#: wird. Ohne ihn faellt jeder Kleinstkanal auf, weil acht Sitzungen ohne
#: Kauf rechnerisch null Prozent Conversion ergeben und nichts bedeuten.
MIN_SHARE = 0.01

#: Ab so vielen Anzeichen gilt ein Kanal als auffaellig.
SIGNAL_THRESHOLD = 2

#: Die Dimensionen eines Geräteprofils. Alle vier meldet der Browser selbst,
#: und erst zusammen trennen sie ein Bot-Netz von Menschen mit demselben
#: System: "Windows" allein trifft jeden Desktop-Kunden, Windows mit Chrome
#: und einer ungewöhnlichen Auflösung nur noch das Netz.
PROFILE_DIMENSIONS = ("screenResolution", "operatingSystem", "deviceCategory", "browser")

#: Der Schlüssel je Profil-Dimension in einer `bot_filter`-Regel, wie
#: `ga4_pull.FILTER_FIELDS` sie kennt.
PROFILE_RULE_KEYS = {
    "screenResolution": "screen_resolution_in",
    "operatingSystem": "operating_system_in",
    "deviceCategory": "device_in",
    "browser": "browser_in",
}

#: Höchstens so viele Käufe je Sitzung trägt ein automatisiertes Profil, einer
#: auf zehntausend. Menschliche Geräte kaufen im Bereich von Prozenten (Median
#: der Shopify-Shops rund 1,4 Prozent, `reference/metrics.md`). Null wäre zu
#: streng: ein paar echte Menschen mit demselben Gerät dürfen den Befund nicht
#: kippen, und jeder Kauf, den der Filter mitnähme, steht im Ergebnis.
MAX_PURCHASE_RATE = 0.0001

#: Ein Tag gehört zu einer Welle, wenn das Profil dort mehr als das Dreifache
#: seines mittleren Tagesanteils trägt und zugleich zehn Prozentpunkte darüber
#: liegt. Der Median ist der Normalzustand des Profils. Fehlt es an den meisten
#: Tagen, liegt er bei null, und dann entscheiden die zehn Punkte; ohne sie
#: wäre jeder Tag mit einem Prozent eine Welle.
WAVE_FACTOR = 3
WAVE_MARGIN = 0.10

#: So viele ruhige Tage darf eine Welle haben, ohne zu zerfallen. Ein Bot-Netz
#: setzt tageweise aus, und zwei Wellen im Abstand von zwei Tagen sind für jede
#: Rate derselbe Zeitraum.
WINDOW_GAP_DAYS = 2

#: Ein Zeitraum mit weniger als einem Prozent der Sitzungen des Profils
#: verschiebt keine Zahl und wäre nur Rauschen in der Liste.
MIN_WINDOW_SHARE = 0.01

#: Die Tagesabfrage je Profil holt nur Zeilen ab einem halben Prozent der
#: mittleren Tagessitzungen, mindestens zehn. Ein Profil darunter trägt an
#: keinem Tag einen auffälligen Anteil, und ohne die Schwelle wächst die
#: Antwort bei einem großen Shop auf Hunderttausende Zeilen. Die Summen der
#: Tagesreihe sind deshalb Untergrenzen und entscheiden nichts: jeder Kandidat
#: wird über den ganzen Zeitraum ohne Schwelle nachgezählt.
DAILY_FLOOR_SHARE = 0.005
MIN_DAILY_FLOOR = 10

#: Höchstens so viele Kandidaten werden nachgezählt, eine Abfrage je Profil.
MAX_CANDIDATES = 5


def _rate(numerator, denominator):
    """Anteil oder None. None heisst 'nicht berechenbar', nie null."""
    if not denominator:
        return None
    if numerator is None:
        return None
    return numerator / denominator


def reference_cr(kanaele: list[dict], gesamt_sitzungen: int) -> float | None:
    """Der Median der Conversion Rates aller Kanaele mit nennenswertem Anteil.

    Warum Median und nicht Durchschnitt: siehe `CR_SHARE_THRESHOLD`. Weniger als
    drei grosse Kanaele ergeben keinen tragfaehigen Median, dann faellt dieses
    Anzeichen aus, statt auf zwei Werte gestuetzt zu werden.
    """
    raten = []
    for k in kanaele:
        sitzungen = k.get("sessions") or 0
        if (_rate(sitzungen, gesamt_sitzungen) or 0) < MIN_SHARE:
            continue
        cr = _rate(k.get("purchases"), sitzungen)
        if cr is not None:
            raten.append(cr)
    if len(raten) < 3:
        return None
    raten.sort()
    mitte = len(raten) // 2
    if len(raten) % 2:
        return raten[mitte]
    return (raten[mitte - 1] + raten[mitte]) / 2


def check_channel(kanal: dict, gesamt_sitzungen: int,
                 gesamt_cr: float | None) -> dict:
    """Prueft einen Kanal auf die drei Anzeichen.

    `kanal` ist eine Zeile aus `ga4.json > channels`. Fehlende Kennzahlen
    schalten ihr Anzeichen ab, statt es als erfuellt zu werten: eine Property,
    die die Kaufmetrik verweigert, macht keinen Kanal verdaechtig. Die Käufe
    stehen unter `purchases`; ein `transactions` aus einem Snapshot von vor
    dem 11.09.2026 enthält Refunds und wird nicht gelesen.
    """
    sitzungen = kanal.get("sessions") or 0
    nutzer = kanal.get("total_users") or 0
    kaeufe = kanal.get("purchases")
    engagiert = kanal.get("engaged_sessions")

    per_user = _rate(sitzungen, nutzer)
    cr = _rate(kaeufe, sitzungen)
    engagement = kanal.get("engagement_rate")
    if engagement is None:
        engagement = _rate(engagiert, sitzungen)

    anzeichen = []
    if per_user is not None and per_user < SESSIONS_PER_USER_THRESHOLD:
        anzeichen.append(f"{per_user:.2f} Sitzungen je Nutzer, "
                         "praktisch niemand kommt wieder")
    if cr is not None and gesamt_cr and cr < gesamt_cr * CR_SHARE_THRESHOLD:
        anzeichen.append(f"{cr * 100:.2f} Prozent Conversion gegen "
                         f"{gesamt_cr * 100:.2f} Prozent im Mittel der "
                         "grossen Kanaele")
    if engagement is not None and engagement < ENGAGEMENT_THRESHOLD:
        anzeichen.append(f"{engagement * 100:.1f} Prozent der Sitzungen "
                         "engagiert")

    share = _rate(sitzungen, gesamt_sitzungen) or 0
    zu_klein = share < MIN_SHARE
    return {
        "channel": kanal.get("channel"),
        "sessions": sitzungen,
        "share_of_sessions": round(share, 4),
        "sessions_per_user": round(per_user, 3) if per_user else None,
        "conversion_rate": round(cr, 5) if cr is not None else None,
        "engagement_rate": round(engagement, 4) if engagement is not None else None,
        "signals": anzeichen,
        "suspicious": (not zu_klein) and len(anzeichen) >= SIGNAL_THRESHOLD,
        "too_small_to_judge": zu_klein,
    }


def analyze(ga4: dict) -> dict:
    """Der ganze Befund zu automatisiertem Traffic aus einem GA4-Snapshot.

    Liefert die Kanalpruefungen, die Spanne und die Saetze, mit denen das im
    Report steht. Ohne Kanaele oder ohne Sitzungen: ein Ergebnis, das sagt,
    dass nichts messbar war, nie eine Null.
    """
    kanaele = ga4.get("channels") or []
    totals = ga4.get("totals") or {}
    gesamt_sitzungen = totals.get("sessions") or sum(
        (k.get("sessions") or 0) for k in kanaele)
    if not kanaele or not gesamt_sitzungen:
        return {"measurable": False,
                "reason": "keine Kanalzahlen im Snapshot",
                "channels": [], "suspicious_channels": []}

    gesamt_kaeufe = totals.get("purchases")
    if gesamt_kaeufe is None:
        values = [k.get("purchases") for k in kanaele]
        gesamt_kaeufe = sum(w for w in values if w is not None) if any(
            w is not None for w in values) else None
    shop_cr = _rate(gesamt_kaeufe, gesamt_sitzungen)
    vergleich_cr = reference_cr(kanaele, gesamt_sitzungen)

    geprueft = [check_channel(k, gesamt_sitzungen, vergleich_cr)
                for k in kanaele]
    auffaellig = [k for k in geprueft if k["suspicious"]]

    obergrenze = sum(k["sessions"] for k in auffaellig)
    untergrenze = 0
    untergrenze_messbar = True
    for k in auffaellig:
        if k["engagement_rate"] is None:
            untergrenze_messbar = False
            continue
        untergrenze += int(k["sessions"] * (1 - k["engagement_rate"]))

    return {
        "measurable": True,
        "total_sessions": gesamt_sitzungen,
        "shop_conversion_rate": round(shop_cr, 5) if shop_cr else None,
        "reference_conversion_rate": (round(vergleich_cr, 5)
                                      if vergleich_cr else None),
        "channels": geprueft,
        "suspicious_channels": auffaellig,
        "upper_bound_sessions": obergrenze,
        "upper_bound_share": round(_rate(obergrenze, gesamt_sitzungen) or 0, 4),
        "lower_bound_sessions": untergrenze if untergrenze_messbar else None,
        "lower_bound_share": (round(_rate(untergrenze, gesamt_sitzungen) or 0, 4)
                              if untergrenze_messbar else None),
        "note": ("Die Spanne kommt aus den Kanalzahlen, nicht aus Server-Logs. "
                 "Die Obergrenze zaehlt alle Sitzungen der auffaelligen "
                 "Kanaele, in denen auch echte Besuche stecken. Die "
                 "Untergrenze zaehlt darin nur die Sitzungen ohne jedes "
                 "Engagement. Die belastbare Zahl braucht Server- oder "
                 "CDN-Daten."),
    }


def _percent(value: float, digits: int = 1) -> str:
    """Ein Anteil als deutsche Prozentangabe, etwa "48,1 Prozent"."""
    return f"{value * 100:.{digits}f}".replace(".", ",") + " Prozent"


def _date_de(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d.%m.%Y")


def profile_label(profile: dict) -> str:
    """Das Profil in einer Zeile, in der Reihenfolge von PROFILE_DIMENSIONS."""
    return " / ".join(str(profile.get(d) or "(not set)") for d in PROFILE_DIMENSIONS)


def daily_floor(total_sessions: int, days: int) -> int:
    """Die Mindestzahl an Sitzungen je Tag und Profil für die Tagesabfrage,
    siehe DAILY_FLOOR_SHARE."""
    if not days:
        return MIN_DAILY_FLOOR
    return max(MIN_DAILY_FLOOR, round(total_sessions / days * DAILY_FLOOR_SHARE))


def profile_candidates(daily_rows: list[dict], total_sessions: int) -> list[dict]:
    """Die Profile, die in der Tagesreihe wie automatisierter Zugriff aussehen.

    `daily_rows` sind Zeilen mit `date`, `profile` (die vier Dimensionen),
    `sessions`, `engaged_sessions` und `purchases`, so wie der Pull sie aus
    der Tagesabfrage baut. Kandidat ist ein Profil mit wenig Engagement,
    praktisch ohne Kauf und mit mindestens einem halben Prozent aller
    Sitzungen: die Hälfte der Schwelle aus MIN_SHARE, weil die Tagesreihe
    wegen DAILY_FLOOR_SHARE zu wenig zählt. Das Urteil fällt erst in
    assess_profile() auf den nachgezählten Summen.

    Fehlt eine Kennzahl, ist das Profil kein Kandidat: unbekannt ist nicht
    verdächtig. Rückgabe nach Sitzungen absteigend, höchstens MAX_CANDIDATES,
    je Profil mit `days` als Sitzungen je Tag für wave_windows().
    """
    merged = {}
    for row in daily_rows:
        profile = row.get("profile") or {}
        key = tuple(profile.get(d) for d in PROFILE_DIMENSIONS)
        entry = merged.setdefault(key, {
            "profile": {d: profile.get(d) for d in PROFILE_DIMENSIONS},
            "sessions": 0, "engaged_sessions": 0, "purchases": 0, "days": {}})
        sessions = row.get("sessions") or 0
        entry["sessions"] += sessions
        entry["days"][row["date"]] = entry["days"].get(row["date"], 0) + sessions
        for field in ("engaged_sessions", "purchases"):
            value = row.get(field)
            entry[field] = None if value is None or entry[field] is None else entry[field] + value

    candidates = []
    for entry in merged.values():
        if not total_sessions or entry["sessions"] < total_sessions * MIN_SHARE / 2:
            continue
        engagement = _rate(entry["engaged_sessions"], entry["sessions"])
        purchase_rate = _rate(entry["purchases"], entry["sessions"])
        if engagement is None or purchase_rate is None:
            continue
        if engagement < ENGAGEMENT_THRESHOLD and purchase_rate <= MAX_PURCHASE_RATE:
            candidates.append(entry)
    candidates.sort(key=lambda e: e["sessions"], reverse=True)
    return candidates[:MAX_CANDIDATES]


def _window(daily_totals: dict, profile_days: dict, start: str, end: str) -> dict:
    days = [d for d in sorted(daily_totals) if start <= d <= end and daily_totals[d]]
    sessions = sum(profile_days.get(d) or 0 for d in days)
    all_sessions = sum(daily_totals[d] for d in days)
    peak = max(days, key=lambda d: (profile_days.get(d) or 0) / daily_totals[d])
    return {
        "start": start,
        "end": end,
        "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
        "sessions": sessions,
        "share": round(_rate(sessions, all_sessions) or 0, 4),
        "peak_day": peak,
        "peak_sessions": profile_days.get(peak) or 0,
        "peak_share": round((profile_days.get(peak) or 0) / daily_totals[peak], 4),
    }


def wave_windows(daily_totals: dict, profile_days: dict) -> list[dict]:
    """Die Zeiträume, in denen ein Profil einen ungewöhnlichen Anteil trägt.

    `daily_totals` sind alle Sitzungen je Tag, `profile_days` die des Profils,
    beide mit ISO-Datum als Schlüssel. Ein Tag ohne Zeile des Profils zählt
    mit null. Welche Tage auffallen, regeln WAVE_FACTOR und WAVE_MARGIN; Tage
    im Abstand von höchstens WINDOW_GAP_DAYS bilden einen Zeitraum, und
    Zeiträume unter MIN_WINDOW_SHARE fallen weg.

    **Ein Profil ohne Welle läuft durchgehend.** Liegt es an jedem Tag gleich
    hoch, fällt kein Tag über seinen eigenen Normalanteil; dann ist der
    Zeitraum der erste bis letzte Tag mit Sitzungen des Profils. Eine leere
    Liste hieße sonst, das Profil sei nie aufgetreten.
    """
    dates = sorted(d for d in daily_totals if daily_totals[d])
    if not dates:
        return []
    share = {d: (profile_days.get(d) or 0) / daily_totals[d] for d in dates}
    median = statistics.median(share.values())
    threshold = max(WAVE_FACTOR * median, median + WAVE_MARGIN)

    runs = []
    for d in dates:
        if share[d] < threshold:
            continue
        if runs and (date.fromisoformat(d)
                     - date.fromisoformat(runs[-1][1])).days - 1 <= WINDOW_GAP_DAYS:
            runs[-1][1] = d
        else:
            runs.append([d, d])

    profile_total = sum(profile_days.get(d) or 0 for d in dates)
    windows = [_window(daily_totals, profile_days, start, end) for start, end in runs]
    windows = [w for w in windows if w["sessions"] >= profile_total * MIN_WINDOW_SHARE]
    if not windows:
        active = [d for d in dates if profile_days.get(d)]
        if active:
            windows = [_window(daily_totals, profile_days, active[0], active[-1])]
    return windows


def assess_profile(profile: dict, totals: dict, total_sessions: int,
                   channels: list | None = None, windows: list | None = None) -> dict:
    """Das Urteil über ein Profil aus seinen nachgezählten Summen.

    `totals` trägt `sessions`, `engaged_sessions`, `purchases` und optional
    `total_users` über den ganzen Zeitraum, `total_sessions` alle Sitzungen
    desselben Zeitraums. Auffällig (`flagged`) ist das Profil nur, wenn alle
    drei Prüfungen in `checks` greifen: mindestens MIN_SHARE aller Sitzungen,
    Engagement Rate unter ENGAGEMENT_THRESHOLD, höchstens MAX_PURCHASE_RATE
    Käufe je Sitzung. Eine fehlende Kennzahl lässt ihre Prüfung scheitern.
    """
    sessions = totals.get("sessions") or 0
    engaged = totals.get("engaged_sessions")
    purchases = totals.get("purchases")
    share = _rate(sessions, total_sessions)
    engagement = _rate(engaged, sessions)
    purchase_rate = _rate(purchases, sessions)
    checks = {
        "share": share is not None and share >= MIN_SHARE,
        "engagement": engagement is not None and engagement < ENGAGEMENT_THRESHOLD,
        "purchases": purchase_rate is not None and purchase_rate <= MAX_PURCHASE_RATE,
    }

    signals = []
    if share is not None:
        signals.append(f"{_percent(share)} aller Sitzungen")
    if engagement is not None:
        signals.append(f"Engagement Rate {_percent(engagement)}")
    if purchases is not None:
        signals.append("kein Kauf" if purchases == 0 else
                       f"{purchases} Käufe, {_percent(purchase_rate, 3)} der Sitzungen")

    return {
        "profile": {d: profile.get(d) for d in PROFILE_DIMENSIONS},
        "label": profile_label(profile),
        "sessions": sessions,
        "share_of_sessions": round(share, 4) if share is not None else None,
        "engaged_sessions": engaged,
        "engagement_rate": round(engagement, 4) if engagement is not None else None,
        "purchases": purchases,
        "purchase_rate": round(purchase_rate, 6) if purchase_rate is not None else None,
        "total_users": totals.get("total_users"),
        "channels": channels or [],
        "windows": windows or [],
        "checks": checks,
        "signals": signals,
        "flagged": all(checks.values()),
    }


def profile_rule(profile: dict, reason: str) -> dict:
    """Eine `bot_filter`-Regel, die genau dieses Profil beschreibt."""
    rule = {PROFILE_RULE_KEYS[d]: [profile[d]] for d in PROFILE_DIMENSIONS if profile.get(d)}
    rule["reason"] = reason
    return rule


def _reason(assessed: dict) -> str:
    text = f"Geräteprofil {assessed.get('label') or profile_label(assessed['profile'])}"
    if assessed.get("signals"):
        text += ": " + ", ".join(assessed["signals"])
    windows = assessed.get("windows") or []
    if windows:
        text += "; Zeiträume " + ", ".join(
            f"{_date_de(w['start'])} bis {_date_de(w['end'])}" for w in windows)
    return text


def filter_proposal(result: dict) -> dict | None:
    """Baut aus den auffaelligen Geräteprofilen einen `bot_filter`-Block, wie
    ihn `ga4_pull.py` erwartet.

    `result` ist der Abschnitt `ga4.json > bot_profiles` oder alles mit einer
    Liste `profiles` aus assess_profile(). **Nie aus einem Kanal.** Bis zum
    13.09.2026 baute diese Funktion die Regel aus den auffälligen Kanälen der
    Kanalprüfung, und ein echter Audit hat daraus empfohlen, Direct
    auszuschließen, mit den echten Besuchen darin (siehe Modulkopf). Ein
    Ergebnis ohne auffälliges Profil liefert deshalb keinen Vorschlag, auch
    wenn ein Kanal auffällt.

    **Der Vorschlag wird nie automatisch scharf geschaltet.** Ein Filter
    schneidet Sitzungen aus jeder spaeteren Zahl heraus, und wer sich darin
    irrt, verliert echte Besuche unsichtbar. Er gehoert vom Menschen in die
    Config uebernommen, nachdem er die Anzeichen gelesen hat.
    """
    flagged = [p for p in (result.get("profiles") or []) if p.get("flagged")]
    if not flagged:
        return None
    return {
        "enabled": False,
        "exclude": [profile_rule(p["profile"], _reason(p)) for p in flagged],
    }
