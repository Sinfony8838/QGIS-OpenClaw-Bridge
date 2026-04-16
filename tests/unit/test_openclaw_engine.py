import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.openclaw_engine import OpenClawBridge, OpenClawEngine, build_openclaw_prompt, extract_result_block
from geobot_runtime.runtime import GeoBotRuntime


class OpenClawEngineHelpersTest(unittest.TestCase):
    @unittest.skip("Legacy prompt assertions were style-specific and have been replaced.")
    def test_build_qgis_prompt_describes_direct_qgis_execution_contract(self):
        prompt = build_openclaw_prompt(
            user_message="将图层改为黄色",
            export_path="",
            project_id="project_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
            workflow_mode="qgis_only",
            requires_export=False,
        )

        self.assertIn("Start by calling get_layers()", prompt)
        self.assertIn("set_style()", prompt)
        self.assertIn("set_layer_style()", prompt)
        self.assertIn("Do not switch to lesson_ppt", prompt)
        self.assertIn("Leave export_path as an empty string", prompt)
        self.assertIn("GEOBOT_RESULT_START", prompt)
        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("Do not produce lesson plans or PPT outputs in this mode.", prompt)
        self.assertNotIn("Completed the requested QGIS-only task.", prompt)
        self.assertNotIn("package_contract", prompt)
        self.assertNotIn("guidance_pack", prompt)
        self.assertNotIn("slide_contract", prompt)

    @unittest.skip("Legacy prompt assertions were style-specific and have been replaced.")
    def test_build_qgis_prompt_requires_request_id_and_verification(self):
        prompt = build_openclaw_prompt(
            user_message="change the current layer to yellow",
            export_path="",
            project_id="project_demo",
            request_id="req_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
            workflow_mode="qgis_only",
            requires_export=False,
        )

        self.assertIn("The current GeoBot request_id is: req_demo", prompt)
        self.assertIn("request_id, status, summary", prompt)
        self.assertIn("verification", prompt)
        self.assertIn("get_layer_style()", prompt)
        self.assertIn("#FFFF00", prompt)
        self.assertIn("is_visible", prompt)
        self.assertIn("is_active", prompt)
        self.assertIn("all currently visible operable layers where is_visible=true", prompt)
        self.assertIn("verification.status=verified", prompt)

    def test_build_qgis_prompt_describes_professional_extensible_assistant_contract(self):
        prompt = build_openclaw_prompt(
            user_message="change the current layer style",
            export_path="",
            project_id="project_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
            workflow_mode="qgis_only",
            requires_export=False,
        )

        self.assertIn("professional QGIS execution assistant", prompt)
        self.assertIn("capable, extensible GIS operator", prompt)
        self.assertIn("inspect layers, prepare data, run analysis, style layers, compose layouts, and export results", prompt)
        self.assertIn("run_python_code() only as an expert fallback", prompt)
        self.assertIn("Never invent styles, colors, field names, classification breaks, layer names, output paths, or template ids", prompt)
        self.assertNotIn("#FFFF00", prompt)
        self.assertNotIn("When the user requests yellow", prompt)

    def test_build_qgis_prompt_requires_safe_targeting_and_operation_specific_verification(self):
        prompt = build_openclaw_prompt(
            user_message="change the current layer to yellow",
            export_path="",
            project_id="project_demo",
            request_id="req_demo",
            qgis_skill_dir=Path("C:/skills/qgis-solver"),
            workflow_mode="qgis_only",
            requires_export=False,
        )

        self.assertIn("The current GeoBot request_id is: req_demo", prompt)
        self.assertIn("prefer the active layer where is_active=true", prompt)
        self.assertIn("Only fall back to visible operable layers", prompt)
        self.assertIn("If the target is ambiguous and acting would risk modifying the wrong layer, do not guess.", prompt)
        self.assertIn("For style edits, verify the observed post-action state with get_layer_style()", prompt)
        self.assertIn("For non-style operations, verify with the most relevant read-back tool", prompt)
        self.assertIn("workflow_type must be exactly: qgis_only", prompt)
        self.assertIn("verification.status=verified", prompt)

    def test_lesson_ppt_population_prompt_includes_contract_and_profile(self):
        prompt = build_openclaw_prompt(
            user_message="请生成完整人口单元教学成果包与答辩 PPT",
            export_path="",
            project_id="project_demo",
            workflow_mode="lesson_ppt",
            knowledge_root="C:/knowledge/population",
            dataset_manifest_path="C:/runtime/population_manifest.json",
            showcase_mode="population_unit",
            lesson_plan_path="C:/tmp/lesson_plan.md",
            pptx_path="C:/tmp/flagship.pptx",
            requires_map=False,
            expected_artifacts={
                "lesson_plan": {"artifact_type": "lesson_plan", "title": "Lesson Plan", "path": "C:/tmp/lesson_plan.md"},
                "guidance": {"artifact_type": "markdown", "title": "Guidance", "path": "C:/tmp/guidance.md"},
                "pptx": {"artifact_type": "pptx", "title": "Deck", "path": "C:/tmp/flagship.pptx"},
            },
            knowledge_bundle={"theme1_refs": [{"title": "theme1", "excerpt": "人口分布"}]},
            package_profile={"profile_id": "population_unit", "suggested_module_roles": ["population_distribution", "population_migration"]},
        )

        self.assertIn("showcase_mode=population_unit", prompt)
        self.assertIn("C:/knowledge/population", prompt)
        self.assertIn("C:/runtime/population_manifest.json", prompt)
        self.assertIn("Do not call QGIS", prompt)
        self.assertIn("Do not read ppt-studio", prompt)
        self.assertIn("Do not return actual artifact paths", prompt)
        self.assertIn("theme1_refs", prompt)
        self.assertIn("package_contract", prompt)
        self.assertIn("suggested_module_roles", prompt)
        self.assertIn("curriculum_requirements", prompt)
        self.assertIn("guidance_pack", prompt)
        self.assertIn("homework_pack", prompt)
        self.assertIn("review_pack", prompt)
        self.assertIn("project_advantages", prompt)
        self.assertIn("modules", prompt)
        self.assertNotIn('"slide_id": "cover"', prompt)
        self.assertNotIn('"theme_id": "theme1"', prompt)
        self.assertNotIn("complete multi-file teaching package for Theme 1 / Theme 2 / Theme 3", prompt)
        self.assertNotIn("generate PPT/PDF files", prompt.split("User request:")[1] if "User request:" in prompt else "")

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


