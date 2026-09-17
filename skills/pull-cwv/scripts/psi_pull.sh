#!/usr/bin/env bash
# CWV-Snapshot über die PageSpeed-Insights-API (CrUX-Felddaten + Lighthouse-Lab)
# plus CrUX-Wochenhistorie je Origin.
#
# Aufruf:
#   psi_pull.sh <out-dir> - <url> [<url> ...]
#   psi_pull.sh <out-dir> - <page_type>=<url> [<page_type>=<url> ...]
#   psi_pull.sh --check -
#
# Ein URL-Argument ohne "=" bleibt eine nackte URL und bekommt den Seitentyp
# "unnamed", damit bestehende Aufrufe ohne Seitentyp-Zuordnung unverändert
# weiterlaufen. Mit "=" steht davor der Seitentyp (aus config.page_types()),
# dahinter die URL.
#
# Schreibt <out-dir>/cwv.json mit fetched_at, strategy, einem pages-Array
# (ein Eintrag je URL: page_type, field_data plus lab, oder ein error-Eintrag)
# und einem historie-Array (ein Eintrag je eindeutigem Origin aus den
# übergebenen URLs: rund 25 Wochen CrUX-Wochenwerte, oder ein error-Eintrag,
# wenn der Origin zu wenig Traffic für die Historie hat). CWV ist punktuell,
# kein period-Block, kein comparison: der Report vergleicht gegen den
# Vormonats-Snapshot. Ein Fehler bei einer URL oder einem Origin ist nie
# fatal für die anderen; --check testet nur Auth plus eine Mini-Query
# (Exit 0/1) für den Setup-Wizard.
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
PLUGIN_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PSI_ENDPOINT="https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_HISTORY_ENDPOINT="https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
# Lighthouse braucht auf einer schweren Storefront regelmäßig länger als
# eine Minute. Mit 60s liefen am 06.09.2026 zwei von sechs Seitentypen zweimal
# hintereinander in den Timeout. Per Env übersteuerbar, vor allem für Tests.
CURL_MAX_TIME="${PSI_CURL_MAX_TIME:-180}"
STATUS_MARKER="___HTTP_STATUS___"

usage() {
  cat >&2 <<EOF
Usage:
  ${SCRIPT_NAME} <out-dir> - <url> [<url> ...]
  ${SCRIPT_NAME} <out-dir> - <page_type>=<url> [<page_type>=<url> ...]
  ${SCRIPT_NAME} --check -

  <out-dir>          Zielordner für cwv.json (wird bei Bedarf angelegt)
  -                  Platzhalter für den API-Key; der Key kommt aus der
                      Umgebung, der .env des Workspace oder
                      ~/.config/ptai-ecom/.env. Ein hier übergebener Key
                      funktioniert weiter, steht dann aber in der
                      Prozessliste. Gilt auch für die CrUX-History-API, die
                      im Key freigeschaltet sein muss
  <url...>           eine oder mehrere Seiten-URLs (https://...); ohne "="
                      bekommt jede den Seitentyp "unnamed"
  <page_type>=<url>  URL mit zugeordnetem Seitentyp, aus config.page_types()

  --check     schneller Auth-Test gegen https://example.com/ (nur Performance-
              Kategorie), gibt eine OK-/Fehlerzeile aus, Exit 0/1
EOF
}

# jq und curl sind dokumentierte Voraussetzungen des Plugins (README). Ohne sie
# kann das Script weder abrufen noch parsen, deshalb hart und früh abbrechen.
for bin in curl jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Fehler: '${bin}' ist nicht installiert, wird aber benötigt." >&2
    exit 1
  fi
done

url_encode() {
  jq -rn --arg v "$1" '$v|@uri'
}

# Der Key geht als Header über eine curl-Konfiguration auf stdin, nie in die URL.
# In der URL stand er in der Argumentliste von curl und damit in der Prozessliste
# jedes Nutzers dieses Rechners (`ps -ef`). printf ist in bash eingebaut und
# startet keinen eigenen Prozess, der Key erscheint also in keiner Argumentliste.
# PageSpeed Insights und die CrUX-API lesen beide X-Goog-Api-Key: am 11.09.2026
# mit einem ungültigen Key geprüft, beide antworten API_KEY_INVALID statt
# "unregistered callers". Anführungszeichen und Backslashes werden für das
# Format der curl-Konfiguration maskiert.
key_config() {
  local key="${1//\\/\\\\}"
  key="${key//\"/\\\"}"
  printf 'header = "X-Goog-Api-Key: %s"\n' "$key"
}

