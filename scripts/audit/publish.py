#!/usr/bin/env python3
"""Einen Lauf für die Kundenansicht bereitstellen.

Schritt 1 der Bau-Reihenfolge aus der Portal-Spec: der Lauf-Ordner wandert
**1:1** in den Bucket, nichts wird umbenannt, zusammengefasst oder neu
gerechnet. Was hochgeht, entscheidet eine Ausschlussliste (`manifest.EXCLUDED`),
keine Auswahlliste: im Zweifel hoch, denn es sind die Daten des Kunden.

**Hochladen ist nicht Freigeben.** Diese Datei setzt nie einen Freigabestatus.
Ein hochgeladener Lauf liegt im Bucket und ist für den Kunden unsichtbar, bis
`release` ihn sichtbar macht. Das hält das menschliche Gate aus dem
Audit-Design intakt: kein Lauf erreicht den Kunden, bevor der Betreiber ihn
gelesen hat.

**Zwei Ebenen, zwei Bedeutungen.** `account_slug` aus der Config ist der Kunde
und damit die Login-Ebene, `brand` ist der Shop und damit die Ablage-Ebene. Ein
Kunde kann mehrere Shops fuehren; ohne diese Trennung braeuchte dieselbe Person
je Shop einen eigenen Zugang, und der zweite Shop waere eine Migration statt
eines Ordners.

CLI:
    python3 -m audit.publish --workspace . --run-id 2026-09-08-audit \\
        --target ~/tmp/bucket        # lokal, solange kein Bucket steht
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from audit import manifest

#: Dateien auf Workspace-Ebene, die zum Shop gehoeren und nicht zu einem
#: einzelnen Lauf: der Massnahmen-Backlog bewegt sich ueber Laeufe hinweg, die
#: Baseline ist der eingefrorene Nullpunkt. Beide braucht die App fuer die
#: Ansichten Massnahmen und Kennzahlen, und beide liegen deshalb neben den
#: Laeufen statt in einem von ihnen.
SHOP_FILES = ("measures.json", "measures.md")
SHOP_DIRS = ("baseline",)

#: Aus "Beispielshop" wird "beispielshop", aus "Nord & Stein" wird "nord-stein".
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Ein Shop-Name als Pfadsegment."""
    umlauts = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
               "Ä": "ae", "Ö": "oe", "Ü": "ue"}
    for umlaut, replacement in umlauts.items():
        name = name.replace(umlaut, replacement)
    return _NON_SLUG_CHARS.sub("-", name.lower()).strip("-")


def run_kind(run_id: str, state: dict) -> tuple[str, str | None]:
    """Lauf-Art und Kadenz. Die Lauf-ID traegt sie im Namen (`<datum>-<kadenz>`),
    der Zustand bestaetigt sie."""
    cadence = state.get("cadence") or (run_id.rsplit("-", 1)[-1] if "-" in run_id else None)
    kind = cadence if cadence in manifest.KINDS else "report"
    return kind, cadence


def load_config(workspace) -> dict:
    """Die Reporting-Config des Workspace. Ohne `account_slug` gibt es keinen
    Kunden und damit keinen Bucket-Pfad."""
    config = json.loads((Path(workspace) / "reporting" / "config.json")
                        .read_text(encoding="utf-8"))
    if not config.get("account_slug"):
        raise SystemExit("reporting/config.json ohne account_slug: ohne Kunde "
                         "kein Bucket-Pfad")
    return config


def manifest_key(brand: str) -> str:
    """Wo das Manifest einer Brand liegt, im Ziel wie im Bucket.

    Eine Stelle für beides: landet das geholte Manifest an einem anderen Pfad
    als dem, an dem `prepare()` sucht, ist der Fehler wieder da, den
    `fetch_manifest()` schließt.
    """
    return f"brands/{brand}/manifest.json"


