#!/usr/bin/env python3
"""Access-Token aus Service-Account-JSON. Aufruf: google_token.py <sa.json> <analytics|webmasters>"""
import sys

SCOPES = {
    "analytics": ["https://www.googleapis.com/auth/analytics.readonly"],
    "webmasters": ["https://www.googleapis.com/auth/webmasters.readonly"],
    # Der Google-Ads-Scope heißt trotz des Alters "adwords", das ist kein
    # Tippfehler und wird nicht "modernisiert". Zugriff läuft über dasselbe
    # Dienstkonto wie GA4 und GSC; dafür muss die Dienstkonto-Mailadresse als
    # Nutzer im Google-Ads-Konto stehen, nicht eine Personenadresse.
    "adwords": ["https://www.googleapis.com/auth/adwords"],
}


def get_access_token(service_account_path: str, scope_key: str) -> str:
    """Liest die Service-Account-Datei ein und liefert ein frisches Access-Token für den Scope.

    Importiert google-auth erst hier (nicht auf Modulebene), damit dieses Modul auch
    importierbar bleibt, wenn das Paket noch fehlt (z. B. beim Doku-Lesen durch Aufrufer).
    """
    if scope_key not in SCOPES:
        raise ValueError(f"unbekannter Scope-Key: {scope_key!r}, erlaubt: {', '.join(SCOPES)}")

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise RuntimeError(
            "Paket google-auth (oder requests) fehlt. Installieren mit: pip3 install --user google-auth requests"
        ) from exc

    creds = service_account.Credentials.from_service_account_file(
        service_account_path, scopes=SCOPES[scope_key]
    )
    creds.refresh(Request())
    return creds.token


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in SCOPES:
        sys.exit("usage: google_token.py <service-account.json> <analytics|webmasters>")

    try:
        token = get_access_token(sys.argv[1], sys.argv[2])
    except Exception as exc:
        sys.exit(f"Fehler: {exc}")

    print(token)


if __name__ == "__main__":
    main()
