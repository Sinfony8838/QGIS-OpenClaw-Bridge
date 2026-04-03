import json
import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig


class RuntimeConfigTest(unittest.TestCase):
    def test_ensure_dirs_writes_manifest_and_private_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(app_root=Path(temp_dir), qgis_executable=r"C:\QGIS\qgis-bin.exe")
            config.ensure_dirs()

            manifest = json.loads((config.runtime_dir / "manifest.json").read_text(encoding="utf-8"))
            private_config = json.loads((config.openclaw_dir / "openclaw.private.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["product"], "GeoBot")
            self.assertEqual(manifest["qgis_bridge"]["executable"], r"C:\QGIS\qgis-bin.exe")
            self.assertFalse(private_config["browser"]["enabled"])


if __name__ == "__main__":
    unittest.main()
