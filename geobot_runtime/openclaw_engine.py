from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .assistant_engine import AssistantEngine
from .config import RuntimeConfig


def extract_result_block(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start_marker = "GEOBOT_RESULT_START"
    end_marker = "GEOBOT_RESULT_END"
    cursor = 0
    last_parsed = None
    while True:
        start_index = text.find(start_marker, cursor)
        if start_index < 0:
            break
        start_index += len(start_marker)
        end_index = text.find(end_marker, start_index)
        if end_index < 0:
            break
        raw = text[start_index:end_index].strip()
        if raw.startswith("```json"):
            raw = raw[len("```json") :].strip()
        elif raw.startswith("```"):
            raw = raw[len("```") :].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        try:
            last_parsed = json.loads(raw)
        except Exception:
            pass
        cursor = end_index + len(end_marker)
    return last_parsed


def build_openclaw_prompt(
    user_message: str,
    export_path: str,
    project_id: str,
    qgis_skill_dir: Optional[Path] = None,
    workflow_mode: str = "qgis_bridge",
    teacher_flow_skill_dir: Optional[Path] = None,
    lesson_plan_path: str = "",
    pptx_path: str = "",
    requires_map: bool = False,
) -> str:
    if workflow_mode == "teacher_flow":
        result_example = json.dumps(
            {
                "status": "success",
                "workflow_type": "teacher_flow",
                "summary": "Completed the teaching workflow.",
                "assistant_message": "已完成教学设计、地图制作与PPT生成。",
                "template_id": "",
                "notes": "The teaching workflow finished successfully.",
                "stages": {
                    "analysis": {"status": "success", "summary": "Parsed the teaching request.", "detail": ""},
                    "design": {"status": "success", "summary": "Prepared the lesson plan.", "detail": ""},
                    "map": {"status": "success" if requires_map else "skipped", "summary": "Prepared the teaching map." if requires_map else "Map generation was not required.", "detail": ""},
                    "presentation": {"status": "success", "summary": "Generated the teaching slides.", "detail": ""},
                },
                "artifacts": {
                    "lesson_plan": {"artifact_type": "lesson_plan", "title": "Lesson Plan", "path": lesson_plan_path},
                    "map_export": {"artifact_type": "map_export", "title": "Teaching Map", "path": export_path if requires_map else ""},
                    "pptx": {"artifact_type": "pptx", "title": "Teaching Slides", "path": pptx_path},
                },
            },
            ensure_ascii=False,
        )
        skill_hint = ""
        if teacher_flow_skill_dir and teacher_flow_skill_dir.exists():
            teacher_skill_file = teacher_flow_skill_dir / "SKILL.md"
            teacher_quick_ref = teacher_flow_skill_dir / "references" / "quick_ref.md"
            skill_hint = (
                f"\nThe teaching workflow skill is available at: {teacher_flow_skill_dir}.\n"
                "Use teacher_flow as the primary orchestration skill for this request.\n"
                f"Before execution, read exactly once:\n- {teacher_skill_file}\n- {teacher_quick_ref}\n"
            )
        if qgis_skill_dir and qgis_skill_dir.exists():
            qgis_skill_file = qgis_skill_dir / "SKILL.md"
            qgis_tools_file = qgis_skill_dir / "references" / "tools.md"
            qgis_client_file = qgis_skill_dir / "scripts" / "qgis_client.py"
            skill_hint += (
                f"The QGIS operator skill is available at: {qgis_skill_dir}.\n"
                f"If the operator stage needs GIS work, read exactly once:\n- {qgis_skill_file}\n- {qgis_tools_file}\n"
                f"Then use the existing client implementation at: {qgis_client_file}\n"
            )
        return (
            "You are the hidden teaching workflow engine behind GeoBot.\n"
            "This is an execution task, not a social conversation.\n"
            "Do not greet, do not introduce yourself, do not ask the user's name, and do not ask what they want to do.\n"
            "Execute the request directly through the teacher_flow workflow.\n"
            "The workflow stages are fixed:\n"
            "- coordinator: parse the teaching request\n"
            "- designer: produce the lesson plan\n"
            "- operator: only if the request needs GIS or maps, call QGIS through qgis-solver\n"
            "- generator: produce the PPT or teaching package\n"
            "Designer and operator may run in parallel, but generator must wait for required prior stages.\n"
            "Do not open unrelated new sessions, and do not end with free-form conversational closing text.\n"
            "The QGIS bridge on port 5555 is a raw length-prefixed TCP socket, not an HTTP endpoint.\n"
            "Never use curl, fetch, Invoke-RestMethod, or ad-hoc HTTP requests against localhost:5555.\n"
            "Never create ad-hoc raw socket scripts, never write temporary socket test files, and never probe port 5555 with custom code if the existing qgis_client skill can handle the task.\n"
            "Do not use netstat, custom socket snippets, or standalone Python socket tests unless GeoBot explicitly asks you to debug the transport.\n"
            "Do not ask the user to open OpenClaw, configure skills, or manually operate QGIS.\n"
            f"The active GeoBot project id is: {project_id}\n"
            f"The lesson plan must be saved to this exact path: {lesson_plan_path}\n"
            f"The PPT must be saved to this exact path: {pptx_path}\n"
            f"The map export path is: {export_path if requires_map else '(leave empty if no map is needed)'}\n"
            f"{skill_hint}"
            "When you use the final machine-readable block, every field must contain a concrete value.\n"
            "Never output placeholder text such as ..., \"...\", <summary>, <path>, TBD, or unknown.\n"
            "All four stage keys must be present in the final result.\n"
            "If the map stage is not required, set stages.map.status to skipped and artifacts.map_export.path to an empty string.\n"
            "When the task is complete, end your reply with exactly one final machine-readable block in this format:\n"
            "GEOBOT_RESULT_START\n"
            f"{result_example}\n"
            "GEOBOT_RESULT_END\n"
            "If the task fails, still return the same shape with status=error and concise stage summaries.\n"
            "User request:\n"
            f"{user_message}"
        )

    result_example = json.dumps(
        {
            "status": "success",
            "summary": "Completed the requested map export.",
            "assistant_message": "Completed the requested map export.",
            "workflow_type": "qgis_bridge",
            "export_path": export_path,
            "template_id": "",
            "notes": "Executed through the QGIS bridge.",
            "stages": {
                "analysis": {"status": "success", "summary": "Parsed the request.", "detail": ""},
                "design": {"status": "skipped", "summary": "Lesson design was not required.", "detail": ""},
                "map": {"status": "success", "summary": "Generated the requested GIS output.", "detail": ""},
                "presentation": {"status": "skipped", "summary": "PPT generation was not required.", "detail": ""},
            },
            "artifacts": {
                "lesson_plan": {"artifact_type": "lesson_plan", "title": "Lesson Plan", "path": ""},
                "map_export": {"artifact_type": "map_export", "title": "Map Export", "path": export_path},
                "pptx": {"artifact_type": "pptx", "title": "Teaching Slides", "path": ""},
            },
        },
        ensure_ascii=False,
    )
    skill_hint = ""
    if qgis_skill_dir and qgis_skill_dir.exists():
        skill_file = qgis_skill_dir / "SKILL.md"
        tools_file = qgis_skill_dir / "references" / "tools.md"
        client_file = qgis_skill_dir / "scripts" / "qgis_client.py"
        skill_hint = (
            f"\nThe QGIS bridge skill is available at: {qgis_skill_dir}.\n"
            f"Before any GIS action, read these files exactly once:\n- {skill_file}\n- {tools_file}\n"
            f"Then use the existing client implementation at: {client_file}\n"
            "Use that skill and client for all GIS and map export work.\n"
        )
    return (
        "You are the hidden execution engine behind GeoBot.\n"
        "This is an execution task, not a social conversation.\n"
        "Do not greet the user, do not introduce yourself, do not ask the user's name, and do not ask what they want to do.\n"
        "Execute the request directly.\n"
        "You must work only through the local QGIS bridge and the currently open QGIS project.\n"
        "Prefer the dedicated teaching templates when they apply:\n"
        "- create_population_distribution_map\n"
        "- create_population_density_map\n"
        "- create_population_migration_map\n"
        "- create_hu_line_comparison_map\n"
        "If a template does not fit, use the lower-level QGIS bridge tools.\n"
        "The QGIS bridge on port 5555 is a raw length-prefixed TCP socket, not an HTTP endpoint.\n"
        "Never use curl, fetch, Invoke-RestMethod, or ad-hoc HTTP requests against localhost:5555.\n"
        "Never create ad-hoc raw socket scripts, never write temporary socket test files, and never probe port 5555 with custom code if the existing qgis_client skill can handle the task.\n"
        "Do not use netstat, custom socket snippets, or standalone Python socket tests unless GeoBot explicitly asks you to debug the transport.\n"
        "Do not ask the user to open OpenClaw, configure skills, or manually operate QGIS.\n"
        f"Always try to export the final map to this exact path: {export_path}\n"
        f"The active GeoBot project id is: {project_id}\n"
        f"{skill_hint}"
        "When you use the final machine-readable block, every field must contain a concrete value.\n"
        "Never output placeholder text such as ..., \"...\", <summary>, <path>, TBD, or unknown.\n"
        f"If you successfully export a map, export_path must be exactly: {export_path}\n"
        "If no teaching template applies, set template_id to an empty string.\n"
        "When the task is complete, end your reply with exactly one final machine-readable block in this format:\n"
        "GEOBOT_RESULT_START\n"
        f"{result_example}\n"
        "GEOBOT_RESULT_END\n"
        "If the task fails, still return the same block with status=error and a concise summary.\n"
        "User request:\n"
        f"{user_message}"
    )


class OpenClawSupervisor:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.gateway_process: Optional[subprocess.Popen] = None

    def health(self) -> Dict[str, Any]:
        payload = self._health_probe()
        payload.setdefault("name", "openclaw")
        payload.setdefault("mode", self.config.openclaw_bridge_mode)
        payload.setdefault("capabilities", ["hidden-automation", "qgis-solver"])
        return payload

    def ensure_ready(self) -> Dict[str, Any]:
        status = self._health_probe()
        if status.get("reachable"):
            return status

        if not self.config.openclaw_gateway_cmd.exists():
            raise RuntimeError(f"OpenClaw gateway launcher not found: {self.config.openclaw_gateway_cmd}")

        self._start_gateway()
        deadline = time.time() + 15
        while time.time() < deadline:
            status = self._health_probe()
            if status.get("reachable"):
                status["started_by_runtime"] = True
                return status
            time.sleep(1)
        raise RuntimeError("OpenClaw gateway did not become reachable after startup")

    def _health_probe(self) -> Dict[str, Any]:
        if not self.config.openclaw_gateway_url:
            return {
                "configured": False,
                "reachable": False,
                "message": "OpenClaw gateway URL is not configured",
            }

        try:
            request = urllib.request.Request(
                f"{self.config.openclaw_gateway_url.rstrip('/')}/health",
                headers={"Authorization": f"Bearer {self.config.private_openclaw_token}"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return {
                "configured": True,
                "reachable": True,
                "gateway_url": self.config.openclaw_gateway_url,
                "response": payload,
            }
        except Exception as exc:
            return {
                "configured": True,
                "reachable": False,
                "gateway_url": self.config.openclaw_gateway_url,
                "message": str(exc),
            }

    def _start_gateway(self) -> None:
        command = ["cmd", "/c", str(self.config.openclaw_gateway_cmd)]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.gateway_process = subprocess.Popen(
            command,
            cwd=str(self.config.openclaw_home),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )


class OpenClawBridge:
    def __init__(self, config: RuntimeConfig):
        self.config = config

    def health(self) -> Dict[str, Any]:
        desktop_bridge = self._probe_desktop_bridge()
        return {
            "configured": bool(desktop_bridge.get("reachable") or (self.config.electron_executable and self.config.openclaw_helper_script.exists())),
            "reachable": desktop_bridge.get("reachable", False),
            "desktop_bridge": desktop_bridge,
            "electron_executable": self.config.electron_executable,
            "helper_script": str(self.config.openclaw_helper_script),
        }

    def chat(
        self,
        project_id: str,
        message: str,
        export_path: str,
        requires_export: bool = False,
        workflow_mode: str = "qgis_bridge",
        lesson_plan_path: str = "",
        pptx_path: str = "",
        requires_map: bool = False,
    ) -> Dict[str, Any]:
        desktop_bridge = self._probe_desktop_bridge()
        if desktop_bridge.get("reachable"):
            return self._chat_via_desktop_bridge(
                project_id=project_id,
                message=message,
                export_path=export_path,
                requires_export=requires_export,
                workflow_mode=workflow_mode,
                lesson_plan_path=lesson_plan_path,
                pptx_path=pptx_path,
                requires_map=requires_map,
            )

        if not self.config.electron_executable:
            raise RuntimeError("Electron runtime not found. Install desktop dependencies before using the OpenClaw bridge.")
        if not self.config.openclaw_helper_script.exists():
            raise RuntimeError(f"OpenClaw bridge helper not found: {self.config.openclaw_helper_script}")

        prompt = build_openclaw_prompt(
            user_message=message,
            export_path=export_path,
            project_id=project_id,
            qgis_skill_dir=self.config.qgis_solver_skill_dir,
            workflow_mode=workflow_mode,
            teacher_flow_skill_dir=self.config.teacher_flow_skill_dir,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
        )
        request_payload = {
            "gatewayUrl": self.config.openclaw_gateway_url,
            "chatUrl": self.config.openclaw_chat_url,
            "gatewayToken": self.config.private_openclaw_token,
            "prompt": prompt,
            "projectId": project_id,
            "exportPath": export_path,
            "requiresExport": requires_export,
            "workflowMode": workflow_mode,
            "requiresMap": requires_map,
            "timeoutMs": self.config.openclaw_bridge_timeout_ms,
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as handle:
            handle.write(json.dumps(request_payload, ensure_ascii=False, indent=2))
            request_path = Path(handle.name)

        try:
            process = subprocess.run(
                [self.config.electron_executable, str(self.config.openclaw_helper_script), "--request", str(request_path)],
                cwd=str(self.config.project_root),
                capture_output=True,
                text=True,
                timeout=max(30, int(self.config.openclaw_bridge_timeout_ms / 1000) + 15),
                check=False,
            )
        finally:
            try:
                request_path.unlink()
            except OSError:
                pass

        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()
        if process.returncode != 0:
            raise RuntimeError(stderr or stdout or "OpenClaw bridge helper failed")

        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError("OpenClaw bridge helper returned no output")
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse OpenClaw bridge output: {exc}") from exc

        if payload.get("status") != "success":
            raise RuntimeError(payload.get("message") or payload.get("summary") or "OpenClaw bridge returned an error")
        return payload

    def _probe_desktop_bridge(self) -> Dict[str, Any]:
        if not self.config.desktop_automation_bridge_url:
            return {"reachable": False}
        try:
            with urllib.request.urlopen(f"{self.config.desktop_automation_bridge_url.rstrip('/')}/health", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return {
                "reachable": payload.get("status") == "ok",
                "url": self.config.desktop_automation_bridge_url,
                "response": payload,
            }
        except Exception as exc:
            return {
                "reachable": False,
                "url": self.config.desktop_automation_bridge_url,
                "message": str(exc),
            }

    def _chat_via_desktop_bridge(
        self,
        project_id: str,
        message: str,
        export_path: str,
        requires_export: bool = False,
        workflow_mode: str = "qgis_bridge",
        lesson_plan_path: str = "",
        pptx_path: str = "",
        requires_map: bool = False,
    ) -> Dict[str, Any]:
        prompt = build_openclaw_prompt(
            user_message=message,
            export_path=export_path,
            project_id=project_id,
            qgis_skill_dir=self.config.qgis_solver_skill_dir,
            workflow_mode=workflow_mode,
            teacher_flow_skill_dir=self.config.teacher_flow_skill_dir,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
        )
        request_payload = {
            "gatewayUrl": self.config.openclaw_gateway_url,
            "chatUrl": self.config.openclaw_chat_url,
            "gatewayToken": self.config.private_openclaw_token,
            "prompt": prompt,
            "projectId": project_id,
            "exportPath": export_path,
            "requiresExport": requires_export,
            "workflowMode": workflow_mode,
            "requiresMap": requires_map,
            "timeoutMs": self.config.openclaw_bridge_timeout_ms,
        }
        request = urllib.request.Request(
            f"{self.config.desktop_automation_bridge_url.rstrip('/')}/openclaw/chat",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(30, int(self.config.openclaw_bridge_timeout_ms / 1000) + 15)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(detail or f"Desktop automation bridge returned HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"Desktop automation bridge request failed: {exc}") from exc

        if payload.get("status") != "success":
            raise RuntimeError(payload.get("message") or payload.get("summary") or "Desktop automation bridge returned an error")
        return payload


class OpenClawEngine(AssistantEngine):
    name = "openclaw"

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.mode = config.openclaw_bridge_mode
        self.supervisor = OpenClawSupervisor(config)
        self.bridge = OpenClawBridge(config)

    def health(self) -> Dict[str, Any]:
        status = self.supervisor.health()
        bridge_status = self.bridge.health()
        bridge_ready = bridge_status.get("reachable", False) or bridge_status.get("configured", False)
        status.update(
            {
                "name": self.name,
                "mode": self.mode,
                "configured": status.get("configured", False) and bridge_ready,
                "reachable": status.get("reachable", False) and bridge_ready,
                "bridge": bridge_status,
                "capabilities": ["hidden-automation", "qgis-solver", "fallback-ready"],
            }
        )
        if status.get("reachable") and not bridge_status.get("configured", False):
            status["message"] = "OpenClaw gateway is reachable, but the hidden automation bridge is not configured"
        return status

    def chat(self, project_id: str, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context = context or {}
        export_path = context.get("export_path")
        requires_export = bool(context.get("requires_export", False))
        workflow_mode = context.get("workflow_mode", "qgis_bridge")
        lesson_plan_path = context.get("lesson_plan_path", "")
        pptx_path = context.get("pptx_path", "")
        requires_map = bool(context.get("requires_map", False))
        if not export_path:
            raise ValueError("OpenClaw chat requires an export_path in context")

        self.supervisor.ensure_ready()
        bridge_result = self.bridge.chat(
            project_id=project_id,
            message=message,
            export_path=export_path,
            requires_export=requires_export,
            workflow_mode=workflow_mode,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
        )

        resolved_export_path = bridge_result["export_path"] if "export_path" in bridge_result else export_path

        result = {
            "status": "success",
            "assistant_message": bridge_result.get("summary") or bridge_result.get("assistant_message") or "OpenClaw completed the task.",
            "summary": bridge_result.get("summary") or bridge_result.get("assistant_message") or "",
            "export_path": resolved_export_path,
            "template_id": bridge_result.get("template_id"),
            "notes": bridge_result.get("notes", ""),
            "workflow_type": bridge_result.get("workflow_type") or workflow_mode,
            "stages": bridge_result.get("stages", {}),
            "artifacts": bridge_result.get("artifacts", {}),
            "engine": {
                "name": self.name,
                "mode": self.mode,
            },
            "steps": bridge_result.get("steps", []),
            "raw": bridge_result,
        }
        return result
