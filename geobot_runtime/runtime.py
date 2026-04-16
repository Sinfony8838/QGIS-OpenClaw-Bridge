from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import RuntimeConfig
from .gisclaw_engine import GISclawEngine
from .lesson_ppt_local import (
    build_ppt_scenario,
    generate_pptx_from_scenario,
    render_document_package,
    render_lesson_markdown,
    resolve_presentation_style,
    summarize_package_contract,
    validate_lesson_blueprint,
    write_docx_from_markdown,
    write_ppt_scenario_file,
)
from .models import WORKFLOW_STAGE_KEYS, build_workflow_stages
from .openclaw_engine import OpenClawEngine
from .population_unit import PopulationShowcase
from .qgis_bridge import QgisBridgeClient
from .style_intent import (
    extract_opacity_value,
    extract_requested_color,
    extract_width_value,
    find_named_layer_match,
    find_named_match,
    is_direct_style_request,
    mentions_current_layer,
    mentions_outline,
    wants_activate_layer,
    wants_hide_labels,
    wants_hide_layer,
    wants_label_change,
    wants_move_layer_bottom,
    wants_move_layer_top,
    wants_show_labels,
    wants_show_layer,
    wants_zoom_to_layer,
)
from .store import RuntimeStore
from .templates import TEMPLATE_SPECS, TemplateExecutor


COMMON_VALUE_FIELDS = ["population", "pop", "value", "count", "density", "score"]
CAPACITY_VALUE_FIELDS = ["capacity", "carrying_capacity", "reasonable_capacity", "pressure", "score", "population"]
COMMON_LABEL_FIELDS = ["name", "province", "city", "label", "region"]

QUERY_KEYWORDS = ["检查", "查看", "查询", "当前图层", "图层情况", "layers", "layer"]
TEACHING_KEYWORDS = ["教学", "教案", "课程", "课堂", "ppt", "课件", "lesson", "slides", "unit", "答辩", "汇报"]
MAP_HINT_KEYWORDS = ["地图", "制图", "qgis", "热力图", "密度图", "迁移图", "胡焕庸", "分级设色"]
DIRECT_QGIS_KEYWORDS = [
    "图层",
    "样式",
    "颜色",
    "标注",
    "标签",
    "显示",
    "隐藏",
    "透明度",
    "轮廓",
    "填充",
    "线宽",
    "符号",
    "style",
    "label",
    "color",
    "yellow",
    "layer color",
]
POPULATION_KEYWORDS = ["人口", "population", "hu line", "migration", "capacity", "distribution", "density"]
SHOWCASE_KEYWORDS = ["单元", "unit", "答辩", "汇报", "展示", "showcase", "flagship"]
TASK_MODE_LESSON_PPT = "lesson_ppt"
TASK_MODE_QGIS_ONLY = "qgis_only"
LEGACY_LESSON_TASK_MODES = {"teacher_flow", "full_flow", TASK_MODE_LESSON_PPT}
LEGACY_QGIS_TASK_MODES = {"qgis_bridge", TASK_MODE_QGIS_ONLY}