def prepare(workspace, run_id: str, target, today: date | None = None) -> dict:
    """Kopiert den Lauf ans Ziel und traegt ihn ins Manifest.

    `target` ist die Wurzel des Buckets, lokal oder gemountet. Der Upload in
    einen echten Bucket ersetzt spaeter genau diese Kopie; die Struktur
    darunter bleibt dieselbe, damit der Wechsel keine Migration ist.
    """
    workspace, target = Path(workspace), Path(target)
    config = load_config(workspace)
    brand = config["account_slug"]
    shop = slugify(config.get("brand") or brand)

    run_dir = workspace / "reporting" / "runs" / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"Kein Lauf {run_id} unter {run_dir}")
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    kind, cadence = run_kind(run_id, state)

    files = manifest.collect_files(run_dir)
    if not files:
        raise SystemExit(f"Lauf {run_id} hat keine Dateien zum Hochladen")

    run_target = target / manifest.path_for(brand, shop, run_id)
    if run_target.exists():
        shutil.rmtree(run_target)
    for rel in files:
        source, dest = run_dir / rel, run_target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

    # Der Backlog und die Baseline gehoeren dem Shop, nicht dem Lauf. Sie
    # wandern bei jedem publish mit, weil sie sich zwischen den Laeufen
    # bewegen: eine Massnahme wechselt ihren Status, ein Baseline-Block wird
    # nachgetragen.
    shop_target = target / manifest.path_for(brand, shop)
    shop_files = {}
    for name in SHOP_FILES:
        source = workspace / "reporting" / name
        if source.exists():
            dest = shop_target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            shop_files[name] = source.stat().st_size
    for name in SHOP_DIRS:
        source = workspace / "reporting" / name
        if not source.is_dir():
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(workspace / "reporting").as_posix()
            dest = shop_target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            shop_files[rel] = path.stat().st_size

    manifest_path = target / manifest_key(brand)
    manifest_data = (manifest.load(manifest_path) if manifest_path.exists()
                     else manifest.empty(brand, config.get("brand") or brand))
    # Der Shop bekommt seinen Anzeigenamen, damit die App ihn nennen kann,
    # ohne den Slug zu verschoenern.
    manifest_data.setdefault("shops", {})[shop] = {
        "name": config.get("brand") or shop,
        "domain": config.get("domain"),
        "path": manifest.path_for(brand, shop),
        "files": shop_files,
    }
    manifest_data = manifest.add_run(manifest_data, shop=shop, run_id=run_id,
                                     kind=kind, cadence=cadence,
                                     period=state.get("period"),
                                     run_date=run_id[:10], files=files, today=today)
    manifest.save(manifest_path, manifest_data)
    return {"brand": brand, "shop": shop, "run_id": run_id,
            "files": len(files), "shop_files": len(shop_files),
            "path": str(run_target), "manifest": str(manifest_path),
            "released": False}


#: Wie eine Datei im Bucket ausgeliefert wird. Ohne den richtigen Typ laedt der
#: Browser die Web-Fassung herunter, statt sie anzuzeigen.
CONTENT_TYPES = {".html": "text/html", ".pdf": "application/pdf",
                 ".json": "application/json", ".md": "text/markdown",
                 ".png": "image/png", ".jpg": "image/jpeg",
                 ".csv": "text/csv", ".txt": "text/plain"}


