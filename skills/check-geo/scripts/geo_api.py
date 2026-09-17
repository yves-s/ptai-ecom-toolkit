#!/usr/bin/env python3
"""GEO-Plattform-Abfrage über die offiziellen APIs statt Browser.

Aufruf:
  geo_api.py --platform <chatgpt|perplexity|google-ai> --key <api-key> \
             --query "<text>" [--timeout 60]
  geo_api.py --check <platform> <api-key>

Schreibt ein normalisiertes JSON-Objekt nach stdout:
  {"platform": "...", "answer_text": "...", "citations": ["url", ...], "model": "..."}

chatgpt läuft über die OpenAI Responses API mit Websuche, perplexity über
chat/completions (Modell sonar), google-ai über Gemini mit
Google-Search-Grounding als Proxy für Googles AI-Schicht. Nur Stdlib (urllib),
keine Abhängigkeiten. Exit 0 bei Erfolg, Exit 1 mit klarer Fehlerzeile sonst.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Geteilte Helfer aus dem Plugin-Root (scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from api_common import describe_error  # noqa: E402
from audit import env as operator_env  # noqa: E402

PLATFORMS = ("chatgpt", "perplexity", "google-ai")

#: Woher der Key je Plattform kommt. Als Argument stünde er in der
#: Prozessliste jedes Nutzers auf demselben Rechner; genau so ist am
#: 06.09.2026 ein Key in ein Sitzungsprotokoll geraten.
KEY_ENV = {"chatgpt": "PTAI_OPENAI_KEY",
           "perplexity": "PTAI_PERPLEXITY_KEY",
           "google-ai": "PTAI_GEMINI_KEY"}

OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-4o-mini"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"
# Stand 06.09.2026, am ersten echten Lauf gegen die APIs geprüft:
# "sonar" ist aktuell und antwortet. "gemini-2.0-flash" war abgekündigt und
# liefert 404; die API empfiehlt selbst "gemini-3.6-flash", das hier jetzt
# steht. Weiter ungeprüft: ob gpt-4o-mini den Tool-Typ "web_search" oder nur
# "web_search_preview" akzeptiert (der Retry unten deckt beides ab), denn der
# Check unten fährt bewusst ohne Websuche-Tool.
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{GEMINI_MODEL}:generateContent")


def post_json(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        try:
            return json.load(resp)
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ungültige JSON-Antwort der API: {exc}") from exc


#: Ein blanker Hostname, so wie Google die Quelldomain neben der Redirect-URL
#: mitgibt. Bewusst streng: kein Schema, kein Pfad, kein Leerzeichen, am Ende
#: eine TLD aus Buchstaben. "reddit.com" passt, "Ledertasche | Startseite" nicht.
_HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]+(?:\.(?!-)[a-z0-9-]+)*\.[a-z]{2,}$")


def _ist_hostname(value: str) -> bool:
    return bool(value) and len(value) <= 253 and bool(_HOSTNAME.match(value))


def _dedupe(urls: list) -> list:
    """Dubletten raus, Reihenfolge erhalten."""
    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """Fehler-Body als Text lesen. Der Body eines HTTPError ist nur einmal
    lesbar; wer ihn hier liest, darf die Exception danach nicht mehr an
    describe_error geben (das liest erneut und bekäme nichts)."""
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _error_message(code: int, body_text: str) -> str:
    """Meldung aus einem bereits gelesenen Error-Body ziehen. Gleiche Logik
    wie api_common.describe_error (alle drei APIs nutzen die Error-Shape
    {"error": {"message": ...}}), nur ohne erneutes read()."""
    try:
        msg = (json.loads(body_text).get("error") or {}).get("message")
        if msg:
            return msg
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    return f"HTTP {code}"


def query_perplexity(key: str, query: str, timeout: int) -> dict:
    body = {"model": PERPLEXITY_MODEL,
            "messages": [{"role": "user", "content": query}]}
    resp = post_json(PERPLEXITY_URL, {"Authorization": f"Bearer {key}"},
                     body, timeout)
    answer = ""
    choices = resp.get("choices") or []
    if choices and isinstance(choices[0], dict):
        answer = ((choices[0].get("message") or {}).get("content")) or ""
    # Quellen liefert Perplexity je nach API-Stand als Top-Level "citations"
    # (Liste von URL-Strings) oder "search_results" (Liste von Objekten mit
    # "url"). Beide Formen einsammeln; welche im Pilot wirklich kommt, dort
    # validieren.
    urls = []
    for item in resp.get("citations") or []:
        if isinstance(item, str) and item:
            urls.append(item)
        elif isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    for item in resp.get("search_results") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    return {"answer_text": answer, "citations": _dedupe(urls),
            "model": resp.get("model") or PERPLEXITY_MODEL}


def query_chatgpt(key: str, query: str, timeout: int) -> dict:
    body = {"model": OPENAI_MODEL, "tools": [{"type": "web_search"}],
            "input": query}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = post_json(OPENAI_URL, headers, body, timeout)
    except urllib.error.HTTPError as exc:
        # Ältere Deployments kennen den Tool-Typ "web_search" nicht und
        # verlangen "web_search_preview". Bei einem 400, der den Tool-Typ
        # nennt, genau einmal mit dem alten Namen nachfassen; jeder andere
        # Fehler wird zur klaren Meldung (Body ist hier schon gelesen,
        # deshalb nicht erneut an describe_error geben).
        detail = _read_error_body(exc)
        if exc.code == 400 and "web_search" in detail:
            body["tools"] = [{"type": "web_search_preview"}]
            resp = post_json(OPENAI_URL, headers, body, timeout)
        else:
            raise RuntimeError(_error_message(exc.code, detail)) from exc
    # Responses-API: output ist eine Liste von Items; Items vom Typ "message"
    # tragen content-Parts vom Typ "output_text" mit text und annotations,
    # darin url_citation-Objekte mit url. Alles defensiv, Felder können fehlen.
    answer_parts = []
    urls = []
    for item in resp.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            if part.get("text"):
                answer_parts.append(part["text"])
            for ann in part.get("annotations") or []:
                if (isinstance(ann, dict) and ann.get("type") == "url_citation"
                        and ann.get("url")):
                    urls.append(ann["url"])
    return {"answer_text": "\n".join(answer_parts), "citations": _dedupe(urls),
            "model": resp.get("model") or OPENAI_MODEL}


def query_google_ai(key: str, query: str, timeout: int) -> dict:
    # Tool-Form {"google_search": {}} gilt für die 2.0er-Modelle; die 1.5er
    # brauchten stattdessen google_search_retrieval. Key im Header statt als
    # ?key=-Query-Parameter: laut Gemini-Doku gleichwertig und hält den Key
    # aus URL-Logs raus.
    body = {"contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}]}
    resp = post_json(GEMINI_URL, {"x-goog-api-key": key}, body, timeout)
    candidates = resp.get("candidates") or []
    cand = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    parts = (cand.get("content") or {}).get("parts") or []
    answer = "\n".join(p["text"] for p in parts
                       if isinstance(p, dict) and p.get("text"))
    # groundingMetadata kann komplett fehlen (kein Grounding-Treffer für die
    # Query), das ist kein Fehler.
    #
    # Die web.uri-Werte sind immer Google-Redirect-URLs auf
    # vertexaisearch.cloud.google.com, nie die echte Site-URL. Die Skill wirft
    # diesen Host beim Domain-Abgleich aus und braucht deshalb die Quelldomain
    # als eigenen Eintrag. Am 07.09.2026 gegen die Live-API geprüft: die steht
    # jetzt in web.title ("reddit.com", "fachblog.example"), das früher
    # dokumentierte web.domain liefert die API nicht mehr. Ohne diesen Zweig
    # bestünde jede Citation-Liste nur aus Redirect-URLs, die Skill fände nie
    # eine Übereinstimmung, und Google-AI meldete für jeden Shop "nicht
    # zitiert" statt eines gemessenen Ergebnisses.
    urls = []
    meta = cand.get("groundingMetadata") or {}
    for chunk in meta.get("groundingChunks") or []:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") or {}
        if web.get("uri"):
            urls.append(web["uri"])
        # Beide Feldnamen, damit ein weiterer API-Wechsel nichts kaputt macht.
        # Ein title, der kein Hostname ist (ein Seitentitel etwa), bleibt
        # draußen: er würde den Domain-Abgleich auf Text laufen lassen.
        for feld in ("domain", "title"):
            value = str(web.get(feld) or "").strip().lower()
            if _ist_hostname(value):
                urls.append(value)
    return {"answer_text": answer, "citations": _dedupe(urls),
            "model": resp.get("modelVersion") or GEMINI_MODEL}


def check(platform: str, key: str, timeout: int) -> None:
    """Minimaler, billiger Call je Plattform: eine OK-/Fehlerzeile, Exit 0/1."""
    try:
        if platform == "perplexity":
            # max_tokens muss mindestens 16 sein, Perplexity lehnt kleinere
            # Werte mit 400 ab. Mit 1 meldete der Check einen gültigen Key
            # als nicht erreichbar (gefunden am 06.09.2026).
            body = {"model": PERPLEXITY_MODEL,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 16}
            resp = post_json(PERPLEXITY_URL, {"Authorization": f"Bearer {key}"},
                             body, timeout)
            model = resp.get("model") or PERPLEXITY_MODEL
        elif platform == "chatgpt":
            # Bewusst ohne Websuche-Tool: der Check prüft Key und Endpoint,
            # nicht das Tool. 16 ist das Minimum für max_output_tokens.
            body = {"model": OPENAI_MODEL, "input": "ping",
                    "max_output_tokens": 16}
            resp = post_json(OPENAI_URL, {"Authorization": f"Bearer {key}"},
                             body, timeout)
            model = resp.get("model") or OPENAI_MODEL
        else:
            body = {"contents": [{"parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1}}
            resp = post_json(GEMINI_URL, {"x-goog-api-key": key}, body, timeout)
            model = resp.get("modelVersion") or GEMINI_MODEL
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        sys.exit(f"Fehler: {platform}-API nicht erreichbar: {describe_error(exc)}")
    print(f"OK: {platform}-API erreichbar (Modell: {model})")


def resolve_key(platform: str, from_argument: str | None, workspace=".") -> str:
    """Der Key über dieselbe Suche wie jeder Betreiber-Schlüssel, das Argument zuletzt.

    Ein per `--key` übergebener Schlüssel steht in `ps` und damit für jeden
    Nutzer der Maschine offen. Die alte Aufrufform läuft weiter, warnt aber.
    `-` ist der Platzhalter der Skill und heißt "kein Argument"; bis 11.09.2026
    ging er als wörtlicher Key an die API, wenn sonst keiner stand.

    Wird trotzdem ein echtes Argument übergeben, obwohl ein Key an anderer
    Stelle gefunden wurde, gewinnt bis 11.09.2026 still der gefundene Key: ein
    `--check <platform> <key>` prüfte dann einen anderen Key als den
    übergebenen und konnte ein OK für den falschen Key melden. Jetzt steht
    dafür ein Hinweis auf stderr, der die Quelle nennt, nie den Wert.
    """
    found = (operator_env.get(KEY_ENV[platform], workspace) or "").strip()
    if found:
        if from_argument and from_argument != "-":
            quelle = operator_env.origin(KEY_ENV[platform], workspace)
            print(f"Hinweis: --key wird ignoriert, {KEY_ENV[platform]} kommt "
                  f"aus {quelle}.", file=sys.stderr)
        return found
    if from_argument and from_argument != "-":
        print(f"Warnung: der Key wurde als Argument übergeben und steht damit "
              f"in der Prozessliste. Besser: {KEY_ENV[platform]} in die .env "
              f"eintragen.", file=sys.stderr)
        return from_argument
    sys.exit(f"Fehler: kein Key für {platform}. {KEY_ENV[platform]} in die .env "
             f"des Workspace oder zentral in ~/.config/ptai-ecom/.env eintragen.")


def main():
    parser = argparse.ArgumentParser(
        description="GEO-Plattform-Abfrage (ChatGPT, Perplexity, Google-AI) "
                    "über die offiziellen APIs."
    )
    parser.add_argument("--platform", choices=PLATFORMS, help="Ziel-Plattform")
    parser.add_argument("--key", help="API-Key der Plattform. Besser leer lassen: der Key kommt aus PTAI_OPENAI_KEY, PTAI_PERPLEXITY_KEY oder PTAI_GEMINI_KEY, aus der Umgebung, der .env des Workspace oder zentral aus ~/.config/ptai-ecom/.env")
    parser.add_argument("--query",
                        help="Query wörtlich, wie sie in der Config steht")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Timeout je API-Call in Sekunden (Default 60)")
    parser.add_argument("--check", nargs=2, metavar=("PLATFORM", "KEY"),
                        help="Nur Auth per Mini-Call testen, Exit 0/1. Für KEY genügt '-', wenn der Key aus der Umgebung, der .env des Workspace oder zentral aus ~/.config/ptai-ecom/.env kommt")
    args = parser.parse_args()

    if args.check:
        platform, key = args.check
        if platform not in PLATFORMS:
            parser.error(f"--check: unbekannte Plattform '{platform}' "
                         f"(erlaubt: {', '.join(PLATFORMS)})")
        check(platform, resolve_key(platform, key), args.timeout)
        return

    missing = [name for name, val in
               (("--platform", args.platform), ("--query", args.query))
               if not val]
    if missing:
        parser.error(f"ohne --check erforderlich: {', '.join(missing)}")

    handlers = {"chatgpt": query_chatgpt, "perplexity": query_perplexity,
                "google-ai": query_google_ai}
    try:
        key = resolve_key(args.platform, args.key)
        result = handlers[args.platform](key, args.query, args.timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        sys.exit(f"Fehler: {args.platform}-Abfrage fehlgeschlagen: "
                 f"{describe_error(exc)}")

    print(json.dumps({"platform": args.platform, **result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
