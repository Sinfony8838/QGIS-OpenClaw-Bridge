import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.templates import TemplateExecutor


class FakeQgisClient:
    def __init__(self):
        self.calls = []

    def call(self, tool_name, **tool_params):
        self.calls.append((tool_name, tool_params))
        return {
            "status": "success",
            "message": "ok",
            "layout_name": tool_params.get("layout_name"),
            "artifacts": {},
            "warnings": [],
        }


class TemplateExecutorTest(unittest.TestCase):
    def test_execute_routes_template_to_expected_qgis_tool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(app_root=Path(temp_dir))
            config.ensure_dirs()
            qgis = FakeQgisClient()
            executor = TemplateExecutor(config, qgis)

            result = executor.execute(
                project_id="project_demo",
                template_id="population_distribution",
                payload={"layer_name": "china_population", "value_field": "population"},
            )

            self.assertEqual(result["tool_name"], "create_population_distribution_map")
            self.assertEqual(qgis.calls[0][0], "create_population_distribution_map")
            self.assertTrue(result["export_path"].endswith(".png"))
            self.assertIn("export_path", qgis.calls[0][1])


if __name__ == "__main__":
    unittest.main()
