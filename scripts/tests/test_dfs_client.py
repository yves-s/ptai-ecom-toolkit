"""Umschlag, Fehlerpfade und Auth des DataForSEO-Clients.

Kein Test öffnet einen Socket und kein Test kostet Geld: der Transport ist
überall die injizierte Funktion `transport(url, headers, body, timeout)`.
"""
import base64
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

import dfs_client
from audit import env as operator_env


def fake_transport(payload, *, capture=None):
    def transport(url, headers, body, timeout):
        if capture is not None:
            capture.append({"url": url, "headers": headers, "body": body})
        return json.dumps(payload).encode("utf-8")
    return transport


def envelope(*, status=20000, task_status=20000, cost=0.01, result=None, tag=True):
    task = {
        "id": "09061200-1234-0066-0000-abcdef123456",
        "status_code": task_status,
        "status_message": "Ok." if task_status in (20000, 20100) else "Not Found.",
        "cost": cost,
        "path": ["v3", "dataforseo_labs", "google", "ranked_keywords", "live"],
        "data": {"tag": "beispielshop/2026-10-01/dfs_rankings"} if tag else {},
        "result": result,
    }
    return {"version": "0.1.20260901", "status_code": status, "status_message": "Ok.",
            "cost": cost, "tasks_count": 1, "tasks_error": 0, "tasks": [task]}


class TestAuth(unittest.TestCase):
    def test_basic_header_is_base64_of_login_and_password(self):
        self.assertEqual(dfs_client.auth_header("login", "password"),
                         "Basic " + base64.b64encode(b"login:password").decode("ascii"))

    def test_empty_credentials_raise(self):
        with self.assertRaises(ValueError):
            dfs_client.auth_header("", "password")

    def test_error_names_the_env_variables(self):
        with self.assertRaises(ValueError) as caught:
            dfs_client.auth_header("", "")
        self.assertIn("PTAI_DFS_LOGIN", str(caught.exception))


class TestBase(unittest.TestCase):
    def test_sandbox_is_a_different_host(self):
        self.assertNotEqual(dfs_client.BASE_PRODUCTION, dfs_client.BASE_SANDBOX)
        self.assertIn("sandbox", dfs_client.BASE_SANDBOX)

    def test_post_builds_the_full_url(self):
        calls = []
        client = dfs_client.Client("l", "p", base=dfs_client.BASE_SANDBOX,
                                    transport=fake_transport(envelope(), capture=calls))
        client.post("dataforseo_labs/google/ranked_keywords/live", [{"target": "x"}])
        self.assertEqual(
            calls[0]["url"],
            "https://sandbox.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live")

    def test_post_sends_a_list_of_tasks(self):
        calls = []
        client = dfs_client.Client("l", "p", transport=fake_transport(envelope(), capture=calls))
        client.post("x/live", [{"target": "beispielshop.example"}])
        self.assertEqual(json.loads(calls[0]["body"]), [{"target": "beispielshop.example"}])

    def test_post_refuses_a_bare_dict(self):
        # Die API nimmt immer ein Array. Ein Dict käme als Fehler zurück und
        # hätte dann schon eine Anfrage verbraucht.
        client = dfs_client.Client("l", "p", transport=fake_transport(envelope()))
        with self.assertRaises(TypeError):
            client.post("x/live", {"target": "beispielshop.example"})

    def test_is_sandbox_reflects_the_base(self):
        self.assertTrue(dfs_client.Client("l", "p", base=dfs_client.BASE_SANDBOX,
                                           transport=fake_transport(envelope())).is_sandbox)
        self.assertFalse(dfs_client.Client("l", "p",
                                            transport=fake_transport(envelope())).is_sandbox)


class TestEnvelope(unittest.TestCase):
    def test_ok_envelope_passes(self):
        dfs_client.check_envelope(envelope())

    def test_top_level_error_raises(self):
        with self.assertRaises(dfs_client.DfsError):
            dfs_client.check_envelope(envelope(status=40200))

    def test_error_message_carries_the_status(self):
        with self.assertRaises(dfs_client.DfsError) as caught:
            dfs_client.check_envelope(envelope(status=40200))
        self.assertIn("40200", str(caught.exception))

    def test_task_error_raises(self):
        with self.assertRaises(dfs_client.DfsError):
            dfs_client.task_result(envelope(task_status=40400))

    def test_task_created_counts_as_ok(self):
        # 20100 ist die Antwort auf task_post: die Aufgabe wurde angelegt.
        self.assertEqual(dfs_client.task_result(envelope(task_status=20100)), [])

    def test_result_null_is_an_empty_list_not_an_error(self):
        # "keine Daten" ist ein Ergebnis, kein Fehler. Ein Shop ohne Rankings
        # hat schlicht keine.
        self.assertEqual(dfs_client.task_result(envelope(result=None)), [])

    def test_result_is_returned_as_is(self):
        rows = [{"keyword": "ohrstecker"}]
        self.assertEqual(dfs_client.task_result(envelope(result=rows)), rows)

    def test_missing_task_raises(self):
        empty = envelope()
        empty["tasks"] = []
        with self.assertRaises(dfs_client.DfsError):
            dfs_client.task_result(empty)

    def test_cost_comes_from_the_top_level(self):
        # Abgerechnet wird die Anfrage. Der Ledger hält den Betrag, der auf
        # der Rechnung steht.
        self.assertAlmostEqual(dfs_client.envelope_cost(envelope(cost=0.042)), 0.042)

    def test_missing_cost_is_zero_not_a_crash(self):
        broken = envelope()
        del broken["cost"]
        self.assertEqual(dfs_client.envelope_cost(broken), 0.0)

    def test_tag_is_read_back_from_the_task_data(self):
        self.assertEqual(dfs_client.task_tag(envelope()),
                         "beispielshop/2026-10-01/dfs_rankings")

    def test_missing_tag_is_none(self):
        # Ob die Live-Endpunkte `tag` spiegeln, ist laut Spec Abschnitt 19
        # offen. Fehlt er, ist das kein Fehler: die Kostenzuordnung hängt am
        # gesendeten Tag und an `cost`.
        self.assertIsNone(dfs_client.task_tag(envelope(tag=False)))


