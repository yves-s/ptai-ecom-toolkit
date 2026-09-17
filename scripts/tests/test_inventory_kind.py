"""Die Bestandsaufnahme vor einem Theme-Wechsel als eigene Lauf-Art."""
import unittest

from audit import manifest, publish


class InventoryKind(unittest.TestCase):
    def test_an_inventory_is_a_known_kind(self):
        manifest_data = manifest.empty("beispielbrand", "Beispielbrand")
        manifest_data = manifest.add_run(manifest_data, shop="beispielshop",
                                         run_id="2026-09-10-inventory",
                                         kind="inventory", cadence="inventory",
                                         period=None, run_date="2026-09-10",
                                         files={"inventory.html": 1})
        self.assertEqual(manifest_data["runs"][0]["kind"], "inventory")

    def test_an_inventory_is_not_released_by_publishing(self):
        manifest_data = manifest.add_run(manifest.empty("b", "B"), shop="s",
                                         run_id="2026-09-10-inventory",
                                         kind="inventory", cadence="inventory",
                                         period=None, run_date="2026-09-10",
                                         files={"inventory.html": 1})
        self.assertFalse(manifest_data["runs"][0]["released"])

    def test_the_cadence_names_the_kind(self):
        self.assertEqual(publish.run_kind("2026-09-10-inventory", {"cadence": "inventory"}),
                         ("inventory", "inventory"))


if __name__ == "__main__":
    unittest.main()
