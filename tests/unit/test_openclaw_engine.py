import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.openclaw_engine import build_openclaw_prompt, extract_result_block
from geobot_runtime.runtime import GeoBotRuntime


class OpenClawEngineHelpersTest(unittest.TestCase):
    def test_build_prompt_includes_export_path_and_result_contract(self):
        prompt = build_openclaw_prompt(
            user_message="Draw a population density map",
            export_path="C:/tmp/output.png",
            project_id="project_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
        )

        self.assertIn("C:/tmp/output.png", prompt)
        self.assertIn("GEOBOT_RESULT_START", prompt)
        self.assertIn("create_population_density_map", prompt)
        self.assertNotIn('"summary":"..."', prompt)
        self.assertIn("Never output placeholder text", prompt)
        self.assertIn("Never use curl, fetch, Invoke-RestMethod", prompt)

    def test_extract_result_block_reads_plain_json_marker(self):
        text = """
        some text
        GEOBOT_RESULT_START
        {"status":"success","summary":"done","export_path":"C:/tmp/output.png"}
        GEOBOT_RESULT_END
        """
        result = extract_result_block(text)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["export_path"], "C:/tmp/output.png")


class RuntimeFallbackInferenceTest(unittest.TestCase):
    def test_distribution_fallback_uses_best_matching_layer_and_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir)))
            runtime._inspect_project_layers = lambda: [
                {
                    "name": "china_population",
                    "fields": ["province", "population", "density"],
                    "geometry_type": 2,
                }
            ]
            payload = runtime._build_fallback_payload(
                project_id="project_demo",
                template_id="population_distribution",
                message="Please create a population distribution map",
            )
            self.assertEqual(payload["layer_name"], "china_population")
            self.assertEqual(payload["value_field"], "population")
            self.assertEqual(payload["label_field"], "province")

    def test_density_fallback_prefers_explicit_layer_and_weight_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir)))
            runtime._inspect_project_layers = lambda: [
                {
                    "name": "fallback_layer",
                    "fields": ["value"],
                    "geometry_type": 0,
                }
            ]
            payload = runtime._build_fallback_payload(
                project_id="project_demo",
                template_id="population_density",
                message='layer_name="city_points", weight_field="population"',
            )
            self.assertEqual(payload["layer_name"], "city_points")
            self.assertEqual(payload["weight_field"], "population")

    def test_request_requires_export_for_map_generation_but_not_layer_inspection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir)))
            self.assertFalse(runtime._request_requires_export("检查当前QGIS图层", None))
            self.assertTrue(runtime._request_requires_export("绘制中国人口密度图并导出结果", "population_density"))


    def test_teacher_flow_route_is_used_for_teaching_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir)))
            route = runtime._classify_chat_request("Design a lesson about population distribution and generate slides")
            self.assertEqual(route["workflow_type"], "teacher_flow")
            self.assertTrue(route["requires_map"])


if __name__ == "__main__":
    unittest.main()
