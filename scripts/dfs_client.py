#!/usr/bin/env python3
"""HTTP-Client für die DataForSEO-API v3.

Aufruf als Setup-Check (kostenlos, prüft nur Zugang und Kontostand):
  dfs_client.py --check [--sandbox]

Zwei Hälften wie in crawl.py. Die reinen Funktionen (`check_envelope`,
`task_result`, `envelope_cost`, `task_tag`) lesen einen Umschlag, ohne je ein
Netz anzufassen, und sind vollständig durch Tests abgedeckt. Genau eine
Funktion redet mit der Welt (`_real_transport`), und sie ist injizierbar.

Hier gibt es einen zweiten Grund für diese Trennung, den `crawl.py` nicht hat:
jeder echte Aufruf kostet Geld. Ein Test, der versehentlich die Produktion
trifft, ist keine langsame Testsuite, sondern eine Rechnung.

`BASE_SANDBOX` liefert dieselbe Struktur mit Dummy-Werten und kostet nichts.
Der Host ist ein Rauchtest für die Verkabelung und **nie eine Quelle für
Zahlen oder Fixtures**: entwickelt und geprüft wird gegen die Produktion, weil
ein Dummy-Wert keine falsche Bedeutung verrät.

Nur Standardbibliothek: base64, json, urllib. Kein requests.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

from audit import env as operator_env

BASE_PRODUCTION = "https://api.dataforseo.com/v3"
BASE_SANDBOX = "https://sandbox.dataforseo.com/v3"

#: DataForSEO meldet Erfolg als 20000. 20100 heißt "Aufgabe angelegt" und ist
#: die normale Antwort der task_post-Endpunkte, also ebenfalls Erfolg.
STATUS_OK = (20000, 20100)

#: Kostenlos laut Doku, liefert Kontostand, Limits und Preise. Der Setup-Check
#: läuft ausschließlich hierüber, damit er nie etwas kostet.
USER_DATA_PATH = "appendix/user_data"

#: Namensentscheidung: das Integrationskonzept vom 12.08.2026
#: (interne Endpoint-Bewertung zu DataForSEO) schlug DATAFORSEO_USERNAME
#: und DATAFORSEO_PASSWORD vor. Hier gilt das Präfix des Plugins, wie bei
#: PTAI_GOOGLE_CREDENTIALS und PTAI_PSI_KEY: eine .env mit zwei
#: Namensschemata sortiert später niemand mehr auseinander.
ENV_LOGIN = "PTAI_DFS_LOGIN"
ENV_PASSWORD = "PTAI_DFS_PASSWORD"

DEFAULT_TIMEOUT = 180


class DfsError(RuntimeError):
    """Ein Aufruf ist gescheitert: Transport, Umschlag oder einzelne Aufgabe."""


def auth_header(login: str, password: str) -> str:
    """Basic-Auth-Header. DataForSEO nimmt keine Zugangsdaten als URL-Parameter."""
    if not login or not password:
        raise ValueError(
            f"DataForSEO-Zugangsdaten fehlen. {ENV_LOGIN} und {ENV_PASSWORD} "
            "gehören in die .env des Kunden-Workspace oder zentral in "
            "~/.config/ptai-ecom/.env."
        )
    raw = f"{login}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _real_transport(url: str, headers: dict, body: bytes | None, timeout: float) -> bytes:
    """Die einzige Stelle, die wirklich das Netz anfasst."""
    request = urllib.request.Request(
        url, data=body, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class Client:
    """Ein DataForSEO-Zugang. Zustandslos bis auf Zugangsdaten und Basis-URL."""

    def __init__(self, login: str, password: str, *, base: str = BASE_PRODUCTION,
                 transport=None, timeout: float = DEFAULT_TIMEOUT):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._headers = {
            "Authorization": auth_header(login, password),
            "Content-Type": "application/json",
        }
        self._transport = transport or _real_transport

    @property
    def is_sandbox(self) -> bool:
        return self.base == BASE_SANDBOX

    def post(self, path: str, tasks: list) -> dict:
        """Ein POST auf einen v3-Pfad. `tasks` ist immer eine Liste.

        Die API nimmt ausschließlich ein Array von Aufgaben. Ein einzelnes
        Objekt käme als Fehlerantwort zurück und hätte dann schon eine
        Anfrage verbraucht, deshalb wird der Typ hier geprüft und nicht dort.
        """
        if not isinstance(tasks, list):
            raise TypeError(
                f"tasks muss eine Liste von Aufgaben sein, ist "
                f"{type(tasks).__name__}. Die DataForSEO-API nimmt immer ein Array."
            )
        return self._call(path, json.dumps(tasks, ensure_ascii=False).encode("utf-8"))

    def get(self, path: str) -> dict:
        """Ein GET auf einen v3-Pfad, für task_get und appendix/user_data."""
        return self._call(path, None)

    def _call(self, path: str, body: bytes | None) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            raw = self._transport(url, dict(self._headers), body, self.timeout)
        except urllib.error.HTTPError as exc:
            raise DfsError(f"DataForSEO {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DfsError(f"DataForSEO {path} nicht erreichbar: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError) as exc:
            raise DfsError(f"DataForSEO {path}: ungültige JSON-Antwort ({exc})") from exc
        check_envelope(payload)
        return payload


def check_envelope(payload: dict) -> dict:
    """Prüft den Umschlag auf oberster Ebene und wirft sonst `DfsError`."""
    status = payload.get("status_code")
    if status not in STATUS_OK:
        raise DfsError(f"DataForSEO meldet {status}: {payload.get('status_message')!r}")
    return payload


def _task(payload: dict, index: int = 0) -> dict:
    tasks = payload.get("tasks") or []
    if index >= len(tasks):
        raise DfsError(
            f"DataForSEO-Antwort hat keine Aufgabe an Position {index} "
            f"({len(tasks)} vorhanden)"
        )
    return tasks[index]


def task_result(payload: dict, index: int = 0) -> list:
    """Die Ergebnisliste einer Aufgabe, mit Prüfung ihres eigenen Status.

    Ein leeres Ergebnis (`result: null`) ist kein Fehler: ein Shop ohne
    Rankings hat schlicht keine. Der Aufrufer schreibt dafür eine leere Liste
    und einen Vermerk, nie einen Abbruch. Ein Status ungleich 20000 dagegen
    ist einer, sonst landete eine abgelehnte Aufgabe als "keine Daten" im
    Snapshot und im Report als Aussage über den Shop.
    """
    task = _task(payload, index)
    if task.get("status_code") not in STATUS_OK:
        raise DfsError(
            f"DataForSEO-Aufgabe meldet {task.get('status_code')}: "
            f"{task.get('status_message')!r}"
        )
    return task.get("result") or []


def envelope_cost(payload: dict) -> float:
    """Die Kosten der Anfrage in US-Dollar, wie sie auf der Rechnung stehen."""
    try:
        return float(payload.get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def task_tag(payload: dict, index: int = 0) -> str | None:
    """Der zurückgegebene Tag, sofern der Endpunkt ihn spiegelt.

    Ob die Live-Endpunkte das tun, ist laut Spec Abschnitt 19 offen. Fehlt er,
    ist das kein Fehler: die Kostenzuordnung hängt am gesendeten Tag und an
    `cost`, nicht an der Spiegelung.
    """
    return (_task(payload, index).get("data") or {}).get("tag")


def credentials(env: dict | None = None, workspace: str | os.PathLike = ".") -> tuple:
    """Zugangsdaten, ohne sie je auszugeben.

    Nie aus argv: ein Schlüssel im Argument steht in der Prozessliste. `env`
    hat Vorrang und ist für Tests da. Sonst sucht `audit.env.get_together()`
    in Umgebung, Workspace-`.env` und `~/.config/ptai-ecom/.env` und holt
    Login und Passwort bewusst aus derselben Ebene: ein Login aus der Umgebung
    und ein Passwort aus der zentralen Datei wären ein Paar, das so nirgends
    eingetragen wurde, und die API lehnte es mit einem 401 ab, der auf die
    falsche Ursache zeigt. Bis 11.09.2026 las diese Funktion nur die Umgebung,
    und ein zentral eingetragener Zugang ließ alle fünf DataForSEO-Pulls im
    großen Audit ausfallen.
    """
    if env is not None:
        return env.get(ENV_LOGIN, ""), env.get(ENV_PASSWORD, "")
    login, password = operator_env.get_together((ENV_LOGIN, ENV_PASSWORD), workspace)
    return login or "", password or ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DataForSEO-Zugang prüfen (kostenlos über appendix/user_data).")
    parser.add_argument("--check", action="store_true",
                        help="Zugang und Kontostand prüfen, Exit 0/1")
    parser.add_argument("--sandbox", action="store_true",
                        help="Rauchtest gegen die kostenlose Sandbox mit Dummy-Werten")
    parser.add_argument("--workspace", default=".",
                        help="Kunden-Workspace für die .env-Suche (Default: .)")
    args = parser.parse_args()
    if not args.check:
        parser.error("ohne --check hat dieses Script nichts zu tun")

    login, password = credentials(workspace=args.workspace)
    base = BASE_SANDBOX if args.sandbox else BASE_PRODUCTION
    try:
        result = task_result(Client(login, password, base=base).get(USER_DATA_PATH))
    except (ValueError, DfsError) as exc:
        sys.exit(f"Fehler: DataForSEO nicht erreichbar: {exc}")

    money = (result[0].get("money") if result else {}) or {}
    where = "Sandbox" if args.sandbox else "Produktion"
    print(f"OK: DataForSEO erreichbar ({where}, Kontostand: {money.get('balance')} USD)")


if __name__ == "__main__":
    main()