class GeoBotRuntime:
    def __init__(self, config: Optional[RuntimeConfig] = None):
        self.config = config or RuntimeConfig()
        self.config.ensure_dirs()
        self.store = RuntimeStore(self.config.state_file)
        self.qgis = QgisBridgeClient(self.config.qgis_host, self.config.qgis_port)
        self.template_executor = TemplateExecutor(self.config, self.qgis)
        self.population_showcase = PopulationShowcase(self.config)
        self.assistant_engine = self._build_assistant_engine()

    def _build_assistant_engine(self):
        if self.config.assistant_engine == "gisclaw":
            return GISclawEngine(self.config)
        return OpenClawEngine(self.config)

    def health(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "runtime": {
                "api": self.config.runtime_url,
                "outputs": str(self.config.outputs_dir),
                "workspace": str(self.config.workspace_dir),
            },
            "qgis": self.qgis.health(),
            "assistant_engine": self.assistant_engine.health(),
            "qgis_installation": {
                "detected": bool(self.config.qgis_executable),
                "executable": self.config.qgis_executable,
            },
            "population_showcase": self.population_showcase.health_payload(),
        }

    def create_project(self, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self.store.create_project(name=name, metadata=metadata)
        return {"status": "success", **project.to_dict()}

    def get_project(self, project_id: str) -> Dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project:
            raise KeyError(f"Unknown project: {project_id}")
        return {"status": "success", **project.to_dict()}

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job: {job_id}")
        return job.to_dict()

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        return {"status": "success", **artifact.to_dict()}

    def list_outputs(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return {"status": "success", "items": self.store.list_outputs(project_id=project_id)}

    def list_templates(self) -> Dict[str, Any]:
        return self.template_executor.list_templates()

    def get_population_showcase(self) -> Dict[str, Any]:
        return self.population_showcase.describe()

    def focus_qgis(self) -> Dict[str, Any]:
        payload = self.qgis.focus_window()
        return {"status": "success" if payload.get("ok") else "error", **payload}

    def submit_template(self, project_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if template_id not in TEMPLATE_SPECS:
            raise ValueError(f"Unknown template: {template_id}")
        stages = self._default_stages("map_template", requires_map=True)
        job = self.store.create_job(
            project_id=project_id,
            job_type="template",
            title=TEMPLATE_SPECS[template_id]["title"],
            workflow_type="map_template",
            request={"template_id": template_id, "payload": payload},
            stages=stages,
        )
        threading.Thread(
            target=self._run_template_job,
            args=(job.job_id, project_id, template_id, payload),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def submit_chat(
        self,
        project_id: str,
        message: str,
        task_mode: str = "",
        presentation_style: str = "",
    ) -> Dict[str, Any]:
        normalized_task_mode = self._normalize_task_mode(task_mode)
        route = self._classify_chat_request(
            message,
            task_mode=normalized_task_mode,
            presentation_style=presentation_style,
        )
        if route.get("showcase_mode") == self.config.population_showcase_mode:
            title = "Population Unit Lesson + PPT" if route["workflow_type"] == TASK_MODE_LESSON_PPT else "Population Unit QGIS Task"
        else:
            title = "GeoBot lesson and PPT task" if route["workflow_type"] == TASK_MODE_LESSON_PPT else "GeoBot QGIS task"
        job = self.store.create_job(
            project_id=project_id,
            job_type="chat",
            title=title,
            workflow_type=route["workflow_type"],
            request={
                "message": message,
                "route": route,
                "task_mode": route.get("task_mode", ""),
                "presentation_style": route.get("presentation_style", ""),
            },
            stages=self._default_stages(
                route["workflow_type"],
                requires_map=route["requires_map"],
                route_name=route.get("route", ""),
            ),
        )
        threading.Thread(
            target=self._run_chat_job,
            args=(job.job_id, project_id, message, route),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def _run_template_job(self, job_id: str, project_id: str, template_id: str, payload: Dict[str, Any]) -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "Queued template", "Preparing direct map template execution.", "running")
            self._update_stage(job_id, "analysis", "success", "Template request received.")
            self._update_stage(job_id, "map", "running", "Running map template.")
            result = self.template_executor.execute(project_id, template_id, payload)
            artifacts = result.get("artifact_bundle") or {
                "map_export": {
                    "artifact_type": "map_export",
                    "title": result["title"],
                    "path": result["export_path"],
                }
            }
            artifacts = self._register_result_artifacts(project_id, job_id, artifacts, self.assistant_engine.name)
            self._update_stage(job_id, "map", "success", "Map export completed.", result["export_path"])
            self.store.append_job_step(job_id, "Export complete", f"Saved output to {result['export_path']}", "success")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "map_template",
                    "summary": result["title"],
                    "assistant_message": result["title"],
                    "template_id": template_id,
                    "notes": result["response"].get("message", ""),
                    "export_path": result["export_path"],
                    "stages": self.store.get_job(job_id).stages,
                    "artifacts": artifacts,
                },
            )
        except Exception as exc:
            self._fail_job(job_id, "map_template", str(exc))

    def _run_chat_job(self, job_id: str, project_id: str, message: str, route: Dict[str, Any]) -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "Job created", "Analyzing the request.", "queued")
            if route["workflow_type"] == TASK_MODE_QGIS_ONLY:
                result = self._run_qgis_only_request(job_id, project_id, message, route)
            elif route["workflow_type"] == TASK_MODE_LESSON_PPT:
                result = self._run_lesson_ppt_request(job_id, project_id, message, route)
            elif route["workflow_type"] == "qgis_query":
                result = self._run_query_request(job_id, project_id, message)
            elif route["workflow_type"] == "map_template":
                result = self._run_map_template_request(job_id, project_id, message, route)
            else:
                raise RuntimeError(f"Unsupported workflow_type: {route['workflow_type']}")
            if result.get("status") == "error":
                raise RuntimeError(result.get("notes") or result.get("summary") or "Workflow execution failed")
            self._complete_chat_job(job_id, project_id, result)
        except Exception as exc:
            self._fail_job(job_id, route["workflow_type"], str(exc), task_mode=route.get("task_mode", ""))

    def _run_qgis_only_request(
        self,
        job_id: str,
        project_id: str,
        message: str,
        route: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._build_qgis_only_context(project_id=project_id, job_id=job_id, route=route, message=message)
        self._update_stage(job_id, "analysis", "running", "正在解析 QGIS 执行请求。")
        self._update_stage(job_id, "design", "skipped", "当前为 qgis_only 模式，不生成教学设计。")
        self._update_stage(job_id, "map", "queued", "等待在当前 QGIS 项目中执行操作。")
        self._update_stage(job_id, "presentation", "skipped", "当前为 qgis_only 模式，不生成 PPT。")
        self.store.append_job_step(job_id, "准备执行请求", "正在选择直接执行或隐藏 QGIS 执行引擎。", "running")

        direct_result = self._run_direct_qgis_request(message=message, route=route)
        if direct_result is not None:
            for step in direct_result.get("steps", []):
                self.store.append_job_step(
                    job_id,
                    step.get("title", "QGIS step"),
                    step.get("detail", ""),
                    step.get("status", "info"),
                )
            self.store.get_job(job_id).stages = self._merge_stage_payloads(
                self.store.get_job(job_id).stages,
                direct_result.get("stages", {}),
            )
            return {
                "status": direct_result.get("status", "success"),
                "request_id": context.get("request_id", ""),
                "summary": direct_result.get("summary", "已完成请求的 QGIS 任务。"),
                "assistant_message": direct_result.get("assistant_message", ""),
                "template_id": "",
                "notes": direct_result.get("notes", ""),
                "export_path": "",
                "stages": self.store.get_job(job_id).stages,
                "artifacts": dict(direct_result.get("artifacts", {})),
                "verification": direct_result.get("verification", {}),
                "engine": direct_result.get("engine", "qgis-bridge-direct"),
                "workflow_type": TASK_MODE_QGIS_ONLY,
                "task_mode": TASK_MODE_QGIS_ONLY,
                "showcase_mode": route.get("showcase_mode", ""),
            }

        assistant_result = self.assistant_engine.chat(project_id, message, context=context)
        for step in assistant_result.get("steps", []):
            self.store.append_job_step(
                job_id,
                step.get("title", "Assistant step"),
                step.get("detail", ""),
                step.get("status", "info"),
            )
        self.store.get_job(job_id).stages = self._merge_stage_payloads(
            self.store.get_job(job_id).stages,
            assistant_result.get("stages", {}),
        )
        artifacts = dict(assistant_result.get("artifacts", {}))
        if context.get("requires_export") and context.get("expected_artifacts"):
            artifacts = self._merge_expected_artifacts(artifacts, context.get("expected_artifacts", {}))
        return {
            "status": assistant_result.get("status", "success"),
            "request_id": assistant_result.get("request_id", context.get("request_id", "")),
            "summary": assistant_result.get("summary", "已完成请求的 QGIS 任务。"),
            "assistant_message": assistant_result.get("assistant_message", ""),
            "template_id": assistant_result.get("template_id", ""),
            "notes": assistant_result.get("notes", ""),
            "export_path": assistant_result.get("export_path", "") or context.get("export_path", ""),
            "stages": self.store.get_job(job_id).stages,
            "artifacts": artifacts,
            "verification": assistant_result.get("verification", {}),
            "engine": assistant_result.get("engine", self.assistant_engine.name),
            "workflow_type": TASK_MODE_QGIS_ONLY,
            "task_mode": TASK_MODE_QGIS_ONLY,
            "showcase_mode": route.get("showcase_mode", ""),
        }

    def _run_direct_qgis_request(self, message: str, route: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if bool(route.get("requires_export")):
            return None

        try:
            layers_response = self.qgis.call("get_layers")
        except Exception:
            return None

        if layers_response.get("status") != "success":
            return None

        layers = layers_response.get("data", []) or []
        for handler in (
            self._run_direct_label_request,
            self._run_direct_visibility_request,
            self._run_direct_selection_zoom_request,
            self._run_direct_layer_order_request,
            self._run_direct_style_request,
        ):
            result = handler(message, route, layers)
            if result is not None:
                return result
        return None

    def _run_direct_label_request(self, message: str, route: Dict[str, Any], layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        explicit_field = self._extract_named_payload(message, ["field", "label_field"])
        if not (wants_show_labels(message) or wants_hide_labels(message) or (wants_label_change(message) and explicit_field)):
            return None

        target_layer = self._resolve_direct_layer_target(message, layers)
        if not target_layer:
            return self._build_direct_result(
                status="error",
                summary="未能确定要修改标注的图层。",
                assistant_message="未能确定要修改标注的图层。",
                notes="Direct label request matched, but the target layer was ambiguous.",
                verification_status="failed",
                checked_layers=[],
                expected_style={"labels_enabled": wants_show_labels(message)},
                observed_style={},
                mismatches=["ambiguous_target_layer"],
                steps=[{"title": "检查图层", "detail": "无法确定唯一目标图层。", "status": "error"}],
                map_summary="标注直连请求未执行。",
            )

        if wants_hide_labels(message):
            response = self.qgis.call("set_layer_labels", layer_id=target_layer.get("id"), enabled=False)
            return self._finalize_direct_layer_state_change(
                target_layer=target_layer,
                action_response=response,
                verification_key="labels_enabled",
                expected_value=False,
                success_summary="已关闭图层标注。",
                success_message=f"已关闭图层 {target_layer.get('name', '')} 的标注。",
                success_note="Direct label disable executed through the QGIS bridge.",
                action_title="关闭标注",
                action_detail="通过 set_layer_labels(enabled=False) 关闭标注。",
            )

        label_field = explicit_field or self._pick_direct_label_field(message, target_layer)
        if not label_field:
            return self._build_direct_result(
                status="error",
                summary="未能确定用于标注的字段。",
                assistant_message="未能确定用于标注的字段。",
                notes="Direct label enable request matched, but no label field could be resolved.",
                verification_status="failed",
                checked_layers=[target_layer.get("name", "")],
                expected_style={"labels_enabled": True},
                observed_style={},
                mismatches=["missing_label_field"],
                steps=[{"title": "检查字段", "detail": f"图层 {target_layer.get('name', '')} 没有可用的标注字段。", "status": "error"}],
                map_summary="标注直连请求未执行。",
            )

        response = self.qgis.call("set_layer_labels", layer_id=target_layer.get("id"), enabled=True, field=label_field)
        return self._finalize_direct_layer_state_change(
            target_layer=target_layer,
            action_response=response,
            verification_key="labels_enabled",
            expected_value=True,
            success_summary="已开启图层标注。",
            success_message=f"已为图层 {target_layer.get('name', '')} 开启标注，字段为 {label_field}。",
            success_note="Direct label enable executed through the QGIS bridge.",
            action_title="设置标注",
            action_detail=f"通过 set_layer_labels(field={label_field}) 开启标注。",
        )

    def _run_direct_visibility_request(self, message: str, route: Dict[str, Any], layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        visible = None
        if wants_show_layer(message):
            visible = True
        elif wants_hide_layer(message):
            visible = False
        if visible is None:
            return None

        target_layer = self._resolve_direct_layer_target(message, layers)
        if not target_layer:
            return self._build_direct_result(
                status="error",
                summary="未能确定要显示或隐藏的图层。",
                assistant_message="未能确定要显示或隐藏的图层。",
                notes="Direct visibility request matched, but the target layer was ambiguous.",
                verification_status="failed",
                checked_layers=[],
                expected_style={"visible": visible},
                observed_style={},
                mismatches=["ambiguous_target_layer"],
                steps=[{"title": "检查图层", "detail": "无法确定唯一目标图层。", "status": "error"}],
                map_summary="图层显隐直连请求未执行。",
            )

        response = self.qgis.call("set_layer_visibility", layer_id=target_layer.get("id"), visible=visible)
        return self._finalize_direct_layer_state_change(
            target_layer=target_layer,
            action_response=response,
            verification_key="is_visible",
            expected_value=visible,
            success_summary="已更新图层显隐状态。",
            success_message=f"已将图层 {target_layer.get('name', '')} {'显示' if visible else '隐藏'}。",
            success_note="Direct visibility update executed through the QGIS bridge.",
            action_title="设置显隐",
            action_detail=f"通过 set_layer_visibility(visible={visible}) 更新图层显隐。",
        )

    def _run_direct_selection_zoom_request(self, message: str, route: Dict[str, Any], layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        should_activate = wants_activate_layer(message)
        should_zoom = wants_zoom_to_layer(message)
        if not (should_activate or should_zoom):
            return None

        target_layer = self._resolve_direct_layer_target(message, layers)
        if not target_layer:
            return self._build_direct_result(
                status="error",
                summary="未能确定要选中或缩放的图层。",
                assistant_message="未能确定要选中或缩放的图层。",
                notes="Direct selection or zoom request matched, but the target layer was ambiguous.",
                verification_status="failed",
                checked_layers=[],
                expected_style={"is_active": should_activate, "zoom_to_layer": should_zoom},
                observed_style={},
                mismatches=["ambiguous_target_layer"],
                steps=[{"title": "检查图层", "detail": "无法确定唯一目标图层。", "status": "error"}],
                map_summary="图层选中或缩放直连请求未执行。",
            )

        steps = [{"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"}]
        artifacts = {}

        if should_activate:
            activate_response = self.qgis.call("set_active_layer", layer_id=target_layer.get("id"))
            artifacts.update(activate_response.get("artifacts", {}) or {})
            if activate_response.get("status") != "success":
                return self._build_direct_result(
                    status="error",
                    summary="激活图层失败。",
                    assistant_message="激活图层失败。",
                    notes=activate_response.get("message", ""),
                    verification_status="failed",
                    checked_layers=[target_layer.get("name", "")],
                    expected_style={"is_active": True},
                    observed_style={},
                    mismatches=[activate_response.get("message", "set_active_layer failed")],
                    steps=steps + [{"title": "激活图层", "detail": activate_response.get("message", ""), "status": "error"}],
                    map_summary="图层选中直连请求执行失败。",
                    artifacts=artifacts,
                )
            steps.append({"title": "激活图层", "detail": "通过 set_active_layer() 激活图层。", "status": "success"})

        if should_zoom:
            zoom_response = self.qgis.call("zoom_to_layer", layer_id=target_layer.get("id"))
            artifacts.update(zoom_response.get("artifacts", {}) or {})
            if zoom_response.get("status") != "success":
                return self._build_direct_result(
                    status="error",
                    summary="缩放到图层失败。",
                    assistant_message="缩放到图层失败。",
                    notes=zoom_response.get("message", ""),
                    verification_status="failed",
                    checked_layers=[target_layer.get("name", "")],
                    expected_style={"zoom_to_layer": True},
                    observed_style={},
                    mismatches=[zoom_response.get("message", "zoom_to_layer failed")],
                    steps=steps + [{"title": "缩放到图层", "detail": zoom_response.get("message", ""), "status": "error"}],
                    map_summary="图层缩放直连请求执行失败。",
                    artifacts=artifacts,
                )
            steps.append({"title": "缩放到图层", "detail": "通过 zoom_to_layer() 聚焦到目标图层。", "status": "success"})

        latest_state = self._get_layer_snapshot(target_layer.get("id"))
        mismatches = []
        if should_activate and not latest_state.get("is_active"):
            mismatches.append("active_layer_not_updated")

        return self._build_direct_result(
            status="success" if not mismatches else "error",
            summary="已完成图层选中与缩放。" if not mismatches else "图层选中或缩放验证失败。",
            assistant_message=(
                f"已将图层 {target_layer.get('name', '')} 设为当前图层并缩放到其范围。"
                if should_activate and should_zoom
                else f"已将图层 {target_layer.get('name', '')} 设为当前图层。"
                if should_activate
                else f"已缩放到图层 {target_layer.get('name', '')}。"
            ),
            notes="Direct layer selection and zoom executed through the QGIS bridge.",
            verification_status="verified" if not mismatches else "mismatch",
            checked_layers=[target_layer.get("name", "")],
            expected_style={"is_active": bool(should_activate), "zoom_to_layer": bool(should_zoom)},
            observed_style={target_layer.get("name", ""): {"is_active": bool(latest_state.get("is_active")), "zoom_to_layer": bool(should_zoom)}},
            mismatches=mismatches,
            steps=steps,
            map_summary="已通过底层 QGIS 工具完成图层选中或缩放。",
            artifacts=artifacts,
        )

    def _run_direct_layer_order_request(self, message: str, route: Dict[str, Any], layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        position = None
        if wants_move_layer_top(message):
            position = "top"
        elif wants_move_layer_bottom(message):
            position = "bottom"
        if not position:
            return None

        target_layer = self._resolve_direct_layer_target(message, layers)
        if not target_layer:
            return self._build_direct_result(
                status="error",
                summary="未能确定要调整顺序的图层。",
                assistant_message="未能确定要调整顺序的图层。",
                notes="Direct order request matched, but the target layer was ambiguous.",
                verification_status="failed",
                checked_layers=[],
                expected_style={"position": position},
                observed_style={},
                mismatches=["ambiguous_target_layer"],
                steps=[{"title": "检查图层", "detail": "无法确定唯一目标图层。", "status": "error"}],
                map_summary="图层顺序直连请求未执行。",
            )

        response = self.qgis.call("move_layer", layer_id=target_layer.get("id"), position=position)
        if response.get("status") != "success":
            return self._build_direct_result(
                status="error",
                summary="调整图层顺序失败。",
                assistant_message="调整图层顺序失败。",
                notes=response.get("message", ""),
                verification_status="failed",
                checked_layers=[target_layer.get("name", "")],
                expected_style={"position": position},
                observed_style={},
                mismatches=[response.get("message", "move_layer failed")],
                steps=[
                    {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                    {"title": "调整顺序", "detail": response.get("message", ""), "status": "error"},
                ],
                map_summary="图层顺序直连请求执行失败。",
                artifacts=response.get("artifacts", {}),
            )

        refreshed_layers = self._get_layers_snapshot()
        latest_state = self._find_layer_in_snapshot(target_layer.get("id"), refreshed_layers)
        order_values = [int(layer.get("order_index", -1)) for layer in refreshed_layers if int(layer.get("order_index", -1)) >= 0]
        min_order = min(order_values) if order_values else 0
        max_order = max(order_values) if order_values else 0
        latest_order = int(latest_state.get("order_index", -1)) if latest_state else -1
        verified = latest_order == min_order if position == "top" else latest_order == max_order
        return self._build_direct_result(
            status="success" if verified else "error",
            summary="已调整图层顺序。" if verified else "图层顺序验证失败。",
            assistant_message=f"已将图层 {target_layer.get('name', '')} {'置顶' if position == 'top' else '置底'}。",
            notes="Direct layer order update executed through the QGIS bridge.",
            verification_status="verified" if verified else "mismatch",
            checked_layers=[target_layer.get("name", "")],
            expected_style={"position": position},
            observed_style={target_layer.get("name", ""): {"order_index": latest_order}},
            mismatches=[] if verified else [f"expected {position} but observed order_index={latest_order}"],
            steps=[
                {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                {"title": "调整顺序", "detail": f"通过 move_layer(position={position}) 调整顺序。", "status": "success"},
            ],
            map_summary="已通过底层 QGIS 工具调整图层顺序。",
            artifacts=response.get("artifacts", {}),
        )

    def _run_direct_style_request(self, message: str, route: Dict[str, Any], layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not is_direct_style_request(
            message,
            suggested_template=route.get("suggested_template", "") or "",
            requires_export=bool(route.get("requires_export")),
        ):
            return None

        target_layer = self._resolve_direct_layer_target(message, layers)
        if not target_layer:
            return self._build_direct_result(
                status="error",
                summary="未能确定要修改样式的图层。",
                assistant_message="未能确定要修改样式的图层。",
                notes="Direct style request matched, but the target layer was ambiguous.",
                verification_status="failed",
                checked_layers=[],
                expected_style={},
                observed_style={},
                mismatches=["ambiguous_target_layer"],
                steps=[{"title": "检查图层", "detail": "无法确定唯一目标图层。", "status": "error"}],
                map_summary="图层样式直连请求未执行。",
            )

        geometry_type = str(target_layer.get("geometry_type", "")).lower()
        requested_color = extract_requested_color(message)
        requested_opacity = extract_opacity_value(message)
        requested_width = extract_width_value(message)
        style_properties: Dict[str, Any] = {}
        expected_style: Dict[str, Any] = {}

        if requested_color:
            if geometry_type == "line":
                style_properties["line_color"] = requested_color
                expected_style["line_color"] = requested_color
            elif mentions_outline(message):
                style_properties["outline_color"] = requested_color
                expected_style["outline_color"] = requested_color
            else:
                style_properties["fill_color"] = requested_color
                expected_style["fill_color"] = requested_color
        if requested_width is not None:
            if geometry_type == "line":
                style_properties["line_width"] = requested_width
            else:
                style_properties["outline_width"] = requested_width
            expected_style["line_width"] = requested_width
        if requested_opacity is not None:
            style_properties["opacity"] = requested_opacity
            expected_style["opacity"] = requested_opacity
        if not style_properties:
            return None

        style_response = self.qgis.call("set_layer_style", layer_id=target_layer.get("id"), **style_properties)
        if style_response.get("status") != "success":
            return self._build_direct_result(
                status="error",
                summary="图层样式修改失败。",
                assistant_message="图层样式修改失败。",
                notes=style_response.get("message", ""),
                verification_status="failed",
                checked_layers=[target_layer.get("name", "")],
                expected_style=expected_style,
                observed_style={},
                mismatches=[style_response.get("message", "set_layer_style failed")],
                steps=[
                    {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                    {"title": "设置样式", "detail": style_response.get("message", ""), "status": "error"},
                ],
                map_summary="图层样式直连请求执行失败。",
                artifacts=style_response.get("artifacts", {}),
            )

        observed_response = self.qgis.call("get_layer_style", layer_id=target_layer.get("id"))
        observed_style = observed_response.get("data", {}) if observed_response.get("status") == "success" else {}
        mismatches = self._compare_expected_style(expected_style, observed_style)
        verification_status = "verified" if not mismatches else "mismatch"
        artifacts = dict(style_response.get("artifacts", {}) or {})
        for key, value in (observed_response.get("artifacts", {}) or {}).items():
            artifacts.setdefault(key, value)
        return self._build_direct_result(
            status="success" if verification_status == "verified" else "error",
            summary="已更新图层样式。" if verification_status == "verified" else "图层样式验证失败。",
            assistant_message=f"已更新图层 {target_layer.get('name', '')} 的单符号样式。",
            notes="Direct single-symbol style update executed through the QGIS bridge.",
            verification_status=verification_status,
            checked_layers=[target_layer.get("name", "")],
            expected_style=expected_style,
            observed_style={target_layer.get("name", ""): observed_style},
            mismatches=mismatches,
            steps=[
                {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                {"title": "设置样式", "detail": f"通过 set_layer_style() 更新 {', '.join(expected_style.keys())}。", "status": "success"},
                {"title": "回读验证", "detail": "通过 get_layer_style() 完成样式回读验证。", "status": "success" if verification_status == "verified" else "error"},
            ],
            map_summary="已通过底层 QGIS 工具完成单图层样式调整。",
            artifacts=artifacts,
        )

    def _resolve_direct_layer_target(self, message: str, layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        layer_name = find_named_layer_match(message, [layer.get("name", "") for layer in layers])
        if layer_name:
            for layer in layers:
                if layer.get("name") == layer_name:
                    return layer

        active_layers = [layer for layer in layers if layer.get("is_active")]
        if mentions_current_layer(message):
            return active_layers[0] if len(active_layers) == 1 else None

        if len(active_layers) == 1:
            return active_layers[0]
        return None

    def _pick_direct_label_field(self, message: str, target_layer: Dict[str, Any]) -> str:
        fields = [str(field) for field in target_layer.get("fields", []) if field]
        explicit_field = self._extract_named_payload(message, ["field", "label_field"])
        if explicit_field:
            matched = find_named_match(explicit_field, fields)
            if matched:
                return matched
        mentioned_field = find_named_match(message, fields)
        if mentioned_field:
            return mentioned_field
        best_field = self._pick_best_field([target_layer], target_layer.get("name", ""), COMMON_LABEL_FIELDS)
        if best_field:
            return best_field
        return fields[0] if fields else ""

    def _get_layers_snapshot(self) -> List[Dict[str, Any]]:
        response = self.qgis.call("get_layers")
        if response.get("status") != "success":
            return []
        return response.get("data", []) or []

    def _find_layer_in_snapshot(self, layer_id: str, layers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for layer in layers:
            if layer.get("id") == layer_id:
                return layer
        return None

    def _get_layer_snapshot(self, layer_id: str) -> Dict[str, Any]:
        return self._find_layer_in_snapshot(layer_id, self._get_layers_snapshot()) or {}

    def _compare_expected_style(self, expected_style: Dict[str, Any], observed_style: Dict[str, Any]) -> List[str]:
        mismatches = []
        for key, expected_value in expected_style.items():
            observed_value = observed_style.get(key)
            if key in {"fill_color", "outline_color", "line_color"}:
                if str(observed_value or "").upper() != str(expected_value or "").upper():
                    mismatches.append(f"expected {key}={expected_value} but observed {observed_value}")
            elif key in {"line_width", "opacity"}:
                try:
                    if abs(float(observed_value) - float(expected_value)) > 1e-6:
                        mismatches.append(f"expected {key}={expected_value} but observed {observed_value}")
                except Exception:
                    mismatches.append(f"expected {key}={expected_value} but observed {observed_value}")
            elif observed_value != expected_value:
                mismatches.append(f"expected {key}={expected_value} but observed {observed_value}")
        return mismatches

    def _finalize_direct_layer_state_change(
        self,
        target_layer: Dict[str, Any],
        action_response: Dict[str, Any],
        verification_key: str,
        expected_value: Any,
        success_summary: str,
        success_message: str,
        success_note: str,
        action_title: str,
        action_detail: str,
    ) -> Dict[str, Any]:
        if action_response.get("status") != "success":
            return self._build_direct_result(
                status="error",
                summary=f"{action_title}失败。",
                assistant_message=f"{action_title}失败。",
                notes=action_response.get("message", ""),
                verification_status="failed",
                checked_layers=[target_layer.get("name", "")],
                expected_style={verification_key: expected_value},
                observed_style={},
                mismatches=[action_response.get("message", f"{action_title} failed")],
                steps=[
                    {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                    {"title": action_title, "detail": action_response.get("message", ""), "status": "error"},
                ],
                map_summary=f"{action_title}直连请求执行失败。",
                artifacts=action_response.get("artifacts", {}),
            )

        latest_state = self._get_layer_snapshot(target_layer.get("id"))
        observed_value = latest_state.get(verification_key)
        verified = observed_value == expected_value
        return self._build_direct_result(
            status="success" if verified else "error",
            summary=success_summary if verified else f"{action_title}验证失败。",
            assistant_message=success_message,
            notes=success_note,
            verification_status="verified" if verified else "mismatch",
            checked_layers=[target_layer.get("name", "")],
            expected_style={verification_key: expected_value},
            observed_style={target_layer.get("name", ""): {verification_key: observed_value}},
            mismatches=[] if verified else [f"expected {verification_key}={expected_value} but observed {observed_value}"],
            steps=[
                {"title": "检查图层", "detail": f"目标图层：{target_layer.get('name', '')}", "status": "success"},
                {"title": action_title, "detail": action_detail, "status": "success"},
            ],
            map_summary=f"已通过底层 QGIS 工具完成{action_title}。",
            artifacts=action_response.get("artifacts", {}),
        )

    def _build_direct_result(
        self,
        status: str,
        summary: str,
        assistant_message: str,
        notes: str,
        verification_status: str,
        checked_layers: List[str],
        expected_style: Dict[str, Any],
        observed_style: Dict[str, Any],
        mismatches: List[str],
        steps: List[Dict[str, Any]],
        map_summary: str,
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "summary": summary,
            "assistant_message": assistant_message,
            "notes": notes,
            "stages": self._direct_stages(status="success" if status == "success" else "error", summary=map_summary),
            "artifacts": artifacts or {},
            "verification": {
                "status": verification_status,
                "checked_layers": checked_layers,
                "expected_style": expected_style,
                "observed_style": observed_style,
                "mismatches": mismatches,
            },
            "steps": steps,
            "engine": "qgis-bridge-direct",
        }

    def _direct_stages(self, status: str, summary: str) -> Dict[str, Dict[str, str]]:
        return {
            "analysis": {"status": "success", "summary": "已识别为高频直接 QGIS 操作请求。", "detail": ""},
            "design": {"status": "skipped", "summary": "当前为 qgis_only 模式，不生成教学设计。", "detail": ""},
            "map": {"status": status, "summary": summary, "detail": ""},
            "presentation": {"status": "skipped", "summary": "当前为 qgis_only 模式，不生成 PPT。", "detail": ""},
        }

    def _run_query_request(self, job_id: str, project_id: str, message: str) -> Dict[str, Any]:
        self._update_stage(job_id, "analysis", "running", "正在解析 QGIS 查询请求。")
        self.store.append_job_step(job_id, "调用 QGIS", "正在检查当前 QGIS 项目。", "running")
        response = self.qgis.call("get_layers")
        layers = response.get("data", [])
        self._update_stage(job_id, "analysis", "success", "已完成查询请求解析。")
        self._update_stage(job_id, "map", "success", "已获取当前 QGIS 图层信息。")
        return {
            "status": "success",
            "workflow_type": "qgis_query",
            "summary": "已完成当前 QGIS 图层检查。",
            "assistant_message": "已完成当前 QGIS 图层检查。",
            "template_id": "",
            "notes": self._format_layers_notes(layers),
            "export_path": "",
            "stages": self.store.get_job(job_id).stages,
            "artifacts": {},
        }

    def _run_map_template_request(
        self,
        job_id: str,
        project_id: str,
        message: str,
        route: Dict[str, Any],
    ) -> Dict[str, Any]:
        template_id = route["suggested_template"]
        payload = self._build_fallback_payload(project_id, template_id, message)
        self._update_stage(job_id, "analysis", "success", "Matched a direct map template.")
        self._update_stage(job_id, "map", "running", "Executing the QGIS map template.")
        self.store.append_job_step(job_id, "Calling QGIS", "Running local template execution.", "running")
        result = self.template_executor.execute(project_id, template_id, payload)
        self._update_stage(job_id, "map", "success", "Map export completed.", result["export_path"])
        artifacts = result.get("artifact_bundle") or {
            "map_export": {
                "artifact_type": "map_export",
                "title": result["title"],
                "path": result["export_path"],
            }
        }
        return {
            "status": "success",
            "workflow_type": TASK_MODE_QGIS_ONLY if route.get("task_mode") == TASK_MODE_QGIS_ONLY else "map_template",
            "summary": result["title"],
            "assistant_message": f"已完成 {result['title']}。",
            "template_id": template_id,
            "notes": result["response"].get("message", ""),
            "export_path": result["export_path"],
            "stages": self.store.get_job(job_id).stages,
            "artifacts": artifacts,
            "showcase_mode": route.get("showcase_mode", ""),
        }

    def _run_lesson_ppt_request(
        self,
        job_id: str,
        project_id: str,
        message: str,
        route: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._build_lesson_ppt_context(project_id=project_id, job_id=job_id, route=route)
        self._update_stage(job_id, "analysis", "running", "Parsing the teaching request.")
        self._update_stage(job_id, "design", "queued", "Preparing lesson design.")
        self._update_stage(job_id, "map", "skipped", "QGIS execution is disabled in lesson_ppt mode.")
        self._update_stage(job_id, "presentation", "queued", "Waiting for local presentation rendering.")
        self.store.append_job_step(job_id, "Calling assistant engine", "Forwarding the request to the hidden assistant engine.", "running")

        try:
            assistant_result = self.assistant_engine.chat(project_id, message, context=context)
        except Exception as exc:
            recovered = self._recover_lesson_ppt_timeout_result(context, route, str(exc))
            if not recovered:
                raise
            self.store.append_job_step(
                job_id,
                "Recovered partial lesson output",
                recovered.get("summary", "Recovered generated lesson artifacts after OpenClaw timeout."),
                "warning",
            )
            assistant_result = recovered
        for step in assistant_result.get("steps", []):
            self.store.append_job_step(
                job_id,
                step.get("title", "Assistant step"),
                step.get("detail", ""),
                step.get("status", "info"),
            )
        if assistant_result.get("partial_output"):
            self.store.get_job(job_id).stages = self._merge_stage_payloads(
                self.store.get_job(job_id).stages,
                assistant_result.get("stages", {}),
            )
            self._ensure_qgis_guidance_block(context.get("lesson_plan_path", ""), route)
            return {
                "status": assistant_result.get("status", "success"),
                "workflow_type": TASK_MODE_LESSON_PPT,
                "summary": assistant_result.get("summary", "Lesson design completed with partial local recovery."),
                "assistant_message": assistant_result.get("assistant_message", ""),
                "template_id": assistant_result.get("template_id", ""),
                "notes": assistant_result.get("notes", ""),
                "export_path": "",
                "stages": self.store.get_job(job_id).stages,
                "artifacts": assistant_result.get("artifacts", {}),
                "engine": assistant_result.get("engine", self.assistant_engine.name),
                "showcase_mode": route.get("showcase_mode", ""),
                "task_mode": TASK_MODE_LESSON_PPT,
                "presentation_style": context.get("presentation_style", ""),
            }
        return self._finalize_local_lesson_ppt_result(
            job_id=job_id,
            route=route,
            context=context,
            assistant_result=assistant_result,
        )

    def _finalize_local_lesson_ppt_result(
        self,
        job_id: str,
        route: Dict[str, Any],
        context: Dict[str, Any],
        assistant_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw_result = assistant_result.get("raw") or assistant_result
        blueprint = validate_lesson_blueprint(raw_result)
        self._update_stage(job_id, "analysis", "success", "Parsed the teaching request.")
        self.store.append_job_step(
            job_id,
            "Validated lesson blueprint",
            "Structured teaching package and slide contract passed schema validation.",
            "success",
        )

        expected_artifacts = context.get("expected_artifacts", {})
        lesson_plan_path = Path(str(context.get("lesson_plan_path", "")))
        pptx_path = Path(str(context.get("pptx_path", "")))
        deck_scenario_path = Path(str(context.get("deck_scenario_path", ""))) if context.get("deck_scenario_path") else None
        presentation_style = str(context.get("presentation_style", "")).strip()
        markdown_targets = context.get("document_paths", {})
        docx_targets = context.get("document_docx_paths", {})
        package_contract = blueprint.get("package_contract", {})
        presentation_requirements = package_contract.get("presentation_requirements", {})

        self._update_stage(job_id, "design", "running", "Rendering teaching package locally.")
        document_package = render_document_package(blueprint)
        markdown_success = []
        docx_success = []
        docx_failures: List[str] = []

        for artifact_key, markdown_text in document_package.items():
            target_path_value = str(markdown_targets.get(artifact_key, "")).strip()
            if not target_path_value:
                continue
            target_path = Path(target_path_value)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(markdown_text, encoding="utf-8")
            if artifact_key == "lesson_plan":
                self._ensure_qgis_guidance_block(str(target_path), route)
            markdown_success.append(artifact_key)
            self.store.append_job_step(job_id, "Wrote {}".format(artifact_key), str(target_path), "success")

        for artifact_key, target_path_value in (docx_targets or {}).items():
            if artifact_key not in document_package:
                continue
            try:
                target_path = Path(str(target_path_value))
                write_docx_from_markdown(document_package[artifact_key], target_path)
                docx_success.append(artifact_key)
                self.store.append_job_step(job_id, "Wrote {} docx".format(artifact_key), str(target_path), "success")
            except Exception as exc:
                failure_text = "{}: {}".format(artifact_key, exc)
                docx_failures.append(failure_text)
                self.store.append_job_step(job_id, "Word export failed", failure_text, "warning")

        design_status = "warning" if docx_failures else "success"
        design_summary = "Generated {} markdown documents and {} Word documents.".format(
            len(markdown_success),
            len(docx_success),
        )
        design_detail = "" if not docx_failures else "; ".join(docx_failures)
        self._update_stage(job_id, "design", design_status, design_summary, design_detail)

        ppt_warning = ""
        deck_metadata_path = ""
        if not presentation_requirements.get("enabled", True):
            self._update_stage(job_id, "presentation", "skipped", "Presentation output is disabled by the package contract.")
        elif deck_scenario_path:
            self._update_stage(job_id, "presentation", "running", f"Generating local PPT deck with style `{presentation_style}`.")
            scenario_id = pptx_path.stem
            scenario = build_ppt_scenario(blueprint, presentation_style, scenario_id)
            write_ppt_scenario_file(scenario, deck_scenario_path)
            self.store.append_job_step(job_id, "Wrote deck scenario", str(deck_scenario_path), "success")
            try:
                generated = generate_pptx_from_scenario(
                    ppt_studio_dir=Path(self.config.ppt_studio_skill_dir),
                    scenario_path=deck_scenario_path,
                    scenario_id=scenario_id,
                    output_dir=pptx_path.parent,
                )
                deck_metadata_path = generated.get("deck_metadata_path", "")
                self.store.append_job_step(job_id, "Generated local PPT deck", generated.get("pptx_path", str(pptx_path)), "success")
                self._update_stage(job_id, "presentation", "success", "Generated the teaching slides locally.", generated.get("pptx_path", str(pptx_path)))
            except Exception as exc:
                ppt_warning = str(exc)
                self.store.append_job_step(job_id, "Local PPT generation failed", ppt_warning, "warning")
                self._update_stage(job_id, "presentation", "warning", "PPT generation failed.", ppt_warning)
        else:
            self._update_stage(job_id, "presentation", "running", f"Generating local PPT deck with style `{presentation_style}`.")
            ppt_warning = "Deck scenario path is not configured."
            self.store.append_job_step(job_id, "Local PPT generation failed", ppt_warning, "warning")
            self._update_stage(job_id, "presentation", "warning", "PPT generation failed.", ppt_warning)

        result_artifacts: Dict[str, Dict[str, Any]] = {}
        for artifact_key in markdown_success:
            descriptor = expected_artifacts.get(artifact_key)
            if descriptor:
                result_artifacts[artifact_key] = descriptor
        for artifact_key in docx_success:
            docx_key = "{}_docx".format(artifact_key) if artifact_key != "lesson_plan" else "lesson_plan_docx"
            descriptor = expected_artifacts.get(docx_key)
            if descriptor:
                result_artifacts[docx_key] = descriptor
        if presentation_requirements.get("enabled", True) and deck_scenario_path and deck_scenario_path.exists():
            descriptor = expected_artifacts.get("deck_scenario")
            if descriptor:
                result_artifacts["deck_scenario"] = descriptor
        if presentation_requirements.get("enabled", True) and pptx_path.exists():
            descriptor = expected_artifacts.get("pptx")
            if descriptor:
                result_artifacts["pptx"] = descriptor
        if deck_metadata_path:
            result_artifacts.setdefault(
                "deck_metadata",
                {
                    "artifact_type": "json",
                    "title": "Deck Metadata",
                    "path": deck_metadata_path,
                    "metadata": {"showcase_priority": 96},
                },
            )

        project_advantages = blueprint["lesson_payload"]["project_advantages"]
        contract_summary = summarize_package_contract(blueprint)
        if not presentation_requirements.get("enabled", True):
            summary = "Completed the lesson design workflow. The package contract does not require a PPT output."
            assistant_message = "已完成教学设计与教案输出；本次成果包合同未要求生成 PPT。"
        elif ppt_warning:
            summary = "Completed the lesson design workflow, but local PPT generation did not finish."
            assistant_message = "已完成教学设计与教案输出，但本地 PPT 生成未完成。"
        else:
            summary = "Completed the lesson design workflow and generated the local teaching deck."
            assistant_message = "已完成教学设计、本地教案输出和 PPT 生成。"
        notes_parts = [str(assistant_result.get("notes", "")).strip()]
        if docx_failures:
            notes_parts.append("DOCX export warnings: {}".format("; ".join(docx_failures)))
        if ppt_warning:
            notes_parts.append("PPT export warning: {}".format(ppt_warning))
        notes = "\n".join(part for part in notes_parts if part)
        if ppt_warning and not notes:
            notes = "PPT generation failed."

        return {
            "status": "success",
            "workflow_type": TASK_MODE_LESSON_PPT,
            "summary": summary,
            "assistant_message": assistant_message,
            "template_id": assistant_result.get("template_id", ""),
            "notes": notes,
            "export_path": "",
            "stages": self.store.get_job(job_id).stages,
            "artifacts": result_artifacts,
            "engine": assistant_result.get("engine", self.assistant_engine.name),
            "showcase_mode": route.get("showcase_mode", ""),
            "task_mode": TASK_MODE_LESSON_PPT,
            "presentation_style": presentation_style,
            "showcase_highlights": project_advantages.get("capabilities", []) + contract_summary[:2],
            "package_contract_summary": contract_summary,
            "package_contract": package_contract,
        }

    def _recover_lesson_ppt_timeout_result(
        self,
        context: Dict[str, Any],
        route: Dict[str, Any],
        error_message: str,
    ) -> Optional[Dict[str, Any]]:
        if "Timed out while waiting for OpenClaw to finish the task" not in (error_message or ""):
            return None

        expected_artifacts = context.get("expected_artifacts", {})
        artifacts: Dict[str, Dict[str, Any]] = {}
        lesson_exists = False
        pptx_exists = False

        for artifact_key, descriptor in (expected_artifacts or {}).items():
            path_value = str(descriptor.get("path", "")).strip()
            if not path_value:
                continue
            artifact_path = Path(path_value)
            if not artifact_path.exists():
                continue
            if artifact_key == "lesson_plan":
                lesson_exists = True
                self._ensure_qgis_guidance_block(str(artifact_path), route)
            if artifact_key == "pptx":
                pptx_exists = True
            artifacts[artifact_key] = {
                "artifact_type": descriptor.get("artifact_type", "output"),
                "title": descriptor.get("title", artifact_key),
                "path": str(artifact_path),
            }

        if not artifacts:
            return None

        if lesson_exists and pptx_exists:
            summary = "Teaching package and PPT files were generated, but OpenClaw timed out before returning the final result block."
            assistant_message = "已生成教学成果包与 PPT，但 OpenClaw 在返回最终结果块前超时。"
        elif lesson_exists:
            summary = "Teaching package files were generated, but OpenClaw timed out before the PPT workflow completed."
            assistant_message = "已生成教学成果包，但 PPT 流程在返回最终结果块前超时。"
        else:
            summary = "PPT file was generated, but the lesson workflow timed out before the final result block was returned."
            assistant_message = "已生成 PPT，但 lesson_ppt 流程在返回最终结果块前超时。"

        return {
            "status": "success",
            "summary": summary,
            "assistant_message": assistant_message,
            "notes": error_message,
            "workflow_type": TASK_MODE_LESSON_PPT,
            "template_id": "",
            "export_path": "",
            "stages": {
                "analysis": {"status": "success", "summary": "Parsed the teaching request.", "detail": ""},
                "design": {
                    "status": "success" if lesson_exists else "warning",
                    "summary": "Teaching package files were generated." if lesson_exists else "Teaching package files were not generated before timeout.",
                    "detail": "",
                },
                "map": {"status": "skipped", "summary": "QGIS execution is disabled in lesson_ppt mode.", "detail": ""},
                "presentation": {
                    "status": "success" if pptx_exists else "warning",
                    "summary": "PPT file was generated." if pptx_exists else "PPT generation did not finish before timeout.",
                    "detail": "",
                },
            },
            "artifacts": artifacts,
            "steps": [
                {
                    "title": "Recovered lesson artifacts",
                    "detail": summary,
                    "status": "warning",
                }
            ],
            "partial_output": True,
        }

    def _build_lesson_ppt_context(self, project_id: str, job_id: str, route: Dict[str, Any]) -> Dict[str, Any]:
        output_dir = self.config.project_output_dir(project_id)
        if route.get("showcase_mode") == self.config.population_showcase_mode:
            return self._build_population_lesson_ppt_context(output_dir=output_dir, job_id=job_id, route=route)

        lesson_plan_path = output_dir / f"lesson_plan_{job_id}.md"
        lesson_plan_docx_path = output_dir / f"lesson_plan_{job_id}.docx"
        guidance_path = output_dir / f"lesson_guidance_{job_id}.md"
        guidance_docx_path = output_dir / f"lesson_guidance_{job_id}.docx"
        homework_path = output_dir / f"lesson_homework_{job_id}.md"
        homework_docx_path = output_dir / f"lesson_homework_{job_id}.docx"
        review_path = output_dir / f"lesson_review_{job_id}.md"
        review_docx_path = output_dir / f"lesson_review_{job_id}.docx"
        pptx_path = output_dir / f"teaching_slides_{job_id}.pptx"
        deck_scenario_path = output_dir / f"teaching_slides_{job_id}.scenario.json"
        expected_artifacts = {
            "lesson_plan": {
                "artifact_type": "lesson_plan",
                "title": "Unit Teaching Design",
                "path": str(lesson_plan_path),
            },
            "lesson_plan_docx": {
                "artifact_type": "docx",
                "title": "Unit Teaching Design (Word)",
                "path": str(lesson_plan_docx_path),
            },
            "guidance": {
                "artifact_type": "markdown",
                "title": "Learning Guidance",
                "path": str(guidance_path),
            },
            "guidance_docx": {
                "artifact_type": "docx",
                "title": "Learning Guidance (Word)",
                "path": str(guidance_docx_path),
            },
            "homework": {
                "artifact_type": "markdown",
                "title": "Homework Package",
                "path": str(homework_path),
            },
            "homework_docx": {
                "artifact_type": "docx",
                "title": "Homework Package (Word)",
                "path": str(homework_docx_path),
            },
            "review": {
                "artifact_type": "markdown",
                "title": "Review Package",
                "path": str(review_path),
            },
            "review_docx": {
                "artifact_type": "docx",
                "title": "Review Package (Word)",
                "path": str(review_docx_path),
            },
            "pptx": {
                "artifact_type": "pptx",
                "title": "Teaching Slides",
                "path": str(pptx_path),
            },
            "deck_scenario": {
                "artifact_type": "json",
                "title": "Deck Scenario",
                "path": str(deck_scenario_path),
            },
        }
        return {
            "workflow_mode": TASK_MODE_LESSON_PPT,
            "requires_export": False,
            "requires_map": False,
            "export_path": "",
            "lesson_plan_path": str(lesson_plan_path),
            "lesson_plan_docx_path": str(lesson_plan_docx_path),
            "pptx_path": str(pptx_path),
            "deck_scenario_path": str(deck_scenario_path),
            "document_paths": {
                "lesson_plan": str(lesson_plan_path),
                "guidance": str(guidance_path),
                "homework": str(homework_path),
                "review": str(review_path),
            },
            "document_docx_paths": {
                "lesson_plan": str(lesson_plan_docx_path),
                "guidance": str(guidance_docx_path),
                "homework": str(homework_docx_path),
                "review": str(review_docx_path),
            },
            "suggested_template": route.get("suggested_template") or route.get("fallback_template") or "",
            "showcase_mode": route.get("showcase_mode", ""),
            "knowledge_root": "",
            "dataset_manifest_path": "",
            "expected_artifacts": expected_artifacts,
            "population_preflight": {},
            "knowledge_bundle": {},
            "package_profile": {},
            "presentation_style": route.get("presentation_style") or resolve_presentation_style("", Path(self.config.ppt_studio_skill_dir)),
        }

    def _build_population_lesson_ppt_context(self, output_dir: Path, job_id: str, route: Dict[str, Any]) -> Dict[str, Any]:
        expected_artifacts = self._filter_artifacts_for_mode(
            self.population_showcase.default_artifacts(output_dir, job_id),
            TASK_MODE_LESSON_PPT,
        )
        return {
            "workflow_mode": TASK_MODE_LESSON_PPT,
            "requires_export": False,
            "requires_map": False,
            "export_path": "",
            "lesson_plan_path": expected_artifacts["lesson_plan"]["path"],
            "lesson_plan_docx_path": expected_artifacts["lesson_plan_docx"]["path"],
            "pptx_path": expected_artifacts["pptx"]["path"],
            "deck_scenario_path": expected_artifacts["deck_scenario"]["path"],
            "document_paths": {
                "lesson_plan": expected_artifacts["lesson_plan"]["path"],
                "guidance": expected_artifacts["guidance"]["path"],
                "homework": expected_artifacts["homework"]["path"],
                "review": expected_artifacts["review"]["path"],
            },
            "document_docx_paths": {
                "lesson_plan": expected_artifacts["lesson_plan_docx"]["path"],
                "guidance": expected_artifacts["guidance_docx"]["path"],
                "homework": expected_artifacts["homework_docx"]["path"],
                "review": expected_artifacts["review_docx"]["path"],
            },
            "suggested_template": route.get("suggested_template") or route.get("fallback_template") or "",
            "showcase_mode": self.config.population_showcase_mode,
            "knowledge_root": str(self.config.population_knowledge_root),
            "dataset_manifest_path": str(self.config.population_dataset_manifest_path),
            "expected_artifacts": expected_artifacts,
            "population_preflight": {},
            "knowledge_bundle": self.population_showcase.knowledge_bundle(),
            "package_profile": self.population_showcase.package_profile(),
            "presentation_style": route.get("presentation_style") or resolve_presentation_style("", Path(self.config.ppt_studio_skill_dir)),
        }

    def _build_qgis_only_context(self, project_id: str, job_id: str, route: Dict[str, Any], message: str) -> Dict[str, Any]:
        output_dir = self.config.project_output_dir(project_id)
        requires_export = bool(route.get("requires_export", self._request_requires_export(message, route.get("suggested_template"))))
        suggested_template = route.get("suggested_template") or ""
        export_path = ""
        expected_artifacts: Dict[str, Dict[str, Any]] = {}
        if requires_export:
            if suggested_template and suggested_template in TEMPLATE_SPECS:
                export_path = str(self.template_executor.build_output_path(project_id, suggested_template))
            else:
                export_path = str(output_dir / f"qgis_result_{job_id}.png")
            expected_artifacts["map_export"] = {
                "artifact_type": "map_export",
                "title": "QGIS Export",
                "path": export_path,
            }
        return {
            "workflow_mode": TASK_MODE_QGIS_ONLY,
            "request_id": f"{job_id}_qgis_only",
            "requires_export": requires_export,
            "requires_map": True,
            "export_path": export_path,
            "lesson_plan_path": "",
            "pptx_path": "",
            "showcase_mode": route.get("showcase_mode", ""),
            "knowledge_root": "",
            "dataset_manifest_path": "",
            "expected_artifacts": expected_artifacts,
            "population_preflight": {},
            "knowledge_bundle": {},
            "package_profile": {},
            "presentation_style": "",
            "suggested_template": suggested_template,
            "fallback_template": route.get("fallback_template") or "",
            "target_layer_scope": "all_visible_layers",
        }

    def _filter_artifacts_for_mode(
        self,
        artifacts: Dict[str, Dict[str, Any]],
        task_mode: str,
    ) -> Dict[str, Dict[str, Any]]:
        if task_mode != TASK_MODE_LESSON_PPT:
            return dict(artifacts or {})
        allowed_keys = {"lesson_plan", "lesson_plan_docx", "guidance", "guidance_docx", "homework", "homework_docx", "review", "review_docx", "pptx", "deck_scenario"}
        return {key: value for key, value in (artifacts or {}).items() if key in allowed_keys}

    def _ensure_qgis_guidance_block(self, lesson_plan_path: str, route: Dict[str, Any]) -> None:
        path_value = str(lesson_plan_path or "").strip()
        if not path_value:
            return
        lesson_plan = Path(path_value)
        if not lesson_plan.exists():
            return
        try:
            content = lesson_plan.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = lesson_plan.read_text(encoding="utf-8", errors="replace")
        if "建议 QGIS 操作" in content:
            return
        guidance = self._build_qgis_guidance_block(route)
        updated = content.rstrip()
        if updated:
            updated += "\n\n"
        updated += guidance + "\n"
        lesson_plan.write_text(updated, encoding="utf-8")

    def _build_qgis_guidance_block(self, route: Dict[str, Any]) -> str:
        suggestions: List[str] = []
        template_hints: List[str] = []
        if route.get("showcase_mode") == self.config.population_showcase_mode:
            suggestions.extend(
                [
                    "推荐图层：`china_provinces_population.geojson`、`china_population_sample.csv`、`china_migration_sample.csv`。",
                    "推荐字段：`population`、`density`、`migration_count`、`name` 或 `city_name`。",
                    "建议导出物：Theme 1 分布图、Theme 2 迁移图、对比图表预览。",
                ]
            )
            template_hints.extend(
                [
                    "`population_distribution` / `population_density` / `hu_line_comparison`",
                    "`population_migration`",
                    "`population_change_comparison` / `population_capacity_dashboard`",
                ]
            )
        elif route.get("suggested_template") or route.get("fallback_template"):
            template_hints.append(f"`{route.get('suggested_template') or route.get('fallback_template')}`")
            suggestions.append("建议先确认目标图层名称与核心数值字段，再执行模板导出。")
        else:
            suggestions.append("建议先检查当前 QGIS 图层，再选择合适的人口或区域分布模板。")

        lines = ["## 建议 QGIS 操作"]
        if template_hints:
            lines.append(f"- 推荐模板：{'，'.join(template_hints)}。")
        lines.extend(f"- {item}" for item in suggestions)
        return "\n".join(lines)

    def _merge_expected_artifacts(
        self,
        artifacts: Dict[str, Dict[str, Any]],
        expected_artifacts: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        merged = dict(artifacts or {})
        for key, descriptor in (expected_artifacts or {}).items():
            merged.setdefault(key, descriptor)
        return merged

    def _complete_chat_job(self, job_id: str, project_id: str, result: Dict[str, Any]) -> None:
        artifacts = self._register_result_artifacts(
            project_id,
            job_id,
            result.get("artifacts", {}),
            result.get("engine", self.assistant_engine.name),
        )
        export_path = result.get("export_path", "")
        if export_path:
            self.store.append_job_step(job_id, "导出完成", f"输出已保存到 {export_path}", "success")
        else:
            self.store.append_job_step(job_id, "已获取最终结果", result.get("summary", ""), "success")
        self.store.set_job_status(
            job_id,
            "completed",
            result={
                "status": result.get("status", "success"),
                "request_id": result.get("request_id", ""),
                "workflow_type": result.get("workflow_type", ""),
                "task_mode": result.get("task_mode", ""),
                "summary": result.get("summary", ""),
                "assistant_message": result.get("assistant_message", ""),
                "template_id": result.get("template_id", ""),
                "notes": result.get("notes", ""),
                "export_path": export_path,
                "stages": self.store.get_job(job_id).stages,
                "artifacts": artifacts,
                "verification": result.get("verification", {}),
                "showcase_mode": result.get("showcase_mode", ""),
                "presentation_style": result.get("presentation_style", ""),
                "showcase_highlights": result.get("showcase_highlights", []),
                "package_contract_summary": result.get("package_contract_summary", []),
            },
        )

    def _register_result_artifacts(
        self,
        project_id: str,
        job_id: str,
        artifacts: Dict[str, Dict[str, Any]],
        engine_name: str,
    ) -> Dict[str, Dict[str, Any]]:
        registered: Dict[str, Dict[str, Any]] = {}
        registered_by_path: Dict[str, Any] = {}
        for name, descriptor in (artifacts or {}).items():
            path_value = str(descriptor.get("path", "")).strip()
            if not path_value:
                registered[name] = {**descriptor, "artifact_id": None}
                continue
            artifact_path = Path(path_value)
            metadata = dict(descriptor.get("metadata", {}))
            metadata["engine"] = engine_name
            metadata.setdefault("artifact_key", name)
            if artifact_path.suffix.lower() in {".md", ".txt", ".json"} and artifact_path.exists():
                metadata["preview_text"] = self._build_text_preview(artifact_path)
            if artifact_path.exists():
                cache_key = str(artifact_path).lower()
                artifact = registered_by_path.get(cache_key)
                if artifact is None:
                    artifact = self.store.register_artifact(
                        project_id,
                        job_id,
                        descriptor.get("artifact_type", "output"),
                        descriptor.get("title", artifact_path.name),
                        str(artifact_path),
                        metadata=metadata,
                    )
                    registered_by_path[cache_key] = artifact
                registered[name] = {
                    **descriptor,
                    "path": str(artifact_path),
                    "artifact_id": artifact.artifact_id,
                    "metadata": metadata,
                }
            else:
                registered[name] = {**descriptor, "path": str(artifact_path), "artifact_id": None, "metadata": metadata}
        return registered

    def _build_text_preview(self, path: Path, max_chars: int = 2400) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""

    def _inspect_project_layers(self) -> List[Dict[str, Any]]:
        response = self.qgis.call("get_layers")
        return response.get("data", [])

    def _build_fallback_payload(self, project_id: str, template_id: str, message: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        explicit_layer = self._extract_named_payload(message, ["layer_name", "line_layer_name", "origins_layer", "destinations_layer"])
        explicit_value = self._extract_named_payload(message, COMMON_VALUE_FIELDS)
        explicit_capacity = self._extract_named_payload(message, CAPACITY_VALUE_FIELDS)
        explicit_label = self._extract_named_payload(message, COMMON_LABEL_FIELDS)
        if explicit_layer:
            payload["layer_name"] = explicit_layer
        layers = self._inspect_project_layers()
        best_layer = payload.get("layer_name") or self._pick_best_layer(template_id, layers)
        if best_layer and template_id != "population_migration":
            payload["layer_name"] = best_layer
        if template_id == "population_distribution":
            payload["value_field"] = explicit_value or self._pick_best_field(layers, best_layer, COMMON_VALUE_FIELDS) or "population"
            payload["label_field"] = explicit_label or self._pick_best_field(layers, best_layer, COMMON_LABEL_FIELDS) or "name"
        elif template_id == "population_density":
            payload["weight_field"] = explicit_value or self._extract_named_payload(message, ["weight_field"]) or "population"
        elif template_id == "population_migration":
            payload["line_layer_name"] = explicit_layer or best_layer or "migration_flows"
            payload["width_field"] = explicit_value or self._extract_named_payload(message, ["width_field"]) or "value"
        elif template_id == "hu_line_comparison":
            payload["weight_field"] = explicit_value or self._extract_named_payload(message, ["weight_field"]) or "population"
        elif template_id == "population_change_comparison":
            payload["value_field"] = explicit_value or self._pick_best_field(layers, best_layer, COMMON_VALUE_FIELDS) or "population"
            payload["label_field"] = explicit_label or self._pick_best_field(layers, best_layer, COMMON_LABEL_FIELDS) or "name"
            payload["chart_category_field"] = payload["label_field"]
            payload["chart_value_field"] = payload["value_field"]
            payload["weight_field"] = payload["value_field"]
        elif template_id == "population_capacity_dashboard":
            payload["value_field"] = explicit_capacity or self._pick_best_field(layers, best_layer, CAPACITY_VALUE_FIELDS) or "population"
            payload["label_field"] = explicit_label or self._pick_best_field(layers, best_layer, COMMON_LABEL_FIELDS) or "name"
            payload["chart_category_field"] = payload["label_field"]
            payload["chart_value_field"] = payload["value_field"]
        return payload

    def _pick_best_layer(self, template_id: str, layers: List[Dict[str, Any]]) -> str:
        if not layers:
            return ""
        if template_id == "population_migration":
            for layer in layers:
                geometry_type = str(layer.get("geometry_type", "")).lower()
                if geometry_type in {"1", "line", "linestring"} or str(layer.get("type")) in {"1", "line", "LineString"}:
                    return layer.get("name", "")
        return layers[0].get("name", "")

    def _pick_best_field(self, layers: List[Dict[str, Any]], layer_name: str, candidates: List[str]) -> str:
        for layer in layers:
            if layer_name and layer.get("name") != layer_name:
                continue
            fields = [str(field).lower() for field in layer.get("fields", [])]
            for candidate in candidates:
                if candidate.lower() in fields:
                    return candidate
        return ""

    def _request_requires_export(self, message: str, template_id: Optional[str]) -> bool:
        text = (message or "").lower()
        if any(keyword in text for keyword in QUERY_KEYWORDS):
            return False
        return any(keyword in text for keyword in ("导出", "export", "保存", "layout", "布局", "png", "jpg", "jpeg", "pdf", "截图", "image"))

    def _extract_named_payload(self, message: str, keys: List[str]) -> str:
        for key in keys:
            pattern = re.escape(key) + r'\s*[:=]\s*["\']?([^,"\'}\n]+)'
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _suggest_template(self, message: str) -> Optional[str]:
        text = (message or "").lower()
        if "热力" in text or "密度" in text or "heatmap" in text or "density" in text:
            return "population_density"
        if "迁移" in text or "流向" in text or "migration" in text or "flow" in text:
            return "population_migration"
        if "承载力" in text or "合理容量" in text or "capacity" in text:
            return "population_capacity_dashboard"
        if ("变化" in text or "对比" in text or "compare" in text or "dashboard" in text) and ("人口" in text or "population" in text):
            return "population_change_comparison"
        if "胡焕庸" in text or "hu line" in text:
            return "hu_line_comparison"
        if "人口" in text or "distribution" in text or "分级设色" in text:
            return "population_distribution"
        return None

    def _detect_showcase_mode(self, message: str, is_teaching: bool) -> str:
        text = (message or "").lower()
        has_population = any(keyword in text for keyword in POPULATION_KEYWORDS)
        has_showcase = any(keyword in text for keyword in SHOWCASE_KEYWORDS)
        if has_population and (is_teaching or has_showcase):
            return self.config.population_showcase_mode
        return ""

    def _normalize_task_mode(self, task_mode: str) -> str:
        value = (task_mode or "").strip().lower()
        if value in LEGACY_LESSON_TASK_MODES:
            return TASK_MODE_LESSON_PPT
        if value in LEGACY_QGIS_TASK_MODES:
            return TASK_MODE_QGIS_ONLY
        return ""

    def _normalize_presentation_style(self, presentation_style: str) -> str:
        return resolve_presentation_style(presentation_style, Path(self.config.ppt_studio_skill_dir))

    def _classify_chat_request(
        self,
        message: str,
        task_mode: str = "",
        presentation_style: str = "",
    ) -> Dict[str, Any]:
        text = (message or "").lower()
        normalized_task_mode = self._normalize_task_mode(task_mode)
        normalized_presentation_style = self._normalize_presentation_style(presentation_style)
        suggested_template = self._suggest_template(message)
        is_query = any(keyword in text for keyword in QUERY_KEYWORDS)
        is_teaching = any(keyword in text for keyword in TEACHING_KEYWORDS)
        has_qgis_intent = bool(
            suggested_template
            or is_query
            or any(keyword in text for keyword in MAP_HINT_KEYWORDS)
            or any(keyword in text for keyword in DIRECT_QGIS_KEYWORDS)
        )
        showcase_mode = self._detect_showcase_mode(
            message,
            is_teaching=is_teaching or normalized_task_mode == TASK_MODE_LESSON_PPT,
        )
        lesson_fallback_template = "population_change_comparison" if showcase_mode == self.config.population_showcase_mode else suggested_template

        if normalized_task_mode == TASK_MODE_LESSON_PPT:
            return {
                "workflow_type": TASK_MODE_LESSON_PPT,
                "task_mode": TASK_MODE_LESSON_PPT,
                "route": TASK_MODE_LESSON_PPT,
                "suggested_template": suggested_template,
                "fallback_template": lesson_fallback_template,
                "showcase_mode": showcase_mode,
                "requires_map": False,
                "presentation_style": normalized_presentation_style,
            }

        if normalized_task_mode == TASK_MODE_QGIS_ONLY:
            return {
                "workflow_type": TASK_MODE_QGIS_ONLY,
                "task_mode": TASK_MODE_QGIS_ONLY,
                "route": TASK_MODE_QGIS_ONLY,
                "suggested_template": suggested_template,
                "fallback_template": suggested_template,
                "showcase_mode": showcase_mode,
                "requires_map": True,
                "requires_export": self._request_requires_export(message, suggested_template),
                "presentation_style": "",
            }

        if has_qgis_intent and not is_teaching:
            return {
                "workflow_type": TASK_MODE_QGIS_ONLY,
                "task_mode": TASK_MODE_QGIS_ONLY,
                "route": TASK_MODE_QGIS_ONLY,
                "suggested_template": suggested_template,
                "fallback_template": suggested_template,
                "showcase_mode": showcase_mode,
                "requires_map": True,
                "requires_export": self._request_requires_export(message, suggested_template),
                "presentation_style": "",
            }

        return {
            "workflow_type": TASK_MODE_LESSON_PPT,
            "task_mode": TASK_MODE_LESSON_PPT,
            "route": TASK_MODE_LESSON_PPT,
            "suggested_template": suggested_template,
            "fallback_template": lesson_fallback_template,
            "showcase_mode": showcase_mode,
            "requires_map": False,
            "presentation_style": normalized_presentation_style,
        }

    def _format_layers_notes(self, layers: List[Dict[str, Any]]) -> str:
        if not layers:
            return "当前 QGIS 项目中未检测到图层。"
        lines = [f"当前项目包含 {len(layers)} 个图层："]
        for index, layer in enumerate(layers, start=1):
            fields = ", ".join(str(field) for field in layer.get("fields", [])[:12])
            geometry_type = layer.get("geometry_type", "")
            lines.append(
                f"{index}. {layer.get('name', '未命名图层')} | 数据源={layer.get('provider', '')} | 类型={layer.get('type', '')} | 几何类型={geometry_type} | 坐标系={layer.get('crs', '')} | 字段={fields}"
            )
        return "\n".join(lines)

    def _default_stages(
        self,
        workflow_type: str,
        requires_map: bool = False,
        route_name: str = "",
    ) -> Dict[str, Dict[str, str]]:
        stages = build_workflow_stages()
        if workflow_type in {"map_template", "qgis_query", TASK_MODE_QGIS_ONLY}:
            stages["design"]["status"] = "skipped"
            stages["design"]["summary"] = "当前为 qgis_only 模式，不生成教学设计。" if workflow_type == TASK_MODE_QGIS_ONLY else "当前任务不需要教学设计。"
            stages["presentation"]["status"] = "skipped"
            stages["presentation"]["summary"] = "当前为 qgis_only 模式，不生成 PPT。" if workflow_type == TASK_MODE_QGIS_ONLY else "当前任务不需要演示文稿输出。"
        if workflow_type == TASK_MODE_LESSON_PPT:
            stages["map"]["status"] = "skipped"
            stages["map"]["summary"] = "当前为 lesson_ppt 模式，不执行 QGIS 操作。"
        elif workflow_type == TASK_MODE_QGIS_ONLY:
            stages["map"]["summary"] = "准备在当前项目中直接执行 QGIS 操作。"
        elif workflow_type == "qgis_query" or route_name == "query":
            stages["map"]["summary"] = "正在检查当前 QGIS 项目。"
        elif workflow_type == "map_template" or route_name == "template":
            stages["map"]["summary"] = "准备执行 QGIS 模板任务。"
        elif not requires_map:
            stages["map"]["status"] = "skipped"
            stages["map"]["summary"] = "当前任务不需要地图输出。"
        return stages

    def _update_stage(self, job_id: str, stage_name: str, status: str, summary: str = "", detail: str = "") -> None:
        self.store.update_job_stage(job_id, stage_name, status, summary, detail)

    def _merge_stage_payloads(
        self,
        base_stages: Dict[str, Dict[str, str]],
        incoming: Dict[str, Dict[str, str]],
    ) -> Dict[str, Dict[str, str]]:
        merged = {key: dict(value) for key, value in base_stages.items()}
        for key in WORKFLOW_STAGE_KEYS:
            if key in incoming:
                merged[key] = {
                    "status": incoming[key].get("status", merged.get(key, {}).get("status", "pending")),
                    "summary": incoming[key].get("summary", merged.get(key, {}).get("summary", "")),
                    "detail": incoming[key].get("detail", merged.get(key, {}).get("detail", "")),
                }
        return merged

    def _fail_job(self, job_id: str, workflow_type: str, message: str, task_mode: str = "") -> None:
        self.store.append_job_step(job_id, "智能执行失败", message, "error")
        self._mark_remaining_stages_failed(job_id, message)
        self.store.set_job_status(
            job_id,
            "failed",
            result={
                "status": "error",
                "workflow_type": workflow_type,
                "task_mode": task_mode,
                "summary": "智能执行暂时不可用。",
                "assistant_message": "智能执行暂时不可用。",
                "template_id": "",
                "notes": message,
                "export_path": "",
                "stages": self.store.get_job(job_id).stages,
                "artifacts": {},
            },
            error=message,
        )

    def _mark_remaining_stages_failed(self, job_id: str, detail: str) -> None:
        job = self.store.get_job(job_id)
        for key, payload in job.stages.items():
            if payload.get("status") in {"pending", "queued", "running"}:
                self._update_stage(job_id, key, "failed", payload.get("summary", "当前阶段执行失败。"), detail)
