import json
import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig


class RuntimeConfigTest(unittest.TestCase):
    def test_ensure_dirs_writes_manifest_private_config_and_population_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "app"
            knowledge_root = Path(temp_dir) / "knowledge" / "geography" / "population"
            knowledge_root.mkdir(parents=True, exist_ok=True)

            config = RuntimeConfig(
                app_root=app_root,
                qgis_executable=r"C:\QGIS\qgis-bin.exe",
                population_knowledge_root=knowledge_root,
            )
            config.ensure_dirs()

            runtime_manifest = json.loads((config.runtime_dir / "manifest.json").read_text(encoding="utf-8"))
            private_config = json.loads((config.openclaw_dir / "openclaw.private.json").read_text(encoding="utf-8"))
            population_manifest = json.loads(config.population_dataset_manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(runtime_manifest["product"], "GeoBot")
            self.assertEqual(runtime_manifest["qgis_bridge"]["executable"], r"C:\QGIS\qgis-bin.exe")
            self.assertEqual(runtime_manifest["population_showcase"]["knowledge_root"], str(knowledge_root))
            self.assertFalse(private_config["browser"]["enabled"])
            self.assertEqual(population_manifest["showcase_mode"], config.population_showcase_mode)
            self.assertEqual(population_manifest["knowledge_root"], str(knowledge_root))


if __name__ == "__main__":
    unittest.main()