# Ein PSI-Call. Muss als normale Anweisung aufgerufen werden (nicht in $(...)),
# sonst laufen die Variablenzuweisungen unten in einer Subshell und gehen beim
# Verlassen verloren. Setzt bei Erfolg HTTP_STATUS und RESPONSE_BODY, Rückgabe
# 1 bei einem curl-Fehler (Timeout, Netzwerk).
fetch_page() {
  local api_url="$1"
  local raw
  if raw="$(key_config "$api_key" | curl -s --config - --max-time "$CURL_MAX_TIME" -w "\n${STATUS_MARKER}%{http_code}" "$api_url")"; then
    HTTP_STATUS="${raw##*"$STATUS_MARKER"}"
    RESPONSE_BODY="${raw%$'\n'"$STATUS_MARKER"*}"
    return 0
  fi
  HTTP_STATUS=""
  RESPONSE_BODY=""
  return 1
}

# Ein CrUX-History-Call (POST, JSON-Body), sonst dasselbe Muster wie
# fetch_page und aus demselben Grund (Subshell-Falle) als normale Anweisung
# aufgerufen. formFactor PHONE passend zu strategy=mobile oben: dieselbe
# Zielgruppe wie der Momentwert, nicht die kombinierte CrUX-Population aus
# allen Geräten.
fetch_history() {
  local origin="$1"
  local body
  body=$(jq -nc --arg origin "$origin" \
    '{origin: $origin, formFactor: "PHONE", metrics: ["largest_contentful_paint","interaction_to_next_paint","cumulative_layout_shift"]}')
  local raw
  if raw="$(key_config "$api_key" | curl -s --config - --max-time "$CURL_MAX_TIME" -w "\n${STATUS_MARKER}%{http_code}" \
    -H "Content-Type: application/json" -d "$body" \
    "${CRUX_HISTORY_ENDPOINT}")"; then
    HTTP_STATUS="${raw##*"$STATUS_MARKER"}"
    RESPONSE_BODY="${raw%$'\n'"$STATUS_MARKER"*}"
    return 0
  fi
  HTTP_STATUS=""
  RESPONSE_BODY=""
  return 1
}

# Der Key kommt bevorzugt aus der Umgebung, dann über dieselbe Suche wie jeder
# Betreiber-Schlüssel (Workspace-.env, dann ~/.config/ptai-ecom/.env). Als
# Argument steht er in der Prozessliste jedes Nutzers auf demselben Rechner
# (`ps -ef`), und genau so ist am 06.09.2026 ein Key in ein Sitzungsprotokoll
# geraten und musste rotiert werden. Die alte Aufrufform bleibt lauffähig,
# warnt aber. `-` ist der Platzhalter und heißt "kein Argument".
resolve_api_key() {
  local from_argument="${1:-}"
  local found=""
  local lookup_failed=0
  if [[ -n "${PTAI_PSI_KEY:-}" ]]; then
    printf '%s' "$PTAI_PSI_KEY"
    return 0
  fi
  # Die Suche selbst kann scheitern (python3 fehlt, der Import bricht). Das ist
  # etwas anderes als "kein Schlüssel eingetragen" und bekommt unten eine
  # eigene Meldung: bis 11.09.2026 stand dann "kein API-Key" da, und man
  # suchte den Fehler in einer .env, in der alles stimmte.
  found="$(PYTHONPATH="${PLUGIN_ROOT}/scripts" python3 -c \
    'import sys; from audit import env; sys.stdout.write(env.get("PTAI_PSI_KEY") or "")' \
    2>/dev/null)" || lookup_failed=1
  if [[ -n "$found" ]]; then
    printf '%s' "$found"
    return 0
  fi
  if [[ -n "$from_argument" && "$from_argument" != "-" ]]; then
    echo "Warnung: der API-Key wurde als Argument übergeben und steht damit in der Prozessliste. Besser: PTAI_PSI_KEY in die .env eintragen und '-' als Platzhalter übergeben." >&2
    printf '%s' "$from_argument"
    return 0
  fi
  if [[ "$lookup_failed" -eq 1 ]]; then
    echo "Fehler: die Schlüsselsuche ist technisch gescheitert (python3 fehlt oder ${PLUGIN_ROOT}/scripts/audit ist nicht importierbar). Ob PTAI_PSI_KEY eingetragen ist, bleibt damit ungeprüft. Nachprüfen mit: PYTHONPATH=\"${PLUGIN_ROOT}/scripts\" python3 -m audit.env" >&2
    return 1
  fi
  echo "Fehler: kein API-Key. PTAI_PSI_KEY in die .env des Workspace oder zentral in ~/.config/ptai-ecom/.env eintragen." >&2
  return 1
}