class RuntimeRoutingTest(unittest.TestCase):
    def build_runtime(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return GeoBotRuntime(config=RuntimeConfig(app_root=Path(temp_dir.name)))

    def test_distribution_fallback_uses_best_matching_layer_and_field(self):
        runtime = self.build_runtime()
        runtime._inspect_project_layers = lambda: [
            {"name": "china_population", "fields": ["province", "population", "density"], "geometry_type": 2}
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
        runtime = self.build_runtime()
        runtime._inspect_project_layers = lambda: [{"name": "fallback_layer", "fields": ["value"], "geometry_type": 0}]
        payload = runtime._build_fallback_payload(
            project_id="project_demo",
            template_id="population_density",
            message='layer_name="city_points", weight_field="population"',
        )
        self.assertEqual(payload["layer_name"], "city_points")
        self.assertEqual(payload["weight_field"], "population")

    def test_request_requires_export_for_map_generation_but_not_layer_inspection(self):
        runtime = self.build_runtime()
        self.assertFalse(runtime._request_requires_export("检查当前 QGIS 图层", None))
        self.assertTrue(runtime._request_requires_export("绘制中国人口密度图并导出结果", "population_density"))

    def test_lesson_requests_default_to_lesson_ppt(self):
        runtime = self.build_runtime()
        route = runtime._classify_chat_request("请完成人口单元答辩展示，并生成教学设计和 PPT")
        self.assertEqual(route["workflow_type"], "lesson_ppt")
        self.assertEqual(route["task_mode"], "lesson_ppt")
        self.assertEqual(route["showcase_mode"], runtime.config.population_showcase_mode)
        self.assertEqual(route["fallback_template"], "population_change_comparison")
        self.assertFalse(route["requires_map"])

    def test_explicit_lesson_task_mode_overrides_legacy_teacher_flow(self):
        runtime = self.build_runtime()
        route = runtime._classify_chat_request("请生成教案和答辩 PPT", task_mode="teacher_flow", presentation_style="minimal")
        self.assertEqual(route["workflow_type"], "lesson_ppt")
        self.assertEqual(route["task_mode"], "lesson_ppt")
        self.assertEqual(route["route"], "lesson_ppt")
        self.assertEqual(route["presentation_style"], "minimal")

    def test_explicit_qgis_only_task_mode_uses_direct_agent_route(self):
        runtime = self.build_runtime()
        route = runtime._classify_chat_request("将图层改为黄色", task_mode="qgis_only")
        self.assertEqual(route["workflow_type"], "qgis_only")
        self.assertEqual(route["task_mode"], "qgis_only")
        self.assertEqual(route["route"], "qgis_only")
        self.assertIsNone(route["suggested_template"])
        self.assertTrue(route["requires_map"])
        self.assertFalse(route["requires_export"])

    def test_default_direct_qgis_edit_routes_to_qgis_only(self):
        runtime = self.build_runtime()
        route = runtime._classify_chat_request("change the layer to yellow")
        self.assertEqual(route["workflow_type"], "qgis_only")
        self.assertEqual(route["route"], "qgis_only")
        self.assertFalse(route["requires_export"])

    def test_default_stages_skip_map_for_lesson_ppt(self):
        runtime = self.build_runtime()
        stages = runtime._default_stages("lesson_ppt", requires_map=False)
        self.assertEqual(stages["map"]["status"], "skipped")
        self.assertIn("lesson_ppt", stages["map"]["summary"])

    def test_default_stages_skip_design_and_presentation_for_qgis_only(self):
        runtime = self.build_runtime()
        stages = runtime._default_stages("qgis_only", requires_map=True, route_name="qgis_only")
        self.assertEqual(stages["design"]["status"], "skipped")
        self.assertEqual(stages["presentation"]["status"], "skipped")
        self.assertIn("QGIS", stages["map"]["summary"])

    def test_format_layers_notes_includes_geometry_type_and_fields(self):
        runtime = self.build_runtime()
        notes = runtime._format_layers_notes(
            [{"name": "中国省份人口", "provider": "ogr", "type": 0, "geometry_type": "polygon", "crs": "EPSG:4326", "fields": ["name", "population"]}]
        )
        self.assertIn("几何类型=polygon", notes)
        self.assertIn("字段=name, population", notes)

    @unittest.skip("Direct style edits now bypass OpenClaw through the QGIS bridge.")
    def test_run_qgis_only_request_uses_openclaw_context_without_export_for_style_edit(self):
        runtime = self.build_runtime()
        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("将图层改为黄色", task_mode="qgis_only")
        captured = {}

        class StubAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                captured["project_id"] = project_id
                captured["message"] = message
                captured["context"] = dict(context or {})
                return {
                    "status": "success",
                    "summary": "Layer color updated.",
                    "assistant_message": "已将图层颜色改为黄色。",
                    "template_id": "",
                    "notes": "Targeted the current polygon layer after inspecting get_layers().",
                    "export_path": "",
                    "stages": {
                        "analysis": {"status": "success", "summary": "Parsed the QGIS request.", "detail": ""},
                        "design": {"status": "skipped", "summary": "Lesson design was not required.", "detail": ""},
                        "map": {"status": "success", "summary": "Updated the current layer style.", "detail": ""},
                        "presentation": {"status": "skipped", "summary": "PPT generation was not required.", "detail": ""},
                    },
                    "artifacts": {},
                    "steps": [{"title": "Calling QGIS", "detail": "Updated current layer style.", "status": "success"}],
                    "engine": {"name": "stub-openclaw", "mode": "test"},
                }

        runtime.assistant_engine = StubAssistantEngine()
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "将图层改为黄色"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "将图层改为黄色", route)

        self.assertEqual(captured["project_id"], project["project_id"])
        self.assertEqual(captured["context"]["workflow_mode"], "qgis_only")
        self.assertFalse(captured["context"]["requires_export"])
        self.assertEqual(captured["context"]["export_path"], "")
        self.assertEqual(result["workflow_type"], "qgis_only")
        self.assertEqual(result["task_mode"], "qgis_only")
        self.assertEqual(result["summary"], "Layer color updated.")

    @unittest.skip("Direct style edits now bypass OpenClaw through the QGIS bridge.")
    def test_run_qgis_only_request_preserves_request_id_and_verification(self):
        runtime = self.build_runtime()
        project = runtime.create_project(name="Test Project")
        route = runtime._classify_chat_request("change the current layer to yellow", task_mode="qgis_only")

        class StubAssistantEngine:
            name = "stub-openclaw"

            def chat(self, project_id, message, context=None):
                return {
                    "status": "success",
                    "request_id": context["request_id"],
                    "summary": "已完成样式修改。",
                    "assistant_message": "已将当前可见图层统一改为黄色，并完成样式回读验证。",
                    "template_id": "",
                    "notes": "已回读 get_layer_style()。",
                    "export_path": "",
                    "stages": {
                        "analysis": {"status": "success", "summary": "已解析请求。", "detail": ""},
                        "design": {"status": "skipped", "summary": "不需要教学设计。", "detail": ""},
                        "map": {"status": "success", "summary": "已完成样式修改和验证。", "detail": ""},
                        "presentation": {"status": "skipped", "summary": "不需要 PPT。", "detail": ""},
                    },
                    "verification": {
                        "status": "verified",
                        "checked_layers": ["china_population"],
                        "expected_style": {"fill_color": "#FFFF00"},
                        "observed_style": {"china_population": {"fill_color": "#FFFF00"}},
                        "mismatches": [],
                    },
                    "artifacts": {},
                    "steps": [],
                    "engine": {"name": "stub-openclaw", "mode": "test"},
                }

        runtime.assistant_engine = StubAssistantEngine()
        job = runtime.store.create_job(
            project_id=project["project_id"],
            job_type="chat",
            title="QGIS only",
            workflow_type=route["workflow_type"],
            request={"message": "change the current layer to yellow"},
            stages=runtime._default_stages(route["workflow_type"], requires_map=route["requires_map"], route_name=route["route"]),
        )

        result = runtime._run_qgis_only_request(job.job_id, project["project_id"], "change the current layer to yellow", route)

        self.assertEqual(result["request_id"], f"{job.job_id}_qgis_only")
        self.assertEqual(result["verification"]["status"], "verified")
        self.assertEqual(result["verification"]["expected_style"]["fill_color"], "#FFFF00")

    def test_lesson_timeout_recovers_existing_package_files(self):
        runtime = self.build_runtime()
        with tempfile.TemporaryDirectory() as temp_dir:
            lesson_plan_path = Path(temp_dir) / "lesson_plan.md"
            lesson_plan_docx_path = Path(temp_dir) / "lesson_plan.docx"
            guidance_path = Path(temp_dir) / "guidance.md"
            pptx_path = Path(temp_dir) / "deck.pptx"
            lesson_plan_path.write_text("# Lesson\n", encoding="utf-8")
            lesson_plan_docx_path.write_text("word", encoding="utf-8")
            guidance_path.write_text("# Guidance\n", encoding="utf-8")
            result = runtime._recover_lesson_ppt_timeout_result(
                context={
                    "expected_artifacts": {
                        "lesson_plan": {"artifact_type": "lesson_plan", "title": "Lesson", "path": str(lesson_plan_path)},
                        "lesson_plan_docx": {"artifact_type": "docx", "title": "Lesson Word", "path": str(lesson_plan_docx_path)},
                        "guidance": {"artifact_type": "markdown", "title": "Guidance", "path": str(guidance_path)},
                        "pptx": {"artifact_type": "pptx", "title": "Deck", "path": str(pptx_path)},
                    }
                },
                route={},
                error_message="Timed out while waiting for OpenClaw to finish the task",
            )

            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["partial_output"])
            self.assertIn("lesson_plan", result["artifacts"])
            self.assertIn("lesson_plan_docx", result["artifacts"])
            self.assertIn("guidance", result["artifacts"])
            self.assertNotIn("pptx", result["artifacts"])
            self.assertIn("建议 QGIS 操作", lesson_plan_path.read_text(encoding="utf-8"))


