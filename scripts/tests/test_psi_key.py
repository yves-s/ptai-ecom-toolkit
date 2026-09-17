"""Schlüsselsuche in psi_pull.sh (Spec 2026-09-11, Abschnitt 4.2).

Nur der Fall ohne Schlüssel: ein gefundener Schlüssel führte zu einem Aufruf
nach außen, und den macht kein Test.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "pull-cwv" / "scripts" / "psi_pull.sh"
CHECK_ENV = Path(__file__).resolve().parents[1] / "check_env.sh"

# Das bash des Systems: auf macOS die Version 3.2, dort soll ein Rückfall auffallen.
BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"

#: Ein Wert, der in keiner Argumentliste auftauchen darf. Er hat bewusst nicht die
#: Form eines Google-Schlüssels, sonst meldete ihn die Leak-Prüfung.
KEY = "test-key-der-nie-in-argumenten-steht"

#: Attrappe von curl: schreibt Argumente und stdin weg und antwortet wie curl mit
#: `-w "\n___HTTP_STATUS___%{http_code}"`.
FAKE_CURL = """#!/bin/sh
printf '%s\\n' "$@" >> "$FAKE_CURL_ARGS"
cat >> "$FAKE_CURL_STDIN"
printf '%s\\n___HTTP_STATUS___200' "$FAKE_CURL_BODY"
"""


@unittest.skipUnless(shutil.which("jq") and shutil.which("curl"),
                     "psi_pull.sh bricht ohne jq oder curl vorher ab")
class TestPsiKeyLookup(unittest.TestCase):
    def run_check(self, script, central_text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        central = Path(tmp.name) / "central.env"
        central.write_text(central_text, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PTAI_")}
        env["PTAI_ENV_FILE"] = str(central)
        return subprocess.run(["bash", str(script), "--check", "-"], cwd=tmp.name,
                              env=env, capture_output=True, text=True, timeout=60)

    def test_no_key_anywhere_exits_2_and_does_not_use_the_dash(self):
        result = self.run_check(SCRIPT, "")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("kein API-Key", result.stderr)
        self.assertNotIn("Prozessliste", result.stderr)

    def test_broken_lookup_is_not_reported_as_missing_key(self):
        # Scheitert die Suche selbst (python3 fehlt, Import bricht), stand bis
        # 11.09.2026 "kein API-Key" da, auch wenn der Schlüssel eingetragen war.
        # Die Kopie des Skripts liegt in einem Plugin-Ordner ohne scripts/audit,
        # also scheitert der Import, und es geht kein Aufruf nach außen.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        copy = Path(tmp.name) / "plugin" / "skills" / "pull-cwv" / "scripts" / "psi_pull.sh"
        copy.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT, copy)
        result = self.run_check(copy, "PTAI_PSI_KEY=wert-der-nie-erscheinen-darf\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("technisch gescheitert", result.stderr)
        self.assertNotIn("kein API-Key", result.stderr)
        self.assertNotIn("wert-der-nie-erscheinen-darf", result.stdout + result.stderr)


@unittest.skipUnless(shutil.which("jq"), "psi_pull.sh bricht ohne jq vorher ab")
class TestKeyNeverInArguments(unittest.TestCase):
    """Der Key geht als Header über stdin an curl, nie in die URL (Auftrag C, Punkt 3)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "curl"
        stub.write_text(FAKE_CURL, encoding="utf-8")
        stub.chmod(0o755)
        self.args = self.dir / "args.txt"
        self.stdin = self.dir / "stdin.txt"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("PTAI_")}
        self.env.update({
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "PTAI_PSI_KEY": KEY,
            "PTAI_ENV_FILE": str(self.dir / "keine.env"),
            "FAKE_CURL_ARGS": str(self.args),
            "FAKE_CURL_STDIN": str(self.stdin),
            "FAKE_CURL_BODY": '{"lighthouseResult":{"categories":{"performance":{"score":0.9}}}}',
        })

    def run_psi(self, *argv):
        return subprocess.run([BASH, str(SCRIPT), *argv], cwd=self.dir, env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def test_check_sends_the_key_as_header_not_in_the_url(self):
        result = self.run_psi("--check", "-")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args.read_text(encoding="utf-8")
        self.assertNotIn(KEY, args)
        self.assertIn("--config", args.split())
        self.assertEqual(self.stdin.read_text(encoding="utf-8"), f'header = "X-Goog-Api-Key: {KEY}"\n')

    def test_pull_sends_the_key_as_header_to_psi_and_crux(self):
        result = self.run_psi(str(self.dir / "out"), "-", "start=https://beispielshop.example/")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.args.read_text(encoding="utf-8")
        self.assertNotIn(KEY, args)
        self.assertIn("https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord", args.split())
        self.assertEqual(self.stdin.read_text(encoding="utf-8").count(f'header = "X-Goog-Api-Key: {KEY}"'), 2)


class TestHeaderConfig(unittest.TestCase):
    def config_from(self, script, function, key):
        text = script.read_text(encoding="utf-8")
        body = re.search(rf"^{function}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
        self.assertIsNotNone(body, f"{function}() fehlt in {script.name}")
        return subprocess.run([BASH, "-c", f'{body.group(0)}\n{function} "$1"', "bash", key],
                              capture_output=True, text=True, check=True).stdout

    def test_both_scripts_escape_quotes_and_backslashes(self):
        for script, function in ((SCRIPT, "key_config"), (CHECK_ENV, "key_header_config")):
            with self.subTest(script=script.name):
                self.assertEqual(self.config_from(script, function, 'a"b\\c'),
                                 'header = "X-Goog-Api-Key: a\\"b\\\\c"\n')

    def test_no_script_puts_a_key_into_a_url(self):
        for script in (SCRIPT, CHECK_ENV):
            with self.subTest(script=script.name):
                self.assertIsNone(re.search(r"[?&]key=", script.read_text(encoding="utf-8")))

    def test_the_crux_check_pipes_the_header_into_curl(self):
        self.assertRegex(CHECK_ENV.read_text(encoding="utf-8"),
                         r'key_header_config "\$psi_key" \| curl -s --config - ')


class TestSkillsPassNoKey(unittest.TestCase):
    """Ein Key als Argument an psi_pull.sh steht in der Prozessliste, bevor das Skript läuft."""

    def test_no_skill_passes_the_key_as_an_argument(self):
        root = SCRIPT.parents[3]
        pattern = re.compile(r'psi_pull\.sh"?[^\n]*"\$\{?PTAI_PSI_KEY')
        hits = [p.relative_to(root).as_posix() for p in sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("agents/*.md"))
                if pattern.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
