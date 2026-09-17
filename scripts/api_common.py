#!/usr/bin/env python3
"""Gemeinsame Fehler-Aufbereitung für die Google-API-Pull-Scripts (GA4, GSC)."""
import json
import urllib.error


def describe_error(exc: Exception) -> str:
    """Eine Exception aus einem API-Call in eine klare Meldung wandeln.

    HTTPError: Message aus dem JSON-Error-Body, sonst der HTTP-Status.
    URLError: Netzproblem mit Grund. Alles andere (z. B. RuntimeError bei
    kaputtem JSON-Body): der Exception-Text selbst. HTTPError muss vor
    URLError geprüft werden, er ist eine Subklasse davon.
    """
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            return body.get("error", {}).get("message") or f"HTTP {exc.code}"
        except Exception:
            return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"API nicht erreichbar: {exc.reason}"
    return str(exc)
