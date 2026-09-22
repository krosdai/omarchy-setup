"""Portable checks for the index, without requiring sibling clones or a desktop."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class IndexTest(unittest.TestCase):
    def test_inventory_has_unique_ids_and_sources(self):
        plugins = json.loads((ROOT / "plugins.json").read_text())
        self.assertTrue(plugins)
        self.assertEqual(len({plugin["id"] for plugin in plugins}), len(plugins))
        self.assertEqual(len({plugin["repository"] for plugin in plugins}), len(plugins))
        for plugin in plugins:
            with self.subTest(plugin=plugin["id"]):
                self.assertEqual(set(plugin), {"id", "name", "source", "repository"})
                self.assertTrue(plugin["name"])
                self.assertIn(plugin["source"], {"maintained", "external"})
                self.assertRegex(plugin["repository"], r"^https://github\.com/[\w-]+/[\w.-]+\.git$")
                if plugin["source"] == "maintained":
                    feature = plugin["id"].removeprefix("krosdai.")
                    self.assertTrue(plugin["id"].startswith("krosdai."))
                    self.assertEqual(
                        plugin["repository"], f"https://github.com/krosdai/omarchy-{feature}.git"
                    )

    def test_every_plugin_has_documented_id_and_install_command(self):
        readme = (ROOT / "README.md").read_text()
        for plugin in json.loads((ROOT / "plugins.json").read_text()):
            with self.subTest(plugin=plugin["id"]):
                self.assertIn(f"`{plugin['id']}`", readme)
                repository = plugin["repository"]
                self.assertIn(f"omarchy plugin add {repository} --enable", readme)
        self.assertNotIn("/home/xdanger/", readme)
        self.assertNotIn("omarchy plugin add https://github.com/krosdai/omarchy-setup", readme)

    def test_index_no_longer_ships_feature_entrypoints(self):
        for name in ("manifest.json", "Service.qml", "install.py", "setup_timezone.py"):
            with self.subTest(path=name):
                self.assertFalse((ROOT / name).exists())
        for directory in ("presets", "timezone"):
            self.assertEqual(list((ROOT / directory).glob("*")), [])


if __name__ == "__main__":
    unittest.main()