def upload(local_root, url: str, service_key: str, bucket: str = "runs") -> dict:
    """Laedt einen vorbereiteten Baum in den Bucket.

    Getrennt von `prepare()`, weil beides getrennt scheitern darf: eine
    fehlgeschlagene Uebertragung soll den vorbereiteten Ordner nicht wegwerfen,
    und ein zweiter Anlauf soll ihn nicht neu bauen muessen.

    `x-upsert` ueberschreibt bestehende Objekte. Das ist gewollt: dieselbe
    Lauf-ID zweimal zu veroeffentlichen ist eine Korrektur.
    """
    import urllib.error
    import urllib.request

    local_root = Path(local_root)
    uploaded, errors = 0, []
    for path in sorted(local_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(local_root).as_posix()
        request = urllib.request.Request(
            f"{url.rstrip('/')}/storage/v1/object/{bucket}/{rel}",
            data=path.read_bytes(), method="POST",
            headers={"Authorization": f"Bearer {service_key}",
                     "apikey": service_key,
                     "x-upsert": "true",
                     "Content-Type": CONTENT_TYPES.get(
                         path.suffix.lower(), "application/octet-stream")})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status == 200:
                    uploaded += 1
                else:
                    errors.append(f"{rel}: HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            errors.append(f"{rel}: HTTP {exc.code}")
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
    return {"uploaded": uploaded, "errors": errors}


def fetch_manifest(target, brand: str, url: str, service_key: str,
                   bucket: str = "runs") -> str:
    """Holt das Manifest aus dem Bucket ins Ziel, bevor `prepare()` darauf aufbaut.

    Liegt im Ziel keines, baut `prepare()` auf einem leeren auf, und `upload()`
    ersetzt damit das Manifest im Bucket: jeder andere Lauf verschwindet aus dem
    Portal, und ein schon freigegebener Lauf verliert seine Freigabe, weil
    `add_run` keinen Eintrag findet, dessen Status es behalten könnte.

    Rückgabe ist die Herkunft: `local` (lag schon im Ziel und bleibt
    unangetastet), `remote` (aus dem Bucket geholt) oder `new` (HTTP 404, die
    Brand ist neu). Jeder andere Fehler bricht ab, bevor etwas hochgeht: ein
    Manifest, das sich nicht lesen ließ, ist kein leeres.
    """
    import urllib.error
    import urllib.request

    object_key = manifest_key(brand)
    path = Path(target) / object_key
    if path.exists():
        return "local"
    request = urllib.request.Request(
        f"{url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}",
        headers={"Authorization": f"Bearer {service_key}",
                 "apikey": service_key})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        # Supabase Storage antwortet bei einem fehlenden Objekt nicht mit dem
        # äußeren HTTP-Status 404, sondern mit HTTP 400 und `NoSuchKey` im
        # JSON-Body. Nur dieser benannte 400-Fall bedeutet "neue Brand"; ein
        # anderer 400er bleibt ein Abbruch, damit kein bestehendes Manifest
        # versehentlich durch ein leeres ersetzt wird.
        error_body = exc.read()
        exc.close()
        missing = (exc.code == 404 or
                   (exc.code == 400 and b'"code":"NoSuchKey"' in error_body))
        if missing:
            return "new"
        raise SystemExit(f"Manifest {object_key} nicht aus dem Bucket lesbar: "
                         f"HTTP {exc.code}. Abgebrochen, nichts hochgeladen.")
    except OSError as exc:
        raise SystemExit(f"Manifest {object_key} nicht aus dem Bucket lesbar: "
                         f"{exc}. Abgebrochen, nichts hochgeladen.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return "remote"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--target", required=True,
                   help="Ordner, in dem der Lauf fuer den Upload vorbereitet wird")
    p.add_argument("--upload", action="store_true",
                   help="danach in den Bucket laden, braucht SUPABASE_URL und "
                        "SUPABASE_SERVICE_ROLE_KEY in der Umgebung; liegt im "
                        "Ziel kein Manifest, kommt es vorher aus dem Bucket")
    a = p.parse_args(argv)

    if a.upload:
        import os
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        # Ohne Schlüssel wird auch nichts vorbereitet. Ein Ziel, dessen
        # Manifest auf einem leeren aufbaut, lüde der nächste Anlauf mit
        # Schlüssel sonst genau so hoch.
        if not (url and key):
            print("SUPABASE_URL oder SUPABASE_SERVICE_ROLE_KEY fehlen in der "
                  "Umgebung. Nichts vorbereitet, nichts hochgeladen.",
                  file=sys.stderr)
            return 1
        origin = fetch_manifest(a.target, load_config(a.workspace)["account_slug"],
                                url, key)
        print({"local": "Manifest lag schon im Ziel und bleibt, wie es ist",
               "remote": "Manifest aus dem Bucket übernommen",
               "new": "Brand ist neu im Bucket, das Manifest beginnt leer"}[origin])

    result = prepare(a.workspace, a.run_id, a.target)
    print(f"{result['files']} Dateien nach {result['path']}")
    print(f"{result['shop_files']} Dateien auf Shop-Ebene "
          "(Massnahmen und Baseline, sie gelten ueber Laeufe hinweg)")
    print(f"Manifest: {result['manifest']}")
    if a.upload:
        upload_result = upload(a.target, url, key)
        print(f"{upload_result['uploaded']} Objekte im Bucket")
        for line in upload_result["errors"][:10]:
            print(f"  FEHLER {line}", file=sys.stderr)
        if upload_result["errors"]:
            return 1

    print("Freigabe: nein. Der Lauf ist für den Kunden unsichtbar, bis "
          "release ihn freigibt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
