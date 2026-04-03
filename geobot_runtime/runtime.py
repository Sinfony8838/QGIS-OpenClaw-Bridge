from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import RuntimeConfig
from .gisclaw_engine import GISclawEngine
from .models import WORKFLOW_STAGE_KEYS, build_workflow_stages
from .openclaw_engine import OpenClawEngine
from .qgis_bridge import QgisBridgeClient
from .store import RuntimeStore
from .templates import TEMPLATE_SPECS, TemplateExecutor


COMMON_VALUE_FIELDS = ["population", "pop", "value", "count", "density", "score"]
COMMON_LABEL_FIELDS = ["name", "province", "city", "label", "region"]
QUERY_KEYWORDS = ["检查", "查看", "查询", "当前图层", "图层情况", "layers", "layer"]
TEACHING_KEYWORDS = ["教学", "教案", "课程", "课堂", "ppt", "课件", "lesson", "slides"]
MAP_HINT_KEYWORDS = ["地图", "制图", "qgis", "热力图", "密度图", "迁移图", "胡焕庸", "分级设色"]


class GeoBotRuntime:
    def __init__(self, config: Optional[RuntimeConfig] = None):
        self.config = config or RuntimeConfig()
        self.config.ensure_dirs()
        self.store = RuntimeStore(self.config.state_file)
        self.qgis = QgisBridgeClient(self.config.qgis_host, self.config.qgis_port)
        self.template_executor = TemplateExecutor(self.config, self.qgis)
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

    def submit_chat(self, project_id: str, message: str) -> Dict[str, Any]:
        route = self._classify_chat_request(message)
        title = "GeoBot chat task"
        job = self.store.create_job(
            project_id=project_id,
            job_type="chat",
            title=title,
            workflow_type=route["workflow_type"],
            request={"message": message, "route": route},
            stages=self._default_stages(route["workflow_type"], requires_map=route["requires_map"]),
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
            artifacts = {
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
            self.store.append_job_step(job_id, "Job created", "Analyzing the teaching request.", "queued")
            if route["workflow_type"] == "qgis_query":
                result = self._run_query_request(job_id, project_id, message)
            elif route["workflow_type"] == "map_template":
                result = self._run_map_template_request(job_id, project_id, message, route)
            else:
                result = self._run_teacher_flow_request(job_id, project_id, message, route)
            if result.get("status") == "error":
                raise RuntimeError(result.get("notes") or result.get("summary") or "Workflow execution failed")
            self._complete_chat_job(job_id, project_id, result)
        except Exception as exc:
            self._fail_job(job_id, route["workflow_type"], str(exc))

    def _run_query_request(self, job_id: str, project_id: str, message: str) -> Dict[str, Any]:
        self._update_stage(job_id, "analysis", "running", "Parsing the QGIS query.")
        self.store.append_job_step(job_id, "Calling QGIS", "Inspecting the current QGIS project.", "running")
        response = self.qgis.call("get_layers")
        layers = response.get("data", [])
        self._update_stage(job_id, "analysis", "success", "Parsed the inspection request.")
        self._update_stage(job_id, "map", "success", "Collected current QGIS layers.")
        return {
            "status": "success",
            "workflow_type": "qgis_query",
            "summary": "检查当前图层情况",
            "assistant_message": "当前 QGIS 项目图层已检查完成。",
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
        return {
            "status": "success",
            "workflow_type": "map_template",
            "summary": result["title"],
            "assistant_message": f"已完成 {result['title']}。",
            "template_id": template_id,
            "notes": result["response"].get("message", ""),
            "export_path": result["export_path"],
            "stages": self.store.get_job(job_id).stages,
            "artifacts": {
                "map_export": {
                    "artifact_type": "map_export",
                    "title": result["title"],
                    "path": result["export_path"],
                }
            },
        }

    def _run_teacher_flow_request(
        self,
        job_id: str,
        project_id: str,
        message: str,
        route: Dict[str, Any],
    ) -> Dict[str, Any]:
        output_dir = self.config.project_output_dir(project_id)
        lesson_plan_path = output_dir / f"lesson_plan_{job_id}.md"
        pptx_path = output_dir / f"teaching_slides_{job_id}.pptx"
        map_export_path = output_dir / f"teaching_map_{job_id}.png" if route["requires_map"] else Path("")

        self._update_stage(job_id, "analysis", "running", "Parsing the teaching request.")
        self._update_stage(job_id, "design", "queued", "Preparing lesson design.")
        if route["requires_map"]:
            self._update_stage(job_id, "map", "queued", "Waiting for QGIS map execution.")
        self._update_stage(job_id, "presentation", "queued", "Waiting for presentation generation.")
        self.store.append_job_step(job_id, "Calling assistant engine", "Forwarding the request to the hidden assistant engine.", "running")

        health = self.assistant_engine.health()
        if not health.get("reachable") and self.config.assistant_fallback_templates and route["suggested_template"]:
            return self._run_map_template_request(job_id, project_id, message, route)

        result = self.assistant_engine.chat(
            project_id,
            message,
            context={
                "workflow_mode": "teacher_flow",
                "requires_export": route["requires_map"],
                "requires_map": route["requires_map"],
                "export_path": str(map_export_path) if route["requires_map"] else "",
                "lesson_plan_path": str(lesson_plan_path),
                "pptx_path": str(pptx_path),
                "suggested_template": route["suggested_template"] or "",
            },
        )
        for step in result.get("steps", []):
            self.store.append_job_step(
                job_id,
                step.get("title", "Assistant step"),
                step.get("detail", ""),
                step.get("status", "info"),
            )
        merged_stages = self._merge_stage_payloads(self.store.get_job(job_id).stages, result.get("stages", {}))
        self.store.get_job(job_id).stages = merged_stages
        return {
            "status": result.get("status", "success"),
            "workflow_type": result.get("workflow_type") or "teacher_flow",
            "summary": result.get("summary", "Teaching workflow completed."),
            "assistant_message": result.get("assistant_message", ""),
            "template_id": result.get("template_id", ""),
            "notes": result.get("notes", ""),
            "export_path": result.get("export_path", ""),
            "stages": merged_stages,
            "artifacts": result.get("artifacts", {}),
            "engine": result.get("engine", self.assistant_engine.name),
        }

    def _complete_chat_job(self, job_id: str, project_id: str, result: Dict[str, Any]) -> None:
        artifacts = self._register_result_artifacts(
            project_id,
            job_id,
            result.get("artifacts", {}),
            result.get("engine", self.assistant_engine.name),
        )
        export_path = result.get("export_path", "")
        if export_path:
            self.store.append_job_step(job_id, "Export complete", f"Saved output to {export_path}", "success")
        else:
            self.store.append_job_step(job_id, "Captured final result", result.get("summary", ""), "success")
        self.store.set_job_status(
            job_id,
            "completed",
            result={
                "status": result.get("status", "success"),
                "workflow_type": result.get("workflow_type", ""),
                "summary": result.get("summary", ""),
                "assistant_message": result.get("assistant_message", ""),
                "template_id": result.get("template_id", ""),
                "notes": result.get("notes", ""),
                "export_path": export_path,
                "stages": self.store.get_job(job_id).stages,
                "artifacts": artifacts,
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
        for name, descriptor in (artifacts or {}).items():
            path_value = str(descriptor.get("path", "")).strip()
            if not path_value:
                registered[name] = {**descriptor, "artifact_id": None}
                continue
            artifact_path = Path(path_value)
            metadata = dict(descriptor.get("metadata", {}))
            metadata["engine"] = engine_name
            if artifact_path.suffix.lower() in {".md", ".txt"} and artifact_path.exists():
                metadata["preview_text"] = self._build_text_preview(artifact_path)
            if artifact_path.exists():
                artifact = self.store.register_artifact(
                    project_id,
                    job_id,
                    descriptor.get("artifact_type", "output"),
                    descriptor.get("title", artifact_path.name),
                    str(artifact_path),
                    metadata=metadata,
                )
                registered[name] = {**descriptor, "path": str(artifact_path), "artifact_id": artifact.artifact_id, "metadata": metadata}
            else:
                registered[name] = {**descriptor, "path": str(artifact_path), "artifact_id": None, "metadata": metadata}
        return registered

    def _build_text_preview(self, path: Path, max_chars: int = 2400) -> str:
        try:
            return path.read_text(encoding="utf-8")[:max_chars]
        except Exception:
            return ""

    def _inspect_project_layers(self) -> List[Dict[str, Any]]:
        response = self.qgis.call("get_layers")
        return response.get("data", [])

    def _build_fallback_payload(self, project_id: str, template_id: str, message: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        explicit_layer = self._extract_named_payload(message, ["layer_name", "line_layer_name", "origins_layer", "destinations_layer"])
        explicit_value = self._extract_named_payload(message, COMMON_VALUE_FIELDS)
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
        return payload

    def _pick_best_layer(self, template_id: str, layers: List[Dict[str, Any]]) -> str:
        if not layers:
            return ""
        if template_id == "population_migration":
            for layer in layers:
                if str(layer.get("type")) in {"1", "line", "LineString"}:
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
        if template_id:
            return True
        if any(keyword in text for keyword in ("检查", "查看", "查询", "当前图层", "layers", "layer")):
            return False
        return any(keyword in text for keyword in ("导出", "export", "地图", "制图", "ppt", "课件"))

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
        if "胡焕庸" in text or "hu line" in text:
            return "hu_line_comparison"
        if "人口" in text or "distribution" in text or "分级设色" in text:
            return "population_distribution"
        return None

    def _classify_chat_request(self, message: str) -> Dict[str, Any]:
        text = message.lower()
        suggested_template = self._suggest_template(message)
        is_query = any(keyword in text for keyword in QUERY_KEYWORDS)
        is_teaching = any(keyword in text for keyword in TEACHING_KEYWORDS)
        requires_map = bool(suggested_template or any(keyword in text for keyword in MAP_HINT_KEYWORDS))
        if is_query:
            return {"workflow_type": "qgis_query", "route": "query", "suggested_template": None, "requires_map": False}
        if is_teaching:
            return {"workflow_type": "teacher_flow", "route": "teacher_flow", "suggested_template": suggested_template, "requires_map": requires_map}
        if suggested_template:
            return {"workflow_type": "map_template", "route": "template", "suggested_template": suggested_template, "requires_map": True}
        return {"workflow_type": "teacher_flow", "route": "teacher_flow", "suggested_template": None, "requires_map": requires_map}

    def _format_layers_notes(self, layers: List[Dict[str, Any]]) -> str:
        if not layers:
            return "当前项目中没有检测到图层。"
        lines = [f"当前项目包含 {len(layers)} 个图层："]
        for index, layer in enumerate(layers, start=1):
            lines.append(
                f"{index}. {layer.get('name', 'Unnamed')} | provider={layer.get('provider', '')} | type={layer.get('type', '')} | crs={layer.get('crs', '')}"
            )
        return "\n".join(lines)

    def _default_stages(self, workflow_type: str, requires_map: bool = False) -> Dict[str, Dict[str, str]]:
        stages = build_workflow_stages()
        if workflow_type in {"map_template", "qgis_query"}:
            stages["design"]["status"] = "skipped"
            stages["design"]["summary"] = "Lesson design was not required."
            stages["presentation"]["status"] = "skipped"
            stages["presentation"]["summary"] = "Presentation generation was not required."
        if workflow_type == "qgis_query":
            stages["map"]["summary"] = "Inspecting the current QGIS project."
        elif workflow_type == "map_template":
            stages["map"]["summary"] = "Preparing direct QGIS template execution."
        elif not requires_map:
            stages["map"]["status"] = "skipped"
            stages["map"]["summary"] = "Map generation was not required."
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

    def _fail_job(self, job_id: str, workflow_type: str, message: str) -> None:
        self.store.append_job_step(job_id, "Assistant execution failed", message, "error")
        self._mark_remaining_stages_failed(job_id, message)
        self.store.set_job_status(
            job_id,
            "failed",
            result={
                "status": "error",
                "workflow_type": workflow_type,
                "summary": "智能执行暂不可用",
                "assistant_message": "Intelligent execution is temporarily unavailable.",
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
                self._update_stage(job_id, key, "failed", payload.get("summary", "Stage failed."), detail)
