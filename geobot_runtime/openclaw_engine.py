from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from .assistant_engine import AssistantEngine
from .config import RuntimeConfig
from .style_intent import extract_requested_color, is_direct_style_request


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
def _default_lesson_ppt_artifacts(
    lesson_plan_path: str,
    pptx_path: str,
) -> Dict[str, Dict[str, Any]]:
    base_dir = str(Path(lesson_plan_path).parent) if lesson_plan_path else ""
    return {
        "lesson_plan": {
            "artifact_type": "lesson_plan",
            "title": "Unit Teaching Design",
            "path": lesson_plan_path,
        },
        "lesson_plan_docx": {
            "artifact_type": "docx",
            "title": "Unit Teaching Design (Word)",
            "path": str(Path(lesson_plan_path).with_suffix(".docx")) if lesson_plan_path else "",
        },
        "guidance": {
            "artifact_type": "markdown",
            "title": "Learning Guidance",
            "path": str(Path(base_dir) / "population_guidance.md") if base_dir else "",
        },
        "guidance_docx": {
            "artifact_type": "docx",
            "title": "Learning Guidance (Word)",
            "path": str(Path(base_dir) / "population_guidance.docx") if base_dir else "",
        },
        "homework": {
            "artifact_type": "markdown",
            "title": "Homework Package",
            "path": str(Path(base_dir) / "population_homework.md") if base_dir else "",
        },
        "homework_docx": {
            "artifact_type": "docx",
            "title": "Homework Package (Word)",
            "path": str(Path(base_dir) / "population_homework.docx") if base_dir else "",
        },
        "review": {
            "artifact_type": "markdown",
            "title": "Review Package",
            "path": str(Path(base_dir) / "population_review.md") if base_dir else "",
        },
        "review_docx": {
            "artifact_type": "docx",
            "title": "Review Package (Word)",
            "path": str(Path(base_dir) / "population_review.docx") if base_dir else "",
        },
        "pptx": {
            "artifact_type": "pptx",
            "title": "Teaching Slides",
            "path": pptx_path,
        },
    }


def _normalize_expected_artifacts(
    expected_artifacts: Optional[Dict[str, Dict[str, Any]]],
    lesson_plan_path: str,
    export_path: str,
    pptx_path: str,
    include_map: bool,
) -> Dict[str, Dict[str, Any]]:
    artifacts = dict(expected_artifacts or {})
    if not artifacts:
        artifacts = _default_lesson_ppt_artifacts(
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
        )
    artifacts.setdefault(
        "lesson_plan",
        {"artifact_type": "lesson_plan", "title": "Unit Teaching Design", "path": lesson_plan_path},
    )
    artifacts.setdefault(
        "pptx",
        {"artifact_type": "pptx", "title": "Teaching Slides", "path": pptx_path},
    )
    if include_map:
        artifacts.setdefault(
            "map_export",
            {"artifact_type": "map_export", "title": "Map Export", "path": export_path},
        )
    else:
        artifacts.pop("map_export", None)
    return artifacts


def build_direct_style_hint(
    user_message: str,
    workflow_mode: str,
    suggested_template: str = "",
    requires_export: bool = False,
) -> str:
    normalized_workflow_mode = (workflow_mode or "").strip().lower()
    if normalized_workflow_mode != "qgis_only":
        return ""
    if not is_direct_style_request(
        user_message,
        suggested_template=suggested_template,
        requires_export=requires_export,
    ):
        return ""

    requested_color = extract_requested_color(user_message) or ""
    color_clause = f"The requested color must remain exactly {requested_color}.\n" if requested_color else ""
    return (
        "\nThis specific request is a direct current-project style edit, not a thematic map.\n"
        "Do not use apply_graduated_renderer(), create_population_distribution_map(), create_population_density_map(), "
        "create_population_migration_map(), create_hu_line_comparison_map(), auto_layout(), or export_map() unless the user explicitly asks for thematic composition or export.\n"
        "Use set_layer_style() or set_style() on the resolved target layer.\n"
        "If the target is a polygon or point layer, prefer fill_color for the primary symbol color. "
        "If the target is a line layer, prefer line_color.\n"
        f"{color_clause}"
        "A ramp-based or blue result is incorrect for this request.\n"
    )