# --- Check-Modus -------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
  api_key="$(resolve_api_key "${2:-}")" || exit 2
  encoded_url="$(url_encode "https://example.com/")"
  api_url="${PSI_ENDPOINT}?url=${encoded_url}&strategy=mobile&category=performance"

  if ! fetch_page "$api_url"; then
    echo "Fehler: PSI-Check fehlgeschlagen (curl-Fehler, kein HTTP-Status)" >&2
    exit 1
  fi

  if [[ "$HTTP_STATUS" != 2* ]] || ! jq -e . >/dev/null 2>&1 <<<"$RESPONSE_BODY"; then
    err_msg=$(jq -r '.error.message // "unbekannter Fehler"' <<<"$RESPONSE_BODY" 2>/dev/null || echo "unbekannter Fehler")
    echo "Fehler: PSI-Check fehlgeschlagen (HTTP ${HTTP_STATUS}: ${err_msg})" >&2
    exit 1
  fi

  score=$(jq -r '.lighthouseResult.categories.performance.score // empty' <<<"$RESPONSE_BODY")
  if [[ -z "$score" ]]; then
    echo "Fehler: PSI-Check fehlgeschlagen (kein Performance-Score in der Antwort)" >&2
    exit 1
  fi
  echo "OK: PSI erreichbar, Performance-Score example.com (mobile) = ${score}"
  exit 0
fi