class OpenClawBridgeTransportTest(unittest.TestCase):
    def build_config(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = RuntimeConfig(app_root=Path(temp_dir.name))
        config.desktop_automation_bridge_url = "http://bridge.test"
        return config

    def test_openclaw_engine_chat_allows_qgis_only_without_export_path(self):
        engine = OpenClawEngine(self.build_config())
        engine.supervisor.ensure_ready = lambda: None

        captured = {}

        def fake_bridge_chat(**kwargs):
            captured.update(kwargs)
            return {
                "status": "success",
                "summary": "Updated the current layer style.",
                "assistant_message": "Updated the current layer style.",
                "workflow_type": "qgis_only",
                "export_path": "",
                "template_id": "",
                "notes": "Executed through qgis-solver.",
                "stages": {},
                "artifacts": {},
                "steps": [],
            }

        engine.bridge.chat = fake_bridge_chat
        result = engine.chat(
            "project_demo",
            "将图层改为黄色",
            context={
                "workflow_mode": "qgis_only",
                "requires_export": False,
                "export_path": "",
                "suggested_template": "",
                "fallback_template": "",
            },
        )

        self.assertEqual(captured["workflow_mode"], "qgis_only")
        self.assertFalse(captured["requires_export"])
        self.assertEqual(captured["export_path"], "")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["export_path"], "")

    def test_openclaw_engine_prefers_assistant_message_over_summary_for_chat(self):
        engine = OpenClawEngine(self.build_config())
        engine.supervisor.ensure_ready = lambda: None
        engine.bridge.chat = lambda **kwargs: {
            "status": "success",
            "summary": "摘要",
            "assistant_message": "更完整的中文回复",
            "workflow_type": "qgis_only",
            "export_path": "",
            "template_id": "",
            "notes": "备注",
            "stages": {},
            "artifacts": {},
            "steps": [],
        }

        result = engine.chat(
            "project_demo",
            "检查QGIS连接状态",
            context={"workflow_mode": "qgis_only", "requires_export": False, "export_path": ""},
        )

        self.assertEqual(result["assistant_message"], "更完整的中文回复")
        self.assertEqual(result["summary"], "摘要")

    def test_openclaw_engine_chat_preserves_request_id_and_verification(self):
        engine = OpenClawEngine(self.build_config())
        engine.supervisor.ensure_ready = lambda: None
        engine.bridge.chat = lambda **kwargs: {
            "status": "success",
            "request_id": kwargs["request_id"],
            "summary": "已完成样式修改。",
            "assistant_message": "已将当前图层修改为黄色，并完成验证。",
            "workflow_type": "qgis_only",
            "export_path": "",
            "template_id": "",
            "notes": "验证通过。",
            "stages": {},
            "artifacts": {},
            "verification": {
                "status": "verified",
                "checked_layers": ["china_population"],
                "expected_style": {"fill_color": "#FFFF00"},
                "observed_style": {"china_population": {"fill_color": "#FFFF00"}},
                "mismatches": [],
            },
            "steps": [],
        }

        result = engine.chat(
            "project_demo",
            "change the current layer to yellow",
            context={"workflow_mode": "qgis_only", "requires_export": False, "export_path": "", "request_id": "req_demo"},
        )

        self.assertEqual(result["request_id"], "req_demo")
        self.assertEqual(result["verification"]["status"], "verified")

    def test_desktop_bridge_payload_forces_new_session(self):
        bridge = OpenClawBridge(self.build_config())
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"status": "success", "summary": "ok", "workflow_type": "qgis_only"}).encode("utf-8")

        def fake_urlopen(request, timeout=0):
            captured["timeout"] = timeout
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("geobot_runtime.openclaw_engine.urllib.request.urlopen", side_effect=fake_urlopen):
            bridge._chat_via_desktop_bridge(
                project_id="project_demo",
                message="将图层改为黄色",
                export_path="",
                request_id="req_demo",
                requires_export=False,
                workflow_mode="qgis_only",
                lesson_plan_path="",
                pptx_path="",
                requires_map=True,
                suggested_template="",
                fallback_template="",
            )

        self.assertEqual(captured["url"], "http://bridge.test/openclaw/chat")
        self.assertTrue(captured["payload"]["forceNewSession"])
        self.assertIn("requestId", captured["payload"])
        self.assertEqual(captured["payload"]["requestId"], "req_demo")
        self.assertEqual(captured["payload"]["workflowMode"], "qgis_only")
        self.assertFalse(captured["payload"]["requiresExport"])
        self.assertEqual(captured["payload"]["exportPath"], "")


if __name__ == "__main__":
    unittest.main()