class TestTransportErrors(unittest.TestCase):
    def test_invalid_json_raises_dfs_error(self):
        def broken(url, headers, body, timeout):
            return b"<html>gateway timeout</html>"
        with self.assertRaises(dfs_client.DfsError):
            dfs_client.Client("l", "p", transport=broken).post("x/live", [{}])

    def test_transport_failure_is_wrapped(self):
        def failing(url, headers, body, timeout):
            raise OSError("connection reset")
        with self.assertRaises(dfs_client.DfsError) as caught:
            dfs_client.Client("l", "p", transport=failing).post("x/live", [{}])
        self.assertIn("connection reset", str(caught.exception))

    def test_http_error_carries_the_code(self):
        def failing(url, headers, body, timeout):
            raise urllib.error.HTTPError("u", 402, "Payment Required", {}, None)
        with self.assertRaises(dfs_client.DfsError) as caught:
            dfs_client.Client("l", "p", transport=failing).post("x/live", [{}])
        self.assertIn("402", str(caught.exception))


class TestCredentials(unittest.TestCase):
    def test_read_from_the_environment(self):
        env = {"PTAI_DFS_LOGIN": "mail@example.com", "PTAI_DFS_PASSWORD": "geheim"}
        self.assertEqual(dfs_client.credentials(env), ("mail@example.com", "geheim"))

    def test_missing_environment_gives_empty_strings(self):
        # Leer, nicht None: auth_header() macht daraus eine Meldung, die die
        # beiden Variablennamen nennt.
        self.assertEqual(dfs_client.credentials({}), ("", ""))


class TestCredentialLookup(unittest.TestCase):
    """Zugangsdaten über dieselbe Suche wie jeder Betreiber-Schlüssel."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name) / "ws"
        self.ws.mkdir()
        self.central = Path(tmp.name) / "central.env"
        old = operator_env.CENTRAL
        operator_env.CENTRAL = self.central
        self.addCleanup(setattr, operator_env, "CENTRAL", old)
        for name in (dfs_client.ENV_LOGIN, dfs_client.ENV_PASSWORD):
            saved = os.environ.pop(name, None)
            if saved is not None:
                self.addCleanup(os.environ.__setitem__, name, saved)

    def test_found_in_the_central_file(self):
        self.central.write_text("PTAI_DFS_LOGIN=zentral@example.com\nPTAI_DFS_PASSWORD=z\n",
                                encoding="utf-8")
        self.assertEqual(dfs_client.credentials(workspace=self.ws),
                         ("zentral@example.com", "z"))

    def test_workspace_beats_central(self):
        self.central.write_text("PTAI_DFS_LOGIN=zentral\nPTAI_DFS_PASSWORD=z\n", encoding="utf-8")
        (self.ws / ".env").write_text("PTAI_DFS_LOGIN=kunde\nPTAI_DFS_PASSWORD=k\n",
                                      encoding="utf-8")
        self.assertEqual(dfs_client.credentials(workspace=self.ws), ("kunde", "k"))

    def test_env_argument_beats_everything(self):
        self.central.write_text("PTAI_DFS_LOGIN=zentral\nPTAI_DFS_PASSWORD=z\n", encoding="utf-8")
        self.assertEqual(dfs_client.credentials({}, workspace=self.ws), ("", ""))

    def test_login_and_password_never_mix_levels(self):
        # Login in der Umgebung, Passwort nur zentral: bis 11.09.2026 kam das
        # Passwort trotzdem aus der zentralen Datei, ein Paar, das so nirgends
        # eingetragen wurde und die API mit 401 ablehnte.
        self.central.write_text("PTAI_DFS_LOGIN=zentral\nPTAI_DFS_PASSWORD=z\n", encoding="utf-8")
        os.environ[dfs_client.ENV_LOGIN] = "umgebung@example.com"
        self.addCleanup(lambda: os.environ.pop(dfs_client.ENV_LOGIN, None))
        self.assertEqual(dfs_client.credentials(workspace=self.ws),
                         ("umgebung@example.com", ""))

    def test_empty_password_in_workspace_does_not_fall_through_to_central(self):
        # Eine halb ausgefüllte Workspace-.env (Login gesetzt, Passwort-Zeile
        # leer) soll nicht das zentrale Passwort zum Login des Kunden mischen.
        self.central.write_text("PTAI_DFS_LOGIN=zentral\nPTAI_DFS_PASSWORD=z\n", encoding="utf-8")
        (self.ws / ".env").write_text("PTAI_DFS_LOGIN=kunde\nPTAI_DFS_PASSWORD=\n",
                                      encoding="utf-8")
        self.assertEqual(dfs_client.credentials(workspace=self.ws), ("kunde", ""))


if __name__ == "__main__":
    unittest.main()
