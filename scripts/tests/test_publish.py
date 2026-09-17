"""Einen Lauf für die Kundenansicht bereitstellen: was mitgeht, was bleibt."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from audit import manifest, publish

MANIFEST_KEY = "brands/beispielkunde/manifest.json"


def make_workspace(root: Path, run_id: str) -> Path:
    """Ein Kunden-Workspace mit einem Lauf, der drei Dateien trägt."""
    ws = root / "workspace"
    run = ws / "reporting" / "runs" / run_id
    (run / "findings").mkdir(parents=True)
    (ws / "reporting" / "config.json").write_text(json.dumps({
        "account_slug": "beispielkunde", "brand": "Beispielshop",
        "domain": "https://beispielshop.test"}), encoding="utf-8")
    (run / "state.json").write_text(json.dumps({
        "run_id": run_id, "cadence": "audit", "period": None}),
        encoding="utf-8")
    (run / "audit.pdf").write_bytes(b"%PDF")
    (run / "audit-web.html").write_text("<html>", encoding="utf-8")
    (run / "findings" / "cro.json").write_text("{}", encoding="utf-8")
    return ws


class TestSlugify(unittest.TestCase):
    def test_a_shop_name_becomes_a_path_segment(self):
        self.assertEqual(publish.slugify("Beispielshop"), "beispielshop")

    def test_an_ampersand_disappears(self):
        self.assertEqual(publish.slugify("Nord & Stein"), "nord-stein")

    def test_umlauts_become_ascii(self):
        # Dateinamen und Pfade sind ASCII, auch wenn der Shop es nicht ist.
        self.assertEqual(publish.slugify("Grün & Söhne"), "gruen-soehne")


class TestPrepare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_id = "2026-09-08-audit"
        self.ws = make_workspace(Path(self.tmp.name), self.run_id)
        self.bucket = Path(self.tmp.name) / "bucket"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        return publish.prepare(self.ws, self.run_id, self.bucket)

    def test_the_run_lands_under_customer_and_shop(self):
        out = self._run()
        self.assertEqual((out["brand"], out["shop"]),
                         ("beispielkunde", "beispielshop"))
        run_target = self.bucket / "brands/beispielkunde/shops/beispielshop/runs" / self.run_id
        self.assertTrue((run_target / "audit.pdf").exists())
        self.assertTrue((run_target / "findings" / "cro.json").exists())

    def test_publishing_never_releases(self):
        self._run()
        manifest_data = manifest.load(self.bucket / "brands/beispielkunde/manifest.json")
        self.assertFalse(manifest_data["runs"][0]["released"])
        self.assertEqual(manifest.released(manifest_data), [])

    def test_the_ledger_stays_behind(self):
        (self.ws / "reporting" / "runs" / self.run_id / "dfs-ledger.jsonl"
         ).write_text("{}", encoding="utf-8")
        self._run()
        run_target = self.bucket / "brands/beispielkunde/shops/beispielshop/runs" / self.run_id
        self.assertFalse((run_target / "dfs-ledger.jsonl").exists())

    def test_earlier_versions_stay_behind(self):
        revision_dir = self.ws / "reporting" / "runs" / self.run_id / "revisions" / "01"
        revision_dir.mkdir(parents=True)
        (revision_dir / "audit.pdf").write_bytes(b"%PDF")
        self._run()
        run_target = self.bucket / "brands/beispielkunde/shops/beispielshop/runs" / self.run_id
        self.assertFalse((run_target / "revisions").exists())

    def test_the_shop_carries_its_display_name(self):
        self._run()
        manifest_data = manifest.load(self.bucket / "brands/beispielkunde/manifest.json")
        self.assertEqual(manifest_data["shops"]["beispielshop"]["name"], "Beispielshop")

    def test_a_second_publish_replaces_the_files(self):
        self._run()
        run = self.ws / "reporting" / "runs" / self.run_id
        (run / "audit.pdf").unlink()
        (run / "neu.txt").write_text("x", encoding="utf-8")
        self._run()
        run_target = self.bucket / "brands/beispielkunde/shops/beispielshop/runs" / self.run_id
        self.assertTrue((run_target / "neu.txt").exists())
        self.assertFalse((run_target / "audit.pdf").exists(),
                         "eine geloeschte Datei darf im Bucket nicht stehenbleiben")

    def test_a_second_publish_keeps_an_existing_release(self):
        self._run()
        manifest_path = self.bucket / "brands/beispielkunde/manifest.json"
        manifest.save(manifest_path, manifest.release(manifest.load(manifest_path),
                                                      "beispielshop", self.run_id))
        self._run()
        self.assertTrue(manifest.load(manifest_path)["runs"][0]["released"])

    def test_a_config_without_a_customer_stops(self):
        (self.ws / "reporting" / "config.json").write_text(
            json.dumps({"brand": "Beispielshop"}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            self._run()

    def test_an_unknown_run_stops(self):
        with self.assertRaises(SystemExit):
            publish.prepare(self.ws, "2026-01-01-audit", self.bucket)

    def test_two_shops_of_one_customer_share_a_manifest(self):
        self._run()
        (self.ws / "reporting" / "config.json").write_text(json.dumps({
            "account_slug": "beispielkunde", "brand": "Zweitshop",
            "domain": "https://zweitshop.test"}), encoding="utf-8")
        self._run()
        manifest_data = manifest.load(self.bucket / "brands/beispielkunde/manifest.json")
        self.assertEqual(set(manifest_data["shops"]), {"beispielshop", "zweitshop"})
        self.assertEqual(len(manifest_data["runs"]), 2)


class _Response(io.BytesIO):
    status = 200


class FakeBucket:
    """Der Bucket im Speicher, an der Stelle von `urllib.request.urlopen`.

    Kein Test öffnet einen Socket. GET liest aus `objects`, POST schreibt
    hinein, und jeder Aufruf landet in `calls`, damit ein Test sieht, ob etwas
    hochging.
    """
    URL = "https://bucket.test"
    PREFIX = f"{URL}/storage/v1/object/runs/"

    def __init__(self, objects=None, get_status=None, get_body=b""):
        self.objects = dict(objects or {})
        self.get_status = get_status
        self.get_body = get_body
        self.calls = []

    def urlopen(self, request, timeout=None):
        key = request.full_url.removeprefix(self.PREFIX)
        method = request.get_method()
        self.calls.append((method, key))
        if method == "POST":
            self.objects[key] = request.data
            return _Response(b"{}")
        if self.get_status is None and key in self.objects:
            return _Response(self.objects[key])
        raise urllib.error.HTTPError(request.full_url, self.get_status or 404,
                                     "", {}, io.BytesIO(self.get_body))

    def uploads(self):
        return [key for method, key in self.calls if method == "POST"]

    def manifest(self):
        return json.loads(self.objects[MANIFEST_KEY])


class TestUpload(unittest.TestCase):
    """`publish --upload` in ein frisches Ziel, während der Bucket schon Läufe kennt.

    Ohne das Manifest aus dem Bucket baut `prepare()` auf einem leeren auf, und
    der Upload ersetzt damit das im Bucket: jeder andere Lauf verschwindet aus
    dem Portal, eine Freigabe geht verloren.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_id = "2026-09-08-audit"
        self.ws = make_workspace(Path(self.tmp.name), self.run_id)
        self.target = Path(self.tmp.name) / "fresh"
        manifest_data = manifest.empty("beispielkunde", "Beispielshop")
        for run_id, kind in ((self.run_id, "audit"), ("2026-08-01-report", "report")):
            manifest_data = manifest.add_run(manifest_data, shop="beispielshop",
                                             run_id=run_id, kind=kind, cadence=kind,
                                             period=None, run_date=run_id[:10],
                                             files={"audit.pdf": 4})
        manifest_data = manifest.release(manifest_data, "beispielshop", self.run_id,
                                         today=date(2026, 9, 9))
        self.remote = json.dumps(manifest_data).encode("utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _publish(self, bucket, env=None):
        if env is None:
            env = {"SUPABASE_URL": FakeBucket.URL,
                   "SUPABASE_SERVICE_ROLE_KEY": "service-key"}
        argv = ["--workspace", str(self.ws), "--run-id", self.run_id,
                "--target", str(self.target), "--upload"]
        # `clear=True`, damit ein Schlüssel aus der Shell nie in einen Test gerät.
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("urllib.request.urlopen", bucket.urlopen), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return publish.main(argv)

    def test_an_upload_into_an_empty_target_keeps_the_other_runs(self):
        bucket = FakeBucket({MANIFEST_KEY: self.remote})
        self.assertEqual(self._publish(bucket), 0)
        self.assertEqual({r["run_id"] for r in bucket.manifest()["runs"]},
                         {self.run_id, "2026-08-01-report"})

    def test_an_upload_into_an_empty_target_keeps_the_release(self):
        bucket = FakeBucket({MANIFEST_KEY: self.remote})
        self._publish(bucket)
        entry = next(r for r in bucket.manifest()["runs"]
                     if r["run_id"] == self.run_id)
        self.assertTrue(entry["released"])
        self.assertEqual(entry["released_at"], "2026-09-09")

    def test_a_new_brand_starts_with_an_empty_manifest(self):
        bucket = FakeBucket()
        self.assertEqual(self._publish(bucket), 0)
        runs = bucket.manifest()["runs"]
        self.assertEqual([r["run_id"] for r in runs], [self.run_id])
        self.assertFalse(runs[0]["released"])

    def test_supabase_no_such_key_starts_with_an_empty_manifest(self):
        body = b'{"statusCode":"404","error":"not_found","message":"Object not found","code":"NoSuchKey"}'
        bucket = FakeBucket(get_status=400, get_body=body)
        self.assertEqual(self._publish(bucket), 0)
        self.assertEqual([r["run_id"] for r in bucket.manifest()["runs"]],
                         [self.run_id])

    def test_a_failed_download_stops_before_anything_goes_up(self):
        # Ein Manifest, das nicht gelesen werden konnte, ist kein leeres. Auch
        # im Ziel bleibt keines liegen, sonst lüde ein zweiter Anlauf es hoch.
        bucket = FakeBucket({MANIFEST_KEY: self.remote}, get_status=500)
        with self.assertRaises(SystemExit):
            self._publish(bucket)
        self.assertEqual(bucket.uploads(), [])
        self.assertFalse((self.target / MANIFEST_KEY).exists())

    def test_a_missing_key_prepares_nothing(self):
        # Ohne Schlüssel lässt sich das Manifest nicht holen. Ein trotzdem
        # vorbereitetes Ziel trüge eines, das auf einem leeren aufbaut, und der
        # nächste Anlauf mit Schlüssel lüde genau das hoch.
        bucket = FakeBucket({MANIFEST_KEY: self.remote})
        self.assertEqual(self._publish(bucket, env={}), 1)
        self.assertEqual(bucket.calls, [])
        self.assertFalse((self.target / MANIFEST_KEY).exists())

    def test_a_manifest_already_in_the_target_is_used_as_it_is(self):
        publish.prepare(self.ws, self.run_id, self.target)
        bucket = FakeBucket({MANIFEST_KEY: self.remote})
        self._publish(bucket)
        self.assertNotIn(("GET", MANIFEST_KEY), bucket.calls)


if __name__ == "__main__":
    unittest.main()
