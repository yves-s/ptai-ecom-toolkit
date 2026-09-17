"""Eine Tracking-Architektur als kommentierbare Lauf-Art."""
import unittest

from audit import manifest, publish


class TrackingKind(unittest.TestCase):
    def test_tracking_is_a_known_kind(self):
        manifest_data = manifest.add_run(
            manifest.empty("beispielbrand", "Beispielbrand"),
            shop="beispielshop",
            run_id="2026-09-14-tracking",
            kind="tracking",
            cadence="tracking",
            period=None,
            run_date="2026-09-14",
            files={"tracking.html": 1},
        )
        self.assertEqual(manifest_data["runs"][0]["kind"], "tracking")

    def test_the_cadence_names_the_kind(self):
        self.assertEqual(
            publish.run_kind("2026-09-14-tracking", {"cadence": "tracking"}),
            ("tracking", "tracking"),
        )


if __name__ == "__main__":
    unittest.main()