def build_openclaw_prompt(
    user_message: str,
    export_path: str,
    project_id: str,
    request_id: str = "",
    qgis_skill_dir: Optional[Path] = None,
    workflow_mode: str = "qgis_bridge",
    teacher_flow_skill_dir: Optional[Path] = None,
    ppt_studio_skill_dir: Optional[Path] = None,
    lesson_plan_path: str = "",
    pptx_path: str = "",
    requires_map: bool = False,
    requires_export: bool = False,
    knowledge_root: str = "",
    dataset_manifest_path: str = "",
    showcase_mode: str = "",
    expected_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
    population_preflight: Optional[Dict[str, Any]] = None,
    knowledge_bundle: Optional[Dict[str, Any]] = None,
    package_profile: Optional[Dict[str, Any]] = None,
    suggested_template: str = "",
    fallback_template: str = "",
) -> str:
    normalized_workflow_mode = (workflow_mode or "qgis_bridge").lower()
    if normalized_workflow_mode in {"teacher_flow", "full_flow", "lesson_ppt"}:
        normalized_artifacts = _normalize_expected_artifacts(
            expected_artifacts=expected_artifacts,
            lesson_plan_path=lesson_plan_path,
            export_path=export_path,
            pptx_path=pptx_path,
            include_map=False,
        )
        skill_hint = ""
        if teacher_flow_skill_dir and teacher_flow_skill_dir.exists():
            teacher_skill_file = teacher_flow_skill_dir / "SKILL.md"
            teacher_quick_ref = teacher_flow_skill_dir / "references" / "quick_ref.md"
            skill_hint += (
                f"\nThe teaching workflow skill is available at: {teacher_flow_skill_dir}.\n"
                "Use it only for lesson planning, teaching structure, and assessment design.\n"
                f"Before execution, read exactly once:\n- {teacher_skill_file}\n- {teacher_quick_ref}\n"
            )

        showcase_hint = ""
        if showcase_mode == "population_unit":
            artifact_text = json.dumps(normalized_artifacts, ensure_ascii=False, indent=2)
            knowledge_text = json.dumps(knowledge_bundle or {}, ensure_ascii=False, indent=2)
            package_profile_text = json.dumps(package_profile or {}, ensure_ascii=False, indent=2)
            showcase_hint = (
                "\nThis request is in showcase_mode=population_unit.\n"
                "Treat it as a lesson design and presentation workflow for the high-school Geography population unit.\n"
                "Delivery goals are fixed:\n"
                "- complete multi-file teaching package driven by a declared package contract\n"
                "- flagship storyline centered on Hu Huanyong line + contemporary population migration\n"
                "- presentation-ready slide contract for later local PPT generation\n"
                "- include a dedicated section titled `建议 QGIS 操作` inside the main teaching design\n"
                f"Population knowledge root: {knowledge_root}\n"
                f"Dataset manifest path: {dataset_manifest_path}\n"
                "Use the population package profile below as the recommended contract baseline before declaring the final package_contract:\n"
                f"{package_profile_text}\n"
                "Use the structured knowledge bundle below as the primary source base before improvising any content:\n"
                f"{knowledge_text}\n"
                "GeoBot will render these local output files after your structured result returns:\n"
                f"{artifact_text}\n"
                "Recommend suitable QGIS templates and datasets in the lesson package, but do not execute them.\n"
            )

        return (
            "You are the hidden lesson design engine behind GeoBot.\n"
            "This is an execution task, not a social conversation.\n"
            "Do not greet, do not introduce yourself, do not ask the user's name, and do not ask what they want to do.\n"
            "Execute the request directly through the lesson_ppt workflow.\n"
            "This mode is strictly separated from QGIS execution.\n"
            "Do not call QGIS, do not use qgis-solver, do not read current QGIS layers, and do not generate real map artifacts.\n"
            "Do not read ppt-studio, do not write temporary scripts, do not run Node or PowerShell, do not generate PPT/PDF files, and do not save any final output files yourself.\n"
            "Your only responsibility is to return one structured lesson blueprint that GeoBot can render locally into Markdown, DOCX, and PPTX.\n"
            "Do not open unrelated new sessions, and do not end with free-form conversational closing text.\n"
            "Do not ask the user to manually operate QGIS.\n"
            "Do not return actual artifact paths. GeoBot will assign local paths after your blueprint returns.\n"
            f"The active GeoBot project id is: {project_id}\n"
            f"The current GeoBot request_id is: {request_id}\n"
            f"{skill_hint}"
            f"{showcase_hint}"
            "Return exactly one GEOBOT_RESULT block containing:\n"
            "- top-level request_id, status, workflow_type, summary, assistant_message, template_id, notes, and stages\n"
            "- package_contract with package_type, required_sections, module_requirements, document_outputs, presentation_requirements, and completion_checks\n"
            "- lesson_payload with unit_meta, curriculum_requirements, discipline_literacy_targets, material_analysis, student_analysis, unit_objectives, key_and_difficult_points, assessment_design, modules, guidance_pack, homework_pack, review_pack, flagship_storyline, qgis_guidance, and project_advantages\n"
            "- slide_contract with one item per slide\n"
            "First declare the package_contract, then make lesson_payload and slide_contract satisfy that contract.\n"
            "Do not omit package_contract.\n"
            "If the available knowledge only supports a reduced package, you may reduce the package scope, but you must explicitly declare that reduced scope in package_contract and keep status=success only when the returned package fully satisfies it.\n"
            "Each modules item must contain theme_id, title, focus, periods, core_questions, teaching_objectives, evidence, teaching_process, activities, evaluation_points, summary, board_plan, homework, and reflection.\n"
            "Each teaching_process item must contain stage, duration, teacher_activity, student_activity, goal, and assessment.\n"
            "guidance_pack must include preclass_tasks, inclass_inquiry_tasks, method_guidance, and common_pitfalls.\n"
            "homework_pack must include basic_questions, advanced_questions, and integrated_questions. Each question needs prompt, answer, and analysis.\n"
            "review_pack must include knowledge_checklist, high_frequency_judgments, common_mistakes, example_questions, and review_advice. Each example question needs prompt, answer, and analysis.\n"
            "project_advantages must explain what GeoBot can do that ordinary teachers usually cannot do.\n"
            "lesson_payload.qgis_guidance must list recommended_layers, recommended_templates, key_fields, suggested_exports, and notes.\n"
            "package_contract.module_requirements must declare how many modules are required and any expected module ids or recommended module roles.\n"
            "package_contract.document_outputs must declare whether guidance, homework, and review documents are required.\n"
            "package_contract.presentation_requirements must declare whether slides are required, the minimum slide count, and any required page families.\n"
            "Each slide_contract item must contain slide_id, title, subtitle, page_goal, core_message, evidence_type, recommended_visual, speaker_note, supporting_points, and may include expected_page_family plus visual data arrays.\n"
            "When you use the final machine-readable block, every field must contain a concrete value.\n"
            "Never output placeholder text such as ..., \"...\", <summary>, <path>, TBD, or unknown.\n"
            "All four stage keys must be present in the final result.\n"
            "The map stage must be skipped and the presentation stage must describe local PPT preparation, not real PPT generation.\n"
            "The final JSON request_id must exactly match the GeoBot request_id shown above.\n"
            "When the task is complete, end your reply with exactly one final machine-readable block in this format:\n"
            "GEOBOT_RESULT_START\n"
            "{ valid JSON object with every required field listed above }\n"
            "GEOBOT_RESULT_END\n"
            "If the task fails, still return the same shape with status=error and concise stage summaries.\n"
            "User request:\n"
            f"{user_message}"
        )

    qgis_workflow_type = "qgis_only" if normalized_workflow_mode == "qgis_only" else "qgis_bridge"
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
    template_hint = ""
    if suggested_template:
        template_hint += f"\nIf the request clearly matches a dedicated thematic template, the first candidate is: {suggested_template}.\n"
    if fallback_template and fallback_template != suggested_template:
        template_hint += f"Fallback template hint: {fallback_template}.\n"
    direct_style_hint = build_direct_style_hint(
        user_message=user_message,
        workflow_mode=normalized_workflow_mode,
        suggested_template=suggested_template,
        requires_export=requires_export,
    )
    export_rule = (
        f"The user explicitly requested an export. If you generate a final export, export_path must be exactly: {export_path}\n"
        if requires_export and export_path
        else "This task does not require a file export. Leave export_path as an empty string and do not fabricate output paths.\n"
    )
    return (
        "You are the hidden professional QGIS execution assistant behind GeoBot.\n"
        "This is an execution task, not a social conversation.\n"
        "Do not greet the user, do not introduce yourself, do not ask the user's name, and do not ask what they want to do.\n"
        "Execute the request directly against the currently open QGIS project.\n"
        "This mode is strictly separated from lesson design and PPT generation.\n"
        "Do not switch to lesson_ppt, teacher_flow, or any teaching-design workflow.\n"
        "You are a capable, extensible GIS operator that can inspect layers, prepare data, run analysis, style layers, compose layouts, and export results through the existing QGIS tool interface.\n"
        "You must work only through the local QGIS bridge, qgis-solver skill, and the currently open QGIS project.\n"
        "Start by calling get_layers() to inspect current layers, including fields, geometry_type, is_visible, and is_active.\n"
        "Interpret layer targets safely.\n"
        "If the user provides an explicit layer name or layer id, use that exact target.\n"
        "If the user says '当前图层', 'the current layer', or similar wording without naming a layer, prefer the active layer where is_active=true.\n"
        "Only fall back to visible operable layers where is_visible=true when the request clearly implies a batch action across visible layers.\n"
        "If the target is ambiguous and acting would risk modifying the wrong layer, do not guess. Return status=error with a concise Chinese reason.\n"
        "Choose tools by intent.\n"
        "For direct current-project edits, prefer targeted low-level tools before thematic templates.\n"
        "Prefer set_style() or set_layer_style() for single-symbol color, fill, outline, opacity, or width changes.\n"
        "Prefer set_layer_labels() for label changes, set_layer_visibility() for show/hide, set_active_layer() plus zoom_to_layer() for selection and focus, move_layer() for ordering changes, and query_attributes() only when you need record inspection.\n"
        "Prefer dedicated GIS tools such as prepare_layer(), filter_layer(), join_attributes(), create_centroids(), create_connection_lines(), apply_graduated_renderer(), create_heatmap(), create_flow_arrows(), terrain tools, and run_population_attraction_model() before falling back to run_algorithm().\n"
        "Use cartography templates only when the user clearly requests a thematic map product.\n"
        "Use auto_layout(), customize_layout_legend(), embed_chart(), and export_map() only when the user clearly requests map composition or export.\n"
        "Use run_python_code() only as an expert fallback when the existing bridge tools cannot complete the task safely.\n"
        "Honor the user's requested parameters and the current QGIS project context.\n"
        "Never invent styles, colors, field names, classification breaks, layer names, output paths, or template ids unless they are clearly implied by the request or discovered from the current project or tool metadata.\n"
        "If the user specifies a color, numeric threshold, class count, output format, or other concrete parameter, preserve that value exactly after normalizing it to a QGIS-compatible form.\n"
        "Do not produce lesson plans or PPT outputs in this mode.\n"
        "The QGIS bridge on port 5555 is a raw length-prefixed TCP socket, not an HTTP endpoint.\n"
        "Never use curl, fetch, Invoke-RestMethod, or ad-hoc HTTP requests against localhost:5555.\n"
        "Never create ad-hoc raw socket scripts, never write temporary socket test files, and never probe port 5555 with custom code if the existing qgis_client skill can handle the task.\n"
        "Do not use netstat, custom socket snippets, or standalone Python socket tests unless GeoBot explicitly asks you to debug the transport.\n"
        "Do not ask the user to open OpenClaw, configure skills, or manually operate QGIS.\n"
        "All human-readable fields in the final result must be written in Simplified Chinese.\n"
        f"The active GeoBot project id is: {project_id}\n"
        f"The current GeoBot request_id is: {request_id}\n"
        f"{skill_hint}"
        f"{template_hint}"
        f"{direct_style_hint}"
        f"{export_rule}"
        "Do not claim success from intent alone. Success requires execution plus post-action verification.\n"
        "For style edits, verify the observed post-action state with get_layer_style() before declaring success.\n"
        "For non-style operations, verify with the most relevant read-back tool or returned bridge evidence available for that operation, and record that evidence in the verification object.\n"
        "The verification object uses legacy field names. Store the expected post-action state in expected_style and the observed post-action state in observed_style even when the task is not a pure style change.\n"
        "When you use the final machine-readable block, every field must contain a concrete value.\n"
        "Never output placeholder text such as ..., \"...\", <summary>, <path>, TBD, or unknown.\n"
        "If you do not use a dedicated template, set template_id to an empty string.\n"
        "The final JSON object must contain these top-level keys: request_id, status, summary, assistant_message, workflow_type, export_path, template_id, notes, stages, artifacts, and verification.\n"
        "The stages object must contain analysis, design, map, and presentation. Each stage must contain status, summary, and detail.\n"
        "The verification object must contain status, checked_layers, expected_style, observed_style, and mismatches.\n"
        "When no file export is required, export_path must be an empty string and artifacts may be an empty object.\n"
        f"workflow_type must be exactly: {qgis_workflow_type}\n"
        "The final JSON request_id must exactly match the GeoBot request_id shown above.\n"
        "For qgis_only, only return status=success when verification.status=verified.\n"
        "When the task is complete, end your reply with exactly one final machine-readable block using the markers GEOBOT_RESULT_START and GEOBOT_RESULT_END.\n"
        "Do not echo the prompt, do not repeat the schema instructions, and do not include any extra GEOBOT_RESULT markers before the final answer.\n"
        "If the task fails, still return the same structure with status=error and a concise Chinese summary.\n"
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
        request_id: str,
        requires_export: bool = False,
        workflow_mode: str = "qgis_bridge",
        lesson_plan_path: str = "",
        pptx_path: str = "",
        requires_map: bool = False,
        knowledge_root: str = "",
        dataset_manifest_path: str = "",
        showcase_mode: str = "",
        expected_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
        population_preflight: Optional[Dict[str, Any]] = None,
        knowledge_bundle: Optional[Dict[str, Any]] = None,
        package_profile: Optional[Dict[str, Any]] = None,
        suggested_template: str = "",
        fallback_template: str = "",
    ) -> Dict[str, Any]:
        desktop_bridge = self._probe_desktop_bridge()
        if desktop_bridge.get("reachable"):
            return self._chat_via_desktop_bridge(
                project_id=project_id,
                message=message,
                export_path=export_path,
                request_id=request_id,
                requires_export=requires_export,
                workflow_mode=workflow_mode,
                lesson_plan_path=lesson_plan_path,
                pptx_path=pptx_path,
                requires_map=requires_map,
                knowledge_root=knowledge_root,
                dataset_manifest_path=dataset_manifest_path,
                showcase_mode=showcase_mode,
                expected_artifacts=expected_artifacts,
                population_preflight=population_preflight,
                knowledge_bundle=knowledge_bundle,
                package_profile=package_profile,
                suggested_template=suggested_template,
                fallback_template=fallback_template,
            )

        if not self.config.electron_executable:
            raise RuntimeError("Electron runtime not found. Install desktop dependencies before using the OpenClaw bridge.")
        if not self.config.openclaw_helper_script.exists():
            raise RuntimeError(f"OpenClaw bridge helper not found: {self.config.openclaw_helper_script}")

        prompt = build_openclaw_prompt(
            user_message=message,
            export_path=export_path,
            project_id=project_id,
            request_id=request_id,
            qgis_skill_dir=self.config.qgis_solver_skill_dir,
            workflow_mode=workflow_mode,
            teacher_flow_skill_dir=self.config.teacher_flow_skill_dir,
            ppt_studio_skill_dir=self.config.ppt_studio_skill_dir,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
            requires_export=requires_export,
            knowledge_root=knowledge_root,
            dataset_manifest_path=dataset_manifest_path,
            showcase_mode=showcase_mode,
            expected_artifacts=expected_artifacts,
            population_preflight=population_preflight,
            knowledge_bundle=knowledge_bundle,
            package_profile=package_profile,
            suggested_template=suggested_template,
            fallback_template=fallback_template,
        )
        request_payload = {
            "gatewayUrl": self.config.openclaw_gateway_url,
            "chatUrl": self.config.openclaw_chat_url,
            "gatewayToken": self.config.private_openclaw_token,
            "prompt": prompt,
            "projectId": project_id,
            "requestId": request_id,
            "exportPath": export_path,
            "lessonPlanPath": lesson_plan_path,
            "pptxPath": pptx_path,
            "requiresExport": requires_export,
            "workflowMode": workflow_mode,
            "requiresMap": requires_map,
            "showcaseMode": showcase_mode,
            "timeoutMs": self.config.openclaw_bridge_timeout_ms,
            "forceNewSession": True,
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
        request_id: str,
        requires_export: bool = False,
        workflow_mode: str = "qgis_bridge",
        lesson_plan_path: str = "",
        pptx_path: str = "",
        requires_map: bool = False,
        knowledge_root: str = "",
        dataset_manifest_path: str = "",
        showcase_mode: str = "",
        expected_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
        population_preflight: Optional[Dict[str, Any]] = None,
        knowledge_bundle: Optional[Dict[str, Any]] = None,
        package_profile: Optional[Dict[str, Any]] = None,
        suggested_template: str = "",
        fallback_template: str = "",
    ) -> Dict[str, Any]:
        prompt = build_openclaw_prompt(
            user_message=message,
            export_path=export_path,
            project_id=project_id,
            request_id=request_id,
            qgis_skill_dir=self.config.qgis_solver_skill_dir,
            workflow_mode=workflow_mode,
            teacher_flow_skill_dir=self.config.teacher_flow_skill_dir,
            ppt_studio_skill_dir=self.config.ppt_studio_skill_dir,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
            requires_export=requires_export,
            knowledge_root=knowledge_root,
            dataset_manifest_path=dataset_manifest_path,
            showcase_mode=showcase_mode,
            expected_artifacts=expected_artifacts,
            population_preflight=population_preflight,
            knowledge_bundle=knowledge_bundle,
            package_profile=package_profile,
            suggested_template=suggested_template,
            fallback_template=fallback_template,
        )
        request_payload = {
            "gatewayUrl": self.config.openclaw_gateway_url,
            "chatUrl": self.config.openclaw_chat_url,
            "gatewayToken": self.config.private_openclaw_token,
            "prompt": prompt,
            "projectId": project_id,
            "requestId": request_id,
            "exportPath": export_path,
            "lessonPlanPath": lesson_plan_path,
            "pptxPath": pptx_path,
            "requiresExport": requires_export,
            "workflowMode": workflow_mode,
            "requiresMap": requires_map,
            "showcaseMode": showcase_mode,
            "timeoutMs": self.config.openclaw_bridge_timeout_ms,
            "forceNewSession": True,
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
        knowledge_root = context.get("knowledge_root", "")
        dataset_manifest_path = context.get("dataset_manifest_path", "")
        showcase_mode = context.get("showcase_mode", "")
        expected_artifacts = context.get("expected_artifacts", {})
        population_preflight = context.get("population_preflight", {})
        knowledge_bundle = context.get("knowledge_bundle", {})
        package_profile = context.get("package_profile", {})
        suggested_template = context.get("suggested_template", "")
        fallback_template = context.get("fallback_template", "")
        request_id = context.get("request_id") or f"req_{uuid4().hex}"
        if requires_export and not export_path:
            raise ValueError("OpenClaw chat requires an export_path when requires_export is enabled")

        self.supervisor.ensure_ready()
        bridge_result = self.bridge.chat(
            project_id=project_id,
            message=message,
            export_path=export_path,
            request_id=request_id,
            requires_export=requires_export,
            workflow_mode=workflow_mode,
            lesson_plan_path=lesson_plan_path,
            pptx_path=pptx_path,
            requires_map=requires_map,
            knowledge_root=knowledge_root,
            dataset_manifest_path=dataset_manifest_path,
            showcase_mode=showcase_mode,
            expected_artifacts=expected_artifacts,
            population_preflight=population_preflight,
            knowledge_bundle=knowledge_bundle,
            package_profile=package_profile,
            suggested_template=suggested_template,
            fallback_template=fallback_template,
        )

        resolved_export_path = bridge_result["export_path"] if "export_path" in bridge_result else export_path

        result = {
            "status": bridge_result.get("status", "success"),
            "request_id": bridge_result.get("request_id", request_id),
            "assistant_message": bridge_result.get("assistant_message") or bridge_result.get("summary") or "任务已完成。",
            "summary": bridge_result.get("summary") or bridge_result.get("assistant_message") or "任务已完成。",
            "export_path": resolved_export_path,
            "template_id": bridge_result.get("template_id"),
            "notes": bridge_result.get("notes", ""),
            "workflow_type": bridge_result.get("workflow_type") or workflow_mode,
            "stages": bridge_result.get("stages", {}),
            "artifacts": bridge_result.get("artifacts", {}),
            "verification": bridge_result.get("verification", {}),
            "engine": {
                "name": self.name,
                "mode": self.mode,
            },
            "steps": bridge_result.get("steps", []),
            "showcase_mode": bridge_result.get("showcase_mode") or showcase_mode,
            "lesson_payload": bridge_result.get("lesson_payload"),
            "slide_contract": bridge_result.get("slide_contract"),
            "raw": bridge_result,
        }
        return result
