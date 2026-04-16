import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.templates import TemplateExecutor


class FakeQgisClient:
    def __init__(self):
        self.calls = []
        self.default_session = "session-demo"

    def call(self, tool_name, **tool_params):
        self.calls.append((tool_name, tool_params))
        session = tool_params.get("map_session") or self.default_session

        if tool_name == "create_population_density_map":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "artifacts": {"heatmap_layer": {"layer_name": "density_heatmap"}},
            }
        if tool_name == "create_hu_line_comparison_map":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "artifacts": {"comparison_layer": {"layer_name": "hu_line_dynamic"}},
            }
        if tool_name == "embed_chart":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "artifacts": {"chart_image": "C:/tmp/chart.png"},
            }
        if tool_name == "create_population_migration_map":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "data": {"flow_layer_name": "migration_flow"},
                "artifacts": {"flow_layer": {"layer_name": "migration_flow"}},
            }
        if tool_name == "create_flow_arrows":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "artifacts": {"layer": {"layer_name": "migration_arrow_layer"}},
            }
        if tool_name == "run_population_attraction_model":
            return {
                "status": "success",
                "message": "ok",
                "map_session": session,
                "artifacts": {"layer": {"layer_name": "Population_Attraction"}},
            }
        if tool_name == "export_map":
            return {
                "status": "success",
                "message": "ok",
                "path": tool_params["file_path"],
                "map_session": session,
            }
        return {
            "status": "success",
            "message": "ok",
            "layout_name": tool_params.get("layout_name"),
            "map_session": session,
            "artifacts": {},
            "warnings": [],
        }


class TemplateExecutorTest(unittest.TestCase):
    def build_executor(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = RuntimeConfig(app_root=Path(temp_dir.name))
        config.ensure_dirs()
        qgis = FakeQgisClient()
        return TemplateExecutor(config, qgis), qgis

    def test_execute_routes_distribution_template_to_expected_qgis_tool(self):
        executor, qgis = self.build_executor()

        result = executor.execute(
            project_id="project_demo",
            template_id="population_distribution",
            payload={"layer_name": "china_population", "value_field": "population"},
        )

        self.assertEqual(result["tool_name"], "create_population_distribution_map")
        self.assertEqual(qgis.calls[0][0], "create_population_distribution_map")
        self.assertTrue(result["export_path"].endswith(".png"))
        self.assertIn("export_path", qgis.calls[0][1])

    def test_population_change_comparison_runs_multi_step_showcase_pipeline(self):
        executor, qgis = self.build_executor()

        result = executor.execute(
            project_id="project_demo",
            template_id="population_change_comparison",
            payload={
                "layer_name": "china_population",
                "density_layer_name": "china_population_points",
                "value_field": "population",
                "label_field": "name",
            },
        )

        call_names = [name for name, _params in qgis.calls]
        self.assertEqual(
            call_names,
            [
                "create_population_distribution_map",
                "create_population_density_map",
                "create_hu_line_comparison_map",
                "embed_chart",
                "auto_layout",
                "customize_layout_legend",
                "export_map",
            ],
        )
        self.assertEqual(result["tool_name"], "population_change_comparison")
        self.assertIn("chart_preview", result["artifact_bundle"])
        self.assertTrue(result["export_path"].endswith(".png"))

    def test_population_capacity_dashboard_embeds_primary_chart(self):
        executor, qgis = self.build_executor()

        result = executor.execute(
            project_id="project_demo",
            template_id="population_capacity_dashboard",
            payload={
                "layer_name": "province_capacity",
                "value_field": "capacity",
                "label_field": "name",
            },
        )

        call_names = [name for name, _params in qgis.calls]
        self.assertEqual(
            call_names,
            [
                "create_population_distribution_map",
                "embed_chart",
                "auto_layout",
                "customize_layout_legend",
                "export_map",
            ],
        )
        self.assertEqual(result["tool_name"], "population_capacity_dashboard")
        self.assertIn("primary_chart", result["artifact_bundle"])

    def test_population_migration_supports_existing_line_layer(self):
        executor, qgis = self.build_executor()

        result = executor.execute(
            project_id="project_demo",
            template_id="population_migration",
            payload={"line_layer_name": "migration_flows", "width_field": "migration_count"},
        )

        call_names = [name for name, _params in qgis.calls]
        self.assertEqual(call_names, ["create_flow_arrows", "auto_layout", "customize_layout_legend", "export_map"])
        self.assertEqual(result["tool_name"], "create_flow_arrows")


if __name__ == "__main__":
    unittest.main()
