import tempfile
import unittest
from pathlib import Path

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.openclaw_engine import build_openclaw_prompt
from geobot_runtime.runtime import GeoBotRuntime


class StyleIntentPromptTest(unittest.TestCase):
    def test_build_qgis_prompt_locks_direct_recolor_requests_to_single_symbol_tools(self):
        prompt = build_openclaw_prompt(
            user_message="change the current layer to yellow",
            export_path="",
            project_id="project_demo",
            request_id="req_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
            workflow_mode="qgis_only",
            requires_export=False,
        )

        self.assertIn("direct current-project style edit, not a thematic map", prompt)
        self.assertIn("Do not use apply_graduated_renderer()", prompt)
        self.assertIn("Use set_layer_style() or set_style()", prompt)
        self.assertIn("The requested color must remain exactly #FFFF00.", prompt)
        self.assertIn("A ramp-based or blue result is incorrect", prompt)


class RuntimeDirectStyleFastPathTest(unittest.TestCase):
    def build_runtime(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir.name)))

    def build_stateful_qgis_client(self):
        class StatefulQgisClient:
            def __init__(self):
                self.calls = []
                self.layers = [
                    {
                        "name": "china_population",
                        "id": "layer_1",
                        "geometry_type": "polygon",
                        "is_visible": True,
                        "is_active": True,
                        "labels_enabled": True,
                        "order_index": 0,
                        "fields": ["name", "population"],
                    },
                    {
                        "name": "roads",
                        "id": "layer_2",
                        "geometry_type": "line",
                        "is_visible": True,
                        "is_active": False,
                        "labels_enabled": False,
                        "order_index": 1,
                        "fields": ["name"],
                    },
                ]
                self.styles = {
                    "layer_1": {
                        "renderer_type": "single_symbol",
                        "fill_color": "#CCCCCC",
                        "outline_color": "#000000",
                        "line_color": "",
                        "line_width": 0.5,
                        "opacity": 1.0,
                    }
                }

            def _layer(self, layer_id):
                for layer in self.layers:
                    if layer["id"] == layer_id:
                        return layer
                raise AssertionError(f"Unknown layer id: {layer_id}")

            def call(self, tool_name, **tool_params):
                self.calls.append((tool_name, tool_params))
                if tool_name == "get_layers":
                    return {"status": "success", "data": [dict(layer) for layer in self.layers]}
                if tool_name == "set_layer_visibility":
                    self._layer(tool_params["layer_id"])["is_visible"] = bool(tool_params["visible"])
                    return {"status": "success", "artifacts": {"layer": {"layer_id": tool_params["layer_id"]}}}
                if tool_name == "set_layer_labels":
                    layer = self._layer(tool_params["layer_id"])
                    layer["labels_enabled"] = bool(tool_params.get("enabled", True))
                    return {"status": "success", "artifacts": {"layer": {"layer_id": layer["id"]}}}
                if tool_name == "move_layer":
                    layer = self._layer(tool_params["layer_id"])
                    others = [item for item in self.layers if item["id"] != layer["id"]]
                    self.layers = ([layer] + others) if tool_params["position"] == "top" else (others + [layer])
                    for index, item in enumerate(self.layers):
                        item["order_index"] = index
                    return {"status": "success", "artifacts": {"layer": {"layer_id": layer["id"]}}}
                if tool_name == "set_active_layer":
                    for item in self.layers:
                        item["is_active"] = item["id"] == tool_params["layer_id"]
                    return {"status": "success", "artifacts": {"layer": {"layer_id": tool_params["layer_id"]}}}
                if tool_name == "zoom_to_layer":
                    return {"status": "success", "artifacts": {"layer": {"layer_id": tool_params["layer_id"]}}}
                if tool_name == "set_layer_style":
                    style = self.styles.setdefault(
                        tool_params["layer_id"],
                        {
                            "renderer_type": "single_symbol",
                            "fill_color": "",
                            "outline_color": "",
                            "line_color": "",
                            "line_width": 0.0,
                            "opacity": 1.0,
                        },
                    )
                    if "fill_color" in tool_params:
                        style["fill_color"] = tool_params["fill_color"].upper()
                    if "outline_color" in tool_params:
                        style["outline_color"] = tool_params["outline_color"].upper()
                    if "line_color" in tool_params:
                        style["line_color"] = tool_params["line_color"].upper()
                    if "line_width" in tool_params:
                        style["line_width"] = float(tool_params["line_width"])
                    if "outline_width" in tool_params:
                        style["line_width"] = float(tool_params["outline_width"])
                    if "opacity" in tool_params:
                        style["opacity"] = float(tool_params["opacity"])
                    return {"status": "success", "artifacts": {"layer": {"layer_id": tool_params["layer_id"]}}}
                if tool_name == "get_layer_style":
                    return {"status": "success", "data": dict(self.styles[tool_params["layer_id"]]), "artifacts": {"layer": {"layer_id": tool_params["layer_id"]}}}
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        return StatefulQgisClient()

    def test_qgis_only_direct_recolor_bypasses_openclaw_and_verifies_style(self):
        runtime = self.build_runtime()

        class StubQgisClient:
            def __init__(self):
                self.calls = []

            def call(self, tool_name, **tool_params):
                self.calls.append((tool_name, tool_params))
                if tool_name == "get_layers":
                    return {
                        "status": "success",
                        "data": [
                            {
                                "name": "china_population",
                                "id": "layer_1",
                                "geometry_type": "polygon",
                                "is_visible": True,
                                "is_active": True,
                                "fields": ["name", "population"],
                            }
                        ],
                    }
                if tool_name == "set_layer_style":
                    return {
                        "status": "success",
                        "message": "Single symbol style applied",
                        "artifacts": {
                            "layer": {
                                "artifact_type": "layer",
                                "title": "china_population",
                                "layer_id": "layer_1",
                                "layer_name": "china_population",
                            }
                        },
                    }
                if tool_name == "get_layer_style":
                    return {
                        "status": "success",
                        "data": {
                            "renderer_type": "single_symbol",
                            "fill_color": "#FFFF00",
                            "outline_color": "",
                            "line_color": "",
                            "line_width": 0.0,
                            "opacity": 1.0,
                        },
                        "artifacts": {
                            "layer": {
                                "artifact_type": "layer",
                                "title": "china_population",
                                "layer_id": "layer_1",
                                "layer_name": "china_population",
                            }
                        },
                    }
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct recolor request")

        runtime.qgis = StubQgisClient()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("change the current layer to yellow", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "change the current layer to yellow"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "change the current layer to yellow", route)

        self.assertEqual(runtime.qgis.calls[0][0], "get_layers")
        self.assertEqual(runtime.qgis.calls[1][0], "set_layer_style")
        self.assertEqual(runtime.qgis.calls[1][1]["fill_color"], "#FFFF00")
        self.assertEqual(runtime.qgis.calls[2][0], "get_layer_style")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["verification"]["status"], "verified")
        self.assertEqual(result["verification"]["expected_style"]["fill_color"], "#FFFF00")
        self.assertEqual(result["engine"], "qgis-bridge-direct")

    def test_qgis_only_direct_visibility_bypasses_openclaw(self):
        runtime = self.build_runtime()

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct visibility request")

        runtime.qgis = self.build_stateful_qgis_client()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("隐藏当前图层", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "隐藏当前图层"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "隐藏当前图层", route)

        self.assertEqual(runtime.qgis.calls[1][0], "set_layer_visibility")
        self.assertFalse(runtime.qgis.calls[1][1]["visible"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["verification"]["observed_style"]["china_population"]["is_visible"], False)

    def test_qgis_only_direct_label_disable_bypasses_openclaw(self):
        runtime = self.build_runtime()

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct label request")

        runtime.qgis = self.build_stateful_qgis_client()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("关闭当前图层标注", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "关闭当前图层标注"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "关闭当前图层标注", route)

        self.assertEqual(runtime.qgis.calls[1][0], "set_layer_labels")
        self.assertFalse(runtime.qgis.calls[1][1]["enabled"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["verification"]["observed_style"]["china_population"]["labels_enabled"], False)

    def test_qgis_only_direct_order_bypasses_openclaw(self):
        runtime = self.build_runtime()

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct order request")

        runtime.qgis = self.build_stateful_qgis_client()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("将 roads 置顶", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "将 roads 置顶"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "将 roads 置顶", route)

        self.assertEqual(runtime.qgis.calls[1][0], "move_layer")
        self.assertEqual(runtime.qgis.calls[1][1]["position"], "top")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["verification"]["observed_style"]["roads"]["order_index"], 0)

    def test_qgis_only_direct_activate_and_zoom_bypasses_openclaw(self):
        runtime = self.build_runtime()

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct activate-and-zoom request")

        runtime.qgis = self.build_stateful_qgis_client()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("选中 roads 并缩放到图层", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "选中 roads 并缩放到图层"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "选中 roads 并缩放到图层", route)

        self.assertEqual(runtime.qgis.calls[1][0], "set_active_layer")
        self.assertEqual(runtime.qgis.calls[2][0], "zoom_to_layer")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verification"]["observed_style"]["roads"]["is_active"])

    def test_qgis_only_direct_opacity_bypasses_openclaw(self):
        runtime = self.build_runtime()

        class FailingAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                raise AssertionError("OpenClaw should not be called for a direct opacity request")

        runtime.qgis = self.build_stateful_qgis_client()
        runtime.assistant_engine = FailingAssistantEngine()

        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("将当前图层透明度改为 50%", task_mode="qgis_only")
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "将当前图层透明度改为 50%"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "将当前图层透明度改为 50%", route)

        self.assertEqual(runtime.qgis.calls[1][0], "set_layer_style")
        self.assertEqual(runtime.qgis.calls[1][1]["opacity"], 0.5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["verification"]["expected_style"]["opacity"], 0.5)


if __name__ == "__main__":
    unittest.main()
