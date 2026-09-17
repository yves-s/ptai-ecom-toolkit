"""Auflösung der Betreiber-Schlüssel über drei Ebenen."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from audit import env


class Basis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "workspace"
        self.ws.mkdir()
        self.zentral = Path(self.tmp.name) / "zentral.env"
        self._alt = env.CENTRAL
        env.CENTRAL = self.zentral
        self.addCleanup(lambda: setattr(env, "CENTRAL", self._alt))
        for k in env.OPERATOR_KEYS + env.OPERATOR_SETTINGS:
            os.environ.pop(k, None)

    def schreibe(self, pfad: Path, **values):
        pfad.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")


class TestParseEnv(Basis):
    def test_kommentare_und_leerzeilen_fallen_weg(self):
        self.zentral.write_text("# Kommentar\n\nPTAI_PSI_KEY=abc\n", encoding="utf-8")
        self.assertEqual(env.parse_env(self.zentral), {"PTAI_PSI_KEY": "abc"})

    def test_anfuehrungszeichen_fallen_weg(self):
        self.zentral.write_text('PTAI_PSI_KEY="abc"\nPTAI_GEMINI_KEY=\'d\'\n', encoding="utf-8")
        self.assertEqual(env.parse_env(self.zentral),
                         {"PTAI_PSI_KEY": "abc", "PTAI_GEMINI_KEY": "d"})

    def test_export_praefix_wird_verstanden(self):
        self.zentral.write_text("export PTAI_PSI_KEY=abc\n", encoding="utf-8")
        self.assertEqual(env.parse_env(self.zentral)["PTAI_PSI_KEY"], "abc")

    def test_leerer_wert_zaehlt_als_nicht_gesetzt(self):
        # Sonst verdeckt eine halb ausgefüllte Datei die nächste Ebene.
        self.zentral.write_text("PTAI_PSI_KEY=\n", encoding="utf-8")
        self.assertEqual(env.parse_env(self.zentral), {})

    def test_fehlende_datei_ist_kein_fehler(self):
        self.assertEqual(env.parse_env(Path("/gibt/es/nicht/.env")), {})


class TestReihenfolge(Basis):
    def test_zentral_greift_wenn_sonst_nichts_da_ist(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        self.assertEqual(env.get("PTAI_PSI_KEY", self.ws), "zentral")

    def test_workspace_schlaegt_zentral(self):
        # Ein Kunde mit eigenem Konto soll seines benutzen.
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        self.schreibe(self.ws / ".env", PTAI_PSI_KEY="kunde")
        self.assertEqual(env.get("PTAI_PSI_KEY", self.ws), "kunde")

    def test_umgebung_schlaegt_alles(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        self.schreibe(self.ws / ".env", PTAI_PSI_KEY="kunde")
        os.environ["PTAI_PSI_KEY"] = "umgebung"
        self.addCleanup(lambda: os.environ.pop("PTAI_PSI_KEY", None))
        self.assertEqual(env.get("PTAI_PSI_KEY", self.ws), "umgebung")

    def test_nirgends_gesetzt_ergibt_none(self):
        self.assertIsNone(env.get("PTAI_PSI_KEY", self.ws))

    def test_load_liefert_nur_gesetzte(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="a", PTAI_GEMINI_KEY="b")
        self.assertEqual(sorted(env.load(self.ws)), ["PTAI_GEMINI_KEY", "PTAI_PSI_KEY"])


class TestOrigin(Basis):
    def test_umgebung(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        os.environ["PTAI_PSI_KEY"] = "umgebung"
        self.addCleanup(lambda: os.environ.pop("PTAI_PSI_KEY", None))
        self.assertEqual(env.origin("PTAI_PSI_KEY", self.ws), "Umgebung")

    def test_workspace(self):
        self.schreibe(self.ws / ".env", PTAI_PSI_KEY="kunde")
        self.assertEqual(env.origin("PTAI_PSI_KEY", self.ws), "Workspace-.env")

    def test_zentral(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        self.assertEqual(env.origin("PTAI_PSI_KEY", self.ws), "zentral")

    def test_nirgends_gesetzt_ergibt_none(self):
        self.assertIsNone(env.origin("PTAI_PSI_KEY", self.ws))

    def test_stimmt_mit_status_ueberein(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        self.schreibe(self.ws / ".env", PTAI_GEMINI_KEY="kunde")
        rows = dict(env.status(self.ws))
        self.assertEqual(env.origin("PTAI_PSI_KEY", self.ws), rows["PTAI_PSI_KEY"])
        self.assertEqual(env.origin("PTAI_GEMINI_KEY", self.ws), rows["PTAI_GEMINI_KEY"])
        self.assertIsNone(env.origin("PTAI_DFS_LOGIN", self.ws))


class TestGetTogether(Basis):
    """Login und Passwort dürfen nie aus zwei verschiedenen Ebenen kommen."""

    NAMES = ("PTAI_DFS_LOGIN", "PTAI_DFS_PASSWORD")

    def test_beide_aus_der_umgebung(self):
        os.environ["PTAI_DFS_LOGIN"] = "login-umgebung"
        os.environ["PTAI_DFS_PASSWORD"] = "pw-umgebung"
        self.addCleanup(lambda: os.environ.pop("PTAI_DFS_LOGIN", None))
        self.addCleanup(lambda: os.environ.pop("PTAI_DFS_PASSWORD", None))
        self.assertEqual(env.get_together(self.NAMES, self.ws),
                         ("login-umgebung", "pw-umgebung"))

    def test_beide_aus_dem_workspace_obwohl_zentral_beide_haette(self):
        self.schreibe(self.zentral, PTAI_DFS_LOGIN="zentral", PTAI_DFS_PASSWORD="z")
        self.schreibe(self.ws / ".env", PTAI_DFS_LOGIN="kunde", PTAI_DFS_PASSWORD="k")
        self.assertEqual(env.get_together(self.NAMES, self.ws), ("kunde", "k"))

    def test_login_in_der_umgebung_zieht_das_passwort_nicht_aus_zentral_nach(self):
        # Genau der Fehlerfall, den dfs_client.credentials() bis 11.09.2026 hatte.
        self.schreibe(self.zentral, PTAI_DFS_LOGIN="zentral", PTAI_DFS_PASSWORD="z")
        os.environ["PTAI_DFS_LOGIN"] = "login-umgebung"
        self.addCleanup(lambda: os.environ.pop("PTAI_DFS_LOGIN", None))
        self.assertEqual(env.get_together(self.NAMES, self.ws), ("login-umgebung", None))

    def test_leeres_passwort_im_workspace_faellt_nicht_auf_zentral_zurueck(self):
        self.schreibe(self.zentral, PTAI_DFS_LOGIN="zentral", PTAI_DFS_PASSWORD="z")
        self.schreibe(self.ws / ".env", PTAI_DFS_LOGIN="kunde", PTAI_DFS_PASSWORD="")
        self.assertEqual(env.get_together(self.NAMES, self.ws), ("kunde", None))

    def test_erster_name_nirgends_ergibt_alles_none(self):
        # Das Passwort allein zählt nicht: maßgeblich ist der erste Name.
        self.schreibe(self.zentral, PTAI_DFS_PASSWORD="z")
        self.assertEqual(env.get_together(self.NAMES, self.ws), (None, None))


class TestExportUndStatus(Basis):
    def test_export_setzt_die_umgebung(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="a")
        env.export_env(self.ws)
        self.addCleanup(lambda: os.environ.pop("PTAI_PSI_KEY", None))
        self.assertEqual(os.environ["PTAI_PSI_KEY"], "a")

    def test_export_ueberschreibt_nie_eine_gesetzte_variable(self):
        os.environ["PTAI_PSI_KEY"] = "schon-da"
        self.addCleanup(lambda: os.environ.pop("PTAI_PSI_KEY", None))
        self.schreibe(self.zentral, PTAI_PSI_KEY="zentral")
        env.export_env(self.ws)
        self.assertEqual(os.environ["PTAI_PSI_KEY"], "schon-da")

    def test_status_nennt_die_quelle_und_nie_den_wert(self):
        self.schreibe(self.zentral, PTAI_PSI_KEY="geheim")
        self.schreibe(self.ws / ".env", PTAI_GEMINI_KEY="auch-geheim")
        rows = dict(env.status(self.ws))
        self.assertEqual(rows["PTAI_PSI_KEY"], "zentral")
        self.assertEqual(rows["PTAI_GEMINI_KEY"], "Workspace-.env")
        self.assertEqual(rows["PTAI_DFS_LOGIN"], "FEHLT")
        self.assertNotIn("geheim", " ".join(f"{k}{v}" for k, v in rows.items()))

    def test_status_deckt_betreiber_und_funnel_keys_ab(self):
        self.assertEqual([k for k, _ in env.status(self.ws)],
                         list(env.OPERATOR_KEYS + env.FUNNEL_KEYS + env.OPERATOR_SETTINGS))

    def test_audit_light_braucht_die_funnel_keys(self):
        # Ohne sie scheitert der ID-Weg und der Versand, und beides ist der
        # Normalfall. Der Google-Ads-Token gehört ausdrücklich nicht dazu.
        for k in env.FUNNEL_KEYS:
            self.assertIn(k, env.AUDIT_LIGHT_KEYS)
        self.assertNotIn("PTAI_GOOGLE_ADS_TOKEN", env.AUDIT_LIGHT_KEYS)
        self.assertNotIn("PTAI_DFS_LOGIN", env.AUDIT_LIGHT_KEYS)

    def test_google_credentials_gehoert_nicht_dazu(self):
        # Die Service-Account-JSON ist je Kunde verschieden und bleibt im Workspace.
        self.assertNotIn("PTAI_GOOGLE_CREDENTIALS", env.OPERATOR_KEYS)


class TestOperatorSettings(Basis):
    """Einstellungen des Betreibers stehen in der Übersicht, zählen aber nie als fehlend."""

    SCRIPTS = Path(__file__).resolve().parents[1]

    def test_the_eight_settings(self):
        self.assertEqual(env.OPERATOR_SETTINGS, ("PTAI_ACCOUNTS_ROOT", "PTAI_OPERATOR_NAME",
                                                 "PTAI_OPERATOR_CONTACT", "PTAI_OPERATOR_EMAIL",
                                                 "PTAI_OPERATOR_BOOKING_URL", "PTAI_CLOSING_FILE",
                                                 "PTAI_MAIL_FROM", "PTAI_MAIL_REPLY_TO"))

    def test_a_setting_is_never_a_key(self):
        self.assertFalse(set(env.OPERATOR_SETTINGS) & set(env.OPERATOR_KEYS + env.FUNNEL_KEYS))
        self.schreibe(self.zentral, PTAI_ACCOUNTS_ROOT="/tmp/kunden")
        self.assertNotIn("PTAI_ACCOUNTS_ROOT", env.load(self.ws))

    def test_an_unset_setting_is_not_missing(self):
        rows = dict(env.status(self.ws))
        for name in env.OPERATOR_SETTINGS:
            self.assertEqual(rows[name], env.UNSET, name)
        self.assertNotEqual(env.UNSET, "FEHLT")

    def test_a_set_setting_names_its_origin_not_its_value(self):
        self.schreibe(self.zentral, PTAI_OPERATOR_NAME="Beispiel Beratung")
        rows = dict(env.status(self.ws))
        self.assertEqual(rows["PTAI_OPERATOR_NAME"], "zentral")
        self.assertNotIn("Beispiel Beratung", " ".join(rows.values()))

    def test_the_cli_counts_only_keys(self):
        # Alle Schlüssel stehen zentral, keine Einstellung: es fehlt nichts.
        self.schreibe(self.zentral, **{k: "x" for k in env.OPERATOR_KEYS + env.FUNNEL_KEYS})
        names = env.OPERATOR_KEYS + env.FUNNEL_KEYS + env.OPERATOR_SETTINGS
        clean = {k: v for k, v in os.environ.items() if k not in names}
        clean["PTAI_ENV_FILE"] = str(self.zentral)
        result = subprocess.run([sys.executable, "-m", "audit.env", str(self.ws)],
                                cwd=self.SCRIPTS, env=clean, capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PTAI_ACCOUNTS_ROOT", result.stdout)
        self.assertNotIn("fehlen", result.stderr)


if __name__ == "__main__":
    unittest.main()
