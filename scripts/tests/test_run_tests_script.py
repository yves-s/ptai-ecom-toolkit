"""scripts/run_tests.sh startet jede Suite und zählt, welche scheitern (Spec 2026-09-11 public release, C3).

Die Tests laufen gegen eine Kopie des Skripts in einem Wegwerf-Plugin: das echte
Skript hier zu starten, startete diese Suite in sich selbst. `node` ist eine
Attrappe, die Python-Suiten sind echt und bestehen je aus einem Test.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "run_tests.sh"
BASH = "/bin/bash" if Path("/bin/bash").exists() else "bash"


class TestRunTestsScript(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        scripts = self.root / "scripts"
        (scripts / "tests").mkdir(parents=True)
        (scripts / "report" / "sales").mkdir(parents=True)
        shutil.copy2(SCRIPT, scripts / "run_tests.sh")
        (scripts / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (scripts / "tests" / "test_ok.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n",
            encoding="utf-8")
        (scripts / "report" / "sales" / "x.test.mjs").write_text("// Attrappe\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def node_stub(self, code):
        stub = self.bin / "node"
        stub.write_text(f'#!/bin/sh\necho "# pass 1"\nexit {code}\n', encoding="utf-8")
        stub.chmod(0o755)

    def release_suite(self, passing):
        tests = self.root / "release" / "tests"
        tests.mkdir(parents=True)
        (self.root / "release" / "__init__.py").write_text("", encoding="utf-8")
        (tests / "__init__.py").write_text("", encoding="utf-8")
        body = "pass" if passing else "self.fail('rot')"
        (tests / "test_release.py").write_text(
            f"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_release(self):\n        {body}\n",
            encoding="utf-8")

    def run_script(self):
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")
        return subprocess.run([BASH, str(self.root / "scripts" / "run_tests.sh")], env=env,
                              capture_output=True, text=True, timeout=120)

    def test_all_suites_pass_gives_0(self):
        self.node_stub(0)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("# pass 1", result.stdout)

    def test_the_exit_code_counts_failed_suites(self):
        self.node_stub(1)
        self.release_suite(passing=False)
        result = self.run_script()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_the_release_suite_runs_when_present(self):
        self.node_stub(0)
        self.release_suite(passing=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr.count("Ran 1 test"), 2)

    def test_without_node_the_js_suite_is_skipped_with_a_line(self):
        self.assertIn('echo "JS-Tests übersprungen (node fehlt)"', SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
