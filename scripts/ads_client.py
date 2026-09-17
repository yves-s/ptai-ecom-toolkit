#!/usr/bin/env python3
"""REST-Client für die Google Ads API (GoogleAdsService.Search).

Dieselbe Bauweise wie dfs_client.py: eine injizierbare Transport-Funktion,
alles darüber rein und getestet. Hier aus einem anderen Grund als Geld: das
Entwicklertoken war beim Bau nicht beantragt, es gab also keine Möglichkeit,
gegen die echte API zu entwickeln. Die Fixtures sind aus der REST-Referenz
gebaut, siehe `scripts/tests/fixtures/ads/HERKUNFT.md`.

Zugriff läuft über dasselbe Dienstkonto wie GA4 und GSC, mit dem Scope
`https://www.googleapis.com/auth/adwords`. Dafür muss die **Dienstkonto-Mail**
als Nutzer im Google-Ads-Konto stehen, nicht eine Personenadresse. Das Token
und der Zugang zum Werbekonto sind zwei verschiedene Dinge: das Token gehört
dem Betreiber, den Zugang gibt der Kunde.

Beträge kommen als Micros (millionstel Währungseinheit) und werden hier
umgerechnet. Die Währung steht in `customer.currency_code` und wird vom Pull
mitgezogen: ein Betrag ohne Währung ist keine Zahl, sondern eine Behauptung.

Nur Standardbibliothek plus google-auth über den geteilten Token-Helfer.
"""
import json
import urllib.error
import urllib.request

BASE = "https://googleads.googleapis.com"

#: Die eingesetzte API-Version. Google stellt Versionen nach rund einem Jahr
#: ab. Vor dem ersten echten Lauf gegen die Liste der unterstützten Versionen
#: halten und hier anpassen; `--api-version` übersteuert sie.
DEFAULT_VERSION = "v21"

ENV_TOKEN = "PTAI_GOOGLE_ADS_TOKEN"

DEFAULT_TIMEOUT = 120


class AdsError(RuntimeError):
    """Ein Aufruf gegen die Google Ads API ist gescheitert."""


def from_micros(value):
    """Micros in Währungseinheiten, auf Cent gerundet. `None` bleibt `None`.

    `None` und `0` sind zwei Aussagen: "kein Wert geliefert" gegen "null
    ausgegeben". Eine 0 an der Stelle stünde im Report als Tatsache. Ein Wert,
    der sich nicht lesen lässt, wird ebenfalls `None` und nicht 0.
    """
    if value is None:
        return None
    try:
        return round(int(value) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def _strip(customer_id) -> str:
    """Google Ads zeigt die Kundennummer mit Bindestrichen, die API nimmt sie
    ohne. Ein Copy-Paste aus der Oberfläche scheitert sonst mit einer
    nichtssagenden 400."""
    return str(customer_id).replace("-", "").strip()


def _real_transport(url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class Client:
    def __init__(self, developer_token, customer_id, *, access_token,
                 login_customer_id=None, version=DEFAULT_VERSION,
                 transport=None, timeout=DEFAULT_TIMEOUT):
        if not developer_token:
            raise ValueError(
                f"Google-Ads-Entwicklertoken fehlt. {ENV_TOKEN} gehört zentral "
                "in ~/.config/ptai-ecom/.env oder in die .env des "
                "Kunden-Workspace. Es gehört dem Betreiber und wird im eigenen "
                "Verwaltungskonto beantragt, nicht vom Kunden."
            )
        self.customer_id = _strip(customer_id)
        self.version = version
        self.timeout = timeout
        self._transport = transport or _real_transport
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "Content-Type": "application/json",
        }
        if login_customer_id:
            self._headers["login-customer-id"] = _strip(login_customer_id)

    @property
    def url(self) -> str:
        return f"{BASE}/{self.version}/customers/{self.customer_id}/googleAds:search"

    def search(self, query: str) -> list:
        """Alle Zeilen einer GAQL-Abfrage, über alle Seiten hinweg.

        Die Query geht auf jeder Folgeseite unverändert mit: die API verlangt
        das zum Seitentoken und antwortet sonst mit einem Fehler statt mit der
        nächsten Seite.
        """
        rows, page_token = [], None
        while True:
            payload = {"query": query}
            if page_token:
                payload["pageToken"] = page_token
            body = json.dumps(payload).encode("utf-8")
            try:
                raw = self._transport(self.url, dict(self._headers), body, self.timeout)
            except urllib.error.HTTPError as exc:
                raise AdsError(f"Google Ads: HTTP {exc.code}") from exc
            except (urllib.error.URLError, OSError) as exc:
                raise AdsError(f"Google Ads nicht erreichbar: {exc}") from exc
            try:
                answer = json.loads(raw.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, ValueError) as exc:
                raise AdsError(f"Google Ads: ungültige JSON-Antwort ({exc})") from exc
            rows.extend(answer.get("results") or [])
            page_token = answer.get("nextPageToken")
            if not page_token:
                return rows