# --- Pull-Modus ----------------------------------------------------------
if [[ $# -lt 3 ]]; then
  usage
  exit 2
fi

out_dir="$1"
api_key="$(resolve_api_key "$2")" || exit 2
shift 2

# Seitentyp=URL-Paare auseinanderziehen. Ein Argument ohne "=" bleibt eine
# nackte URL (bestehende Aufrufe ohne Seitentyp-Zuordnung) und bekommt den
# Platzhalter-Seitentyp "unnamed", nie einen leeren oder erratenen Wert.
page_types=()
urls=()
for arg in "$@"; do
  if [[ "$arg" == *=* ]]; then
    page_types+=("${arg%%=*}")
    urls+=("${arg#*=}")
  else
    page_types+=("unnamed")
    urls+=("$arg")
  fi
done

mkdir -p "$out_dir"

fetched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
entries=()

for i in "${!urls[@]}"; do
  url="${urls[$i]}"
  page_type="${page_types[$i]}"

  if ! encoded_url="$(url_encode "$url")"; then
    entries+=("$(jq -nc --arg page_type "$page_type" --arg url "$url" --arg error "URL-Encoding fehlgeschlagen" \
      '{page_type: $page_type, url: $url, error: $error}')")
    continue
  fi
  api_url="${PSI_ENDPOINT}?url=${encoded_url}&strategy=mobile"

  if ! fetch_page "$api_url"; then
    entries+=("$(jq -nc --arg page_type "$page_type" --arg url "$url" --arg error "curl fehlgeschlagen (Timeout oder Netzwerkfehler)" \
      '{page_type: $page_type, url: $url, error: $error}')")
    continue
  fi

  if [[ "$HTTP_STATUS" != 2* ]]; then
    err_msg=$(jq -r '.error.message // "unbekannter Fehler"' <<<"$RESPONSE_BODY" 2>/dev/null || echo "unbekannter Fehler")
    entries+=("$(jq -nc --arg page_type "$page_type" --arg url "$url" --arg error "HTTP ${HTTP_STATUS}: ${err_msg}" \
      '{page_type: $page_type, url: $url, error: $error}')")
    continue
  fi

  if ! jq -e . >/dev/null 2>&1 <<<"$RESPONSE_BODY"; then
    entries+=("$(jq -nc --arg page_type "$page_type" --arg url "$url" --arg error "ungültige JSON-Antwort der PSI-API" \
      '{page_type: $page_type, url: $url, error: $error}')")
    continue
  fi

  # field_data ist komplett null nur, wenn loadingExperience.metrics als
  # Ganzes fehlt (normal bei kleinen Sites ohne genug CrUX-Traffic, kein
  # Fehler). Fehlt nur ein einzelnes Metrik-Feld, bleibt dessen Wert null,
  # der Rest von field_data bleibt erhalten. CLS-Percentile kommt von der API
  # *100 (ganzzahlig codiert), deshalb /100 für den echten Score; Lab-CLS aus
  # dem Lighthouse-Audit ist bereits unskaliert.
  #
  # Guard: ein unerwartetes Antwortformat (z. B. percentile als String statt
  # Zahl) lässt jq mit einem Laufzeitfehler abbrechen. Unguarded würde das
  # unter set -e das ganze Script killen; hier landet die URL stattdessen als
  # error-Eintrag, der Rest der Liste läuft weiter.
  if ! entry=$(jq -c --arg page_type "$page_type" --arg url "$url" '
    {
      page_type: $page_type,
      url: $url,
      field_data: (
        if (.loadingExperience.metrics // null) != null then
          {
            lcp_ms: (.loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.percentile // null),
            lcp_category: (.loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.category // null),
            inp_ms: (.loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.percentile // null),
            inp_category: (.loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.category // null),
            cls: (
              if (.loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile // null) != null
              then (.loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile / 100)
              else null end
            ),
            cls_category: (.loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.category // null)
          }
        else null end
      ),
      lab: {
        performance_score: (.lighthouseResult.categories.performance.score // null),
        lcp_ms: (.lighthouseResult.audits["largest-contentful-paint"].numericValue // null),
        cls: (.lighthouseResult.audits["cumulative-layout-shift"].numericValue // null)
      }
    }
  ' <<<"$RESPONSE_BODY" 2>/dev/null); then
    entries+=("$(jq -nc --arg page_type "$page_type" --arg url "$url" --arg error "Feld-Extraktion fehlgeschlagen (unerwartetes API-Antwortformat)" \
      '{page_type: $page_type, url: $url, error: $error}')")
    continue
  fi
  entries+=("$entry")
done

pages_json=$(printf '%s\n' "${entries[@]}" | jq -s '.')

# --- CrUX-Wochenhistorie je eindeutigem Origin -----------------------------
# Die History-API kennt nur Origins, keine Seiten-URLs. Mehrere Seitentypen
# auf demselben Shop teilen sich einen Origin, deshalb erst deduplizieren
# (einfache Textliste statt declare -A, das Script muss auch mit der
# systemeigenen bash 3.2 laufen, die assoziative Arrays nicht kennt).
origins=()
known_origins=""
for url in "${urls[@]}"; do
  proto="${url%%://*}"
  rest="${url#*://}"
  host="${rest%%/*}"
  origin="${proto}://${host}"
  case " ${known_origins} " in
    *" ${origin} "*) ;;
    *)
      origins+=("$origin")
      known_origins="${known_origins} ${origin}"
      ;;
  esac
done

history_entries=()
for origin in "${origins[@]}"; do
  if ! fetch_history "$origin"; then
    history_entries+=("$(jq -nc --arg origin "$origin" --arg error "curl fehlgeschlagen (Timeout oder Netzwerkfehler)" \
      '{origin: $origin, error: $error}')")
    continue
  fi

  if [[ "$HTTP_STATUS" != 2* ]]; then
    err_msg=$(jq -r '.error.message // "unbekannter Fehler"' <<<"$RESPONSE_BODY" 2>/dev/null || echo "unbekannter Fehler")
    # HTTP 404 ("chrome ux report data not found") ist der Normalfall bei zu
    # wenig CrUX-Traffic für die Historie, kein technischer Fehler; der Grund
    # geht trotzdem in den error-Eintrag, damit er nicht wie ein echter
    # PSI-Fehler aussieht.
    history_entries+=("$(jq -nc --arg origin "$origin" --arg error "keine CrUX-Historie (HTTP ${HTTP_STATUS}: ${err_msg})" \
      '{origin: $origin, error: $error}')")
    continue
  fi

  if ! jq -e . >/dev/null 2>&1 <<<"$RESPONSE_BODY"; then
    history_entries+=("$(jq -nc --arg origin "$origin" --arg error "ungültige JSON-Antwort der CrUX-History-API" \
      '{origin: $origin, error: $error}')")
    continue
  fi

  # Die History-API codiert CLS-Perzentile als String ("CLS uses strings,
  # even if they look like numbers"), anders als loadingExperience oben: kein
  # *100, nur tonumber. Fehlt eine Woche innerhalb der Kollektionsperioden,
  # liefert die API dafür null statt eines Werts, das bleibt null.
  if ! entry=$(jq -c --arg origin "$origin" '
    def pad2: tostring | ("0" + .)[-2:];
    (.record.collectionPeriods // []) as $periods |
    (.record.metrics.largest_contentful_paint.percentilesTimeseries.p75s // []) as $lcp |
    (.record.metrics.interaction_to_next_paint.percentilesTimeseries.p75s // []) as $inp |
    (.record.metrics.cumulative_layout_shift.percentilesTimeseries.p75s // []) as $cls |
    {
      origin: $origin,
      wochen: [
        range(0; ($periods | length)) as $i |
        {
          start: "\($periods[$i].firstDate.year)-\($periods[$i].firstDate.month|pad2)-\($periods[$i].firstDate.day|pad2)",
          ende: "\($periods[$i].lastDate.year)-\($periods[$i].lastDate.month|pad2)-\($periods[$i].lastDate.day|pad2)",
          lcp_ms: ($lcp[$i] // null),
          inp_ms: ($inp[$i] // null),
          cls: (if ($cls[$i] // null) == null then null else ($cls[$i] | tonumber) end)
        }
      ]
    }
  ' <<<"$RESPONSE_BODY" 2>/dev/null); then
    history_entries+=("$(jq -nc --arg origin "$origin" --arg error "Feld-Extraktion fehlgeschlagen (unerwartetes API-Antwortformat)" \
      '{origin: $origin, error: $error}')")
    continue
  fi
  history_entries+=("$entry")
done

history_json=$(printf '%s\n' "${history_entries[@]}" | jq -s '.')

jq -n --arg fetched_at "$fetched_at" --argjson pages "$pages_json" --argjson historie "$history_json" \
  '{fetched_at: $fetched_at, strategy: "mobile", pages: $pages, historie: $historie}' > "${out_dir}/cwv.json"

# Trefferquote statt blosser Anzahl: ein Lauf, in dem jede Seite einen error
# trägt, sah bisher wie ein Erfolg aus (Exit 0, "Geschrieben: n URL(s)"), und
# der Orchestrator trug die Quelle als done ein. Der Block Technik entstand
# dann aus einer Datei ohne einen einzigen Messwert.
pages_ok=$(jq '[.[] | select(has("error") | not)] | length' <<<"$pages_json")
pages_total=$(jq 'length' <<<"$pages_json")
history_ok=$(jq '[.[] | select(has("error") | not)] | length' <<<"$history_json")

echo "Geschrieben: ${out_dir}/cwv.json (${pages_ok}/${pages_total} Seiten gemessen, ${history_ok}/${#origins[@]} Origin(s) mit Historie)"

if [[ "$pages_ok" -eq 0 ]]; then
  echo "Fehler: keine einzige Seite gemessen, jede URL trägt einen error. Die Datei ist geschrieben, taugt aber nicht als Quelle für den Baseline-Block Technik." >&2
  exit 1
fi
if [[ "$pages_ok" -lt "$pages_total" ]]; then
  echo "Hinweis: $((pages_total - pages_ok)) Seite(n) ohne Messwert, Grund je Seite im error-Feld von cwv.json." >&2
fi
