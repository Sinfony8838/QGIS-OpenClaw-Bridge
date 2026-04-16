from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List
from xml.sax.saxutils import escape


DEFAULT_PRESENTATION_STYLE = "data_analysis"
STYLE_REGISTRY_RELATIVE_PATH = Path("assets") / "design_system" / "registries" / "style_families.json"
PPT_GENERATOR_RELATIVE_PATH = Path("scripts") / "design_system" / "generate_design_system_deck.js"

DISCIPLINE_TARGET_KEYS = (
    "human_earth_coordination",
    "regional_cognition",
    "comprehensive_thinking",
    "geographical_practice",
)
OBJECTIVE_KEYS = (
    "knowledge_and_skills",
    "process_and_methods",
    "values",
)
POINT_KEYS = (
    "key_points",
    "difficult_points",
)
ASSESSMENT_KEYS = (
    "formative",
    "summative",
)
QGIS_GUIDANCE_KEYS = (
    "recommended_layers",
    "recommended_templates",
    "key_fields",
    "suggested_exports",
    "notes",
)
PROJECT_ADVANTAGE_KEYS = (
    "capabilities",
    "difference_from_normal_teaching",
    "showcase_tips",
)
GUIDANCE_PACK_KEYS = (
    "preclass_tasks",
    "inclass_inquiry_tasks",
    "method_guidance",
    "common_pitfalls",
)
DOCUMENT_OUTPUT_KEYS = (
    "lesson_plan",
    "guidance",
    "homework",
    "review",
)
THEME_REQUIRED_KEYS = (
    "theme_id",
    "title",
    "focus",
    "periods",
)
REQUIRED_SLIDE_KEYS = (
    "slide_id",
    "title",
    "subtitle",
    "page_goal",
    "core_message",
    "evidence_type",
    "recommended_visual",
    "speaker_note",
    "supporting_points",
)
OPTIONAL_SLIDE_LIST_KEYS = (
    "left_bullets",
    "right_bullets",
    "context_bullets",
    "action_bullets",
)
PACKAGE_CONTRACT_KEYS = (
    "package_type",
    "required_sections",
    "module_requirements",
    "document_outputs",
    "presentation_requirements",
    "completion_checks",
)


def load_presentation_styles(ppt_studio_dir: Path) -> List[Dict[str, Any]]:
    registry_path = Path(ppt_studio_dir) / STYLE_REGISTRY_RELATIVE_PATH
    if not registry_path.exists():
        return [{"id": DEFAULT_PRESENTATION_STYLE, "label": "data_analysis", "theme_id": DEFAULT_PRESENTATION_STYLE}]
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    styles: List[Dict[str, Any]] = []
    for item in payload.get("style_families", []):
        style_id = str(item.get("id", "")).strip()
        if not style_id:
            continue
        styles.append(
            {
                "id": style_id,
                "label": str(item.get("label") or item.get("name") or style_id),
                "theme_id": str(item.get("theme_id", "")),
                "description": str(item.get("description", "")),
            }
        )
    if not styles:
        styles.append({"id": DEFAULT_PRESENTATION_STYLE, "label": "data_analysis", "theme_id": DEFAULT_PRESENTATION_STYLE})
    return styles


def resolve_presentation_style(requested_style: str, ppt_studio_dir: Path) -> str:
    styles = load_presentation_styles(ppt_studio_dir)
    style_ids = {item["id"] for item in styles}
    if requested_style in style_ids:
        return requested_style
    return DEFAULT_PRESENTATION_STYLE if DEFAULT_PRESENTATION_STYLE in style_ids else styles[0]["id"]


def validate_lesson_blueprint(payload: Dict[str, Any]) -> Dict[str, Any]:
    lesson_payload = payload.get("lesson_payload")
    if not isinstance(lesson_payload, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.")
    package_contract = payload.get("package_contract")
    if "unit_meta" not in lesson_payload:
        lesson_payload = _upgrade_legacy_lesson_payload(lesson_payload)
        package_contract = package_contract or _build_minimal_package_contract(lesson_payload)
    elif not isinstance(package_contract, dict):
        if "modules" in lesson_payload:
            raise ValueError("OpenClaw result is missing package_contract.")
        package_contract = _build_minimal_package_contract(lesson_payload)

    contract = _normalize_package_contract(package_contract, lesson_payload)
    slide_contract = payload.get("slide_contract")
    slides = _normalize_slide_contract(slide_contract, contract)
    modules = _normalize_modules(lesson_payload, contract)
    document_outputs = contract["document_outputs"]

    lesson = {
        "unit_meta": _normalize_unit_meta(lesson_payload.get("unit_meta")),
        "curriculum_requirements": _normalize_string_list(
            lesson_payload.get("curriculum_requirements"),
            "lesson_payload.curriculum_requirements",
        ),
        "discipline_literacy_targets": _normalize_named_lists(
            lesson_payload.get("discipline_literacy_targets"),
            DISCIPLINE_TARGET_KEYS,
            "lesson_payload.discipline_literacy_targets",
        ),
        "material_analysis": _normalize_string_list(lesson_payload.get("material_analysis"), "lesson_payload.material_analysis"),
        "student_analysis": _normalize_string_list(lesson_payload.get("student_analysis"), "lesson_payload.student_analysis"),
        "unit_objectives": _normalize_named_lists(
            lesson_payload.get("unit_objectives"),
            OBJECTIVE_KEYS,
            "lesson_payload.unit_objectives",
        ),
        "key_and_difficult_points": _normalize_named_lists(
            lesson_payload.get("key_and_difficult_points"),
            POINT_KEYS,
            "lesson_payload.key_and_difficult_points",
        ),
        "assessment_design": _normalize_named_lists(
            lesson_payload.get("assessment_design"),
            ASSESSMENT_KEYS,
            "lesson_payload.assessment_design",
        ),
        "modules": modules,
        "theme_lessons": modules,
        "guidance_pack": _normalize_guidance_pack(lesson_payload.get("guidance_pack"))
        if document_outputs.get("guidance") or isinstance(lesson_payload.get("guidance_pack"), dict)
        else {},
        "homework_pack": _normalize_question_pack(
            lesson_payload.get("homework_pack"),
            "lesson_payload.homework_pack",
            ("basic_questions", "advanced_questions", "integrated_questions"),
        )
        if document_outputs.get("homework") or isinstance(lesson_payload.get("homework_pack"), dict)
        else {},
        "review_pack": _normalize_review_pack(lesson_payload.get("review_pack"))
        if document_outputs.get("review") or isinstance(lesson_payload.get("review_pack"), dict)
        else {},
        "flagship_storyline": _normalize_flagship(lesson_payload.get("flagship_storyline")),
        "qgis_guidance": _normalize_named_lists(
            lesson_payload.get("qgis_guidance"),
            QGIS_GUIDANCE_KEYS,
            "lesson_payload.qgis_guidance",
        ),
        "project_advantages": _normalize_project_advantages(lesson_payload.get("project_advantages")),
    }
    _validate_required_sections(lesson, contract)
    return {
        "summary": str(payload.get("summary", "")).strip(),
        "notes": str(payload.get("notes", "")).strip(),
        "package_contract": contract,
        "lesson_payload": lesson,
        "slide_contract": slides,
    }


def render_lesson_markdown(blueprint: Dict[str, Any]) -> str:
    return render_document_package(blueprint)["lesson_plan"]


def render_document_package(blueprint: Dict[str, Any]) -> Dict[str, str]:
    lesson = blueprint["lesson_payload"]
    document_outputs = blueprint.get("package_contract", {}).get("document_outputs", {})
    documents = {"lesson_plan": _render_unit_design_markdown(lesson)}
    if document_outputs.get("guidance"):
        documents["guidance"] = _render_guidance_markdown(lesson)
    if document_outputs.get("homework"):
        documents["homework"] = _render_homework_markdown(lesson)
    if document_outputs.get("review"):
        documents["review"] = _render_review_markdown(lesson)
    return documents


def write_docx_from_markdown(markdown_text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = _markdown_to_paragraphs(markdown_text)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _docx_content_types())
        archive.writestr("_rels/.rels", _docx_root_relationships())
        archive.writestr("docProps/app.xml", _docx_app_properties())
        archive.writestr("docProps/core.xml", _docx_core_properties())
        archive.writestr("word/document.xml", _docx_document(paragraphs))
        archive.writestr("word/styles.xml", _docx_styles())
        archive.writestr("word/_rels/document.xml.rels", _docx_document_relationships())


def build_ppt_scenario(blueprint: Dict[str, Any], style_family: str, scenario_id: str) -> Dict[str, Any]:
    lesson = blueprint["lesson_payload"]
    unit_meta = lesson["unit_meta"]
    slides: List[Dict[str, Any]] = []
    for slide in blueprint["slide_contract"]:
        slide_payload: Dict[str, Any] = {
            "slide_id": slide["slide_id"],
            "title": slide["title"],
            "subtitle": slide["subtitle"],
            "page_goal": slide["page_goal"],
            "core_message": slide["core_message"],
            "evidence_type": slide["evidence_type"],
            "recommended_visual": slide["recommended_visual"],
            "speaker_note": slide["speaker_note"],
            "bullets": slide["supporting_points"],
            "footnote": slide["core_message"],
        }
        if slide.get("expected_page_family"):
            slide_payload["expected_page_family"] = slide["expected_page_family"]
        for key in ("hero_metrics", "metrics", "chart_points", "steps", "side_cards"):
            if slide.get(key):
                slide_payload[key] = slide[key]
        for key in OPTIONAL_SLIDE_LIST_KEYS:
            if slide.get(key):
                slide_payload[key] = slide[key]
        slides.append(slide_payload)
    return {
        "id": scenario_id,
        "style_family": style_family,
        "title": unit_meta["title"],
        "audience": unit_meta["audience"],
        "slides": slides,
    }


def summarize_package_contract(blueprint: Dict[str, Any]) -> List[str]:
    contract = blueprint.get("package_contract", {})
    module_requirements = contract.get("module_requirements", {})
    document_outputs = contract.get("document_outputs", {})
    presentation_requirements = contract.get("presentation_requirements", {})

    outputs = [key for key in DOCUMENT_OUTPUT_KEYS if document_outputs.get(key)]
    output_labels = {
        "lesson_plan": "主教学设计",
        "guidance": "导学材料",
        "homework": "作业材料",
        "review": "复习材料",
    }
    summary = [
        "成果包类型：{}".format(contract.get("package_type", "lesson_package")),
        "模块要求：至少 {} 个".format(module_requirements.get("min_count", 1)),
    ]
    if module_requirements.get("recommended_module_roles"):
        summary.append("建议模块角色：{}".format("、".join(module_requirements["recommended_module_roles"])))
    if outputs:
        summary.append("文档输出：{}".format("、".join(output_labels.get(item, item) for item in outputs)))
    if presentation_requirements.get("enabled"):
        required_pages = presentation_requirements.get("required_page_families", [])
        page_text = " / ".join(required_pages) if required_pages else "未限定页面族"
        summary.append("展示约束：至少 {} 页，关键页面 {}".format(presentation_requirements.get("min_slides", 1), page_text))
    return summary


def write_ppt_scenario_file(scenario: Dict[str, Any], scenario_path: Path) -> None:
    scenario_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "regression_suite": "geobot-lesson-ppt",
        "scenarios": [scenario],
    }
    scenario_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_pptx_from_scenario(
    ppt_studio_dir: Path,
    scenario_path: Path,
    scenario_id: str,
    output_dir: Path,
) -> Dict[str, str]:
    generator_path = Path(ppt_studio_dir) / PPT_GENERATOR_RELATIVE_PATH
    if not generator_path.exists():
        raise RuntimeError("PPT generator not found: {}".format(generator_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            "node",
            str(generator_path),
            "--regression-file",
            str(scenario_path),
            "--scenario-id",
            scenario_id,
            "--output-dir",
            str(output_dir),
        ],
        cwd=str(ppt_studio_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(detail or "Local PPT generation failed.")
    deck_path = output_dir / ("{}.pptx".format(scenario_id))
    metadata_path = output_dir / ("{}.deck.json".format(scenario_id))
    if not deck_path.exists():
        raise RuntimeError("Local PPT generation finished without producing the expected PPTX file.")
    return {
        "pptx_path": str(deck_path),
        "deck_metadata_path": str(metadata_path),
    }


def _normalize_unit_meta(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.unit_meta.")
    required_keys = (
        "title",
        "audience",
        "course",
        "grade",
        "time_allocation",
        "unit_overview",
        "showcase_positioning",
    )
    return {key: _require_string(value, key, "lesson_payload.unit_meta") for key in required_keys}


def _build_minimal_package_contract(lesson_payload: Dict[str, Any]) -> Dict[str, Any]:
    modules = lesson_payload.get("modules")
    if not isinstance(modules, list) or not modules:
        modules = lesson_payload.get("theme_lessons")
    module_count = len(modules) if isinstance(modules, list) and modules else 1
    document_outputs = {
        "lesson_plan": True,
        "guidance": bool(lesson_payload.get("guidance_pack")),
        "homework": bool(lesson_payload.get("homework_pack")),
        "review": bool(lesson_payload.get("review_pack")),
    }
    presentation_enabled = bool(lesson_payload)  # legacy lesson_ppt always expected slides
    return {
        "package_type": "lesson_package",
        "required_sections": [
            "unit_meta",
            "curriculum_requirements",
            "discipline_literacy_targets",
            "material_analysis",
            "student_analysis",
            "unit_objectives",
            "key_and_difficult_points",
            "assessment_design",
            "modules",
            "qgis_guidance",
            "project_advantages",
        ],
        "module_requirements": {
            "min_count": module_count,
            "required_fields": list(THEME_REQUIRED_KEYS)
            + [
                "core_questions",
                "teaching_objectives",
                "evidence",
                "teaching_process",
                "activities",
                "evaluation_points",
                "summary",
                "board_plan",
                "homework",
                "reflection",
            ],
            "expected_module_ids": [],
            "recommended_module_roles": [],
        },
        "document_outputs": document_outputs,
        "presentation_requirements": {
            "enabled": presentation_enabled,
            "min_slides": 1 if presentation_enabled else 0,
            "required_page_families": [],
        },
        "completion_checks": ["Provide a coherent lesson package and slide contract."],
    }


def _normalize_package_contract(value: Any, lesson_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing package_contract.")
    contract = {key: value.get(key) for key in PACKAGE_CONTRACT_KEYS}
    package_type = _require_string(contract, "package_type", "package_contract")
    required_sections = _normalize_string_list(contract.get("required_sections"), "package_contract.required_sections")
    module_requirements = _normalize_module_requirements(contract.get("module_requirements"))
    document_outputs = _normalize_document_outputs(contract.get("document_outputs"), lesson_payload)
    presentation_requirements = _normalize_presentation_requirements(contract.get("presentation_requirements"))
    completion_checks = _normalize_string_list(contract.get("completion_checks"), "package_contract.completion_checks")
    return {
        "package_type": package_type,
        "required_sections": required_sections,
        "module_requirements": module_requirements,
        "document_outputs": document_outputs,
        "presentation_requirements": presentation_requirements,
        "completion_checks": completion_checks,
    }


def _normalize_named_lists(value: Any, keys: Iterable[str], scope: str) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    return {key: _normalize_string_list(value.get(key), "{}.{}".format(scope, key)) for key in keys}


def _normalize_guidance_pack(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.guidance_pack.")
    result = {"title": _require_string(value, "title", "lesson_payload.guidance_pack")}
    result.update(_normalize_named_lists(value, GUIDANCE_PACK_KEYS, "lesson_payload.guidance_pack"))
    return result


def _normalize_module_requirements(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing package_contract.module_requirements.")
    raw_min_count = value.get("min_count")
    try:
        min_count = int(raw_min_count)
    except (TypeError, ValueError):
        raise ValueError("OpenClaw result is missing package_contract.module_requirements.min_count.")
    if min_count < 1:
        raise ValueError("OpenClaw result has invalid package_contract.module_requirements.min_count.")
    required_fields = _normalize_string_list(
        value.get("required_fields"),
        "package_contract.module_requirements.required_fields",
    )
    expected_module_ids = _normalize_optional_string_list(
        value.get("expected_module_ids"),
        "package_contract.module_requirements.expected_module_ids",
    )
    recommended_module_roles = _normalize_optional_string_list(
        value.get("recommended_module_roles"),
        "package_contract.module_requirements.recommended_module_roles",
    )
    return {
        "min_count": min_count,
        "required_fields": required_fields,
        "expected_module_ids": expected_module_ids,
        "recommended_module_roles": recommended_module_roles,
    }


def _normalize_document_outputs(value: Any, lesson_payload: Dict[str, Any]) -> Dict[str, bool]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing package_contract.document_outputs.")
    outputs: Dict[str, bool] = {}
    for key in DOCUMENT_OUTPUT_KEYS:
        raw = value.get(key, key == "lesson_plan")
        outputs[key] = bool(raw)
    outputs["lesson_plan"] = True
    if outputs.get("guidance") and not isinstance(lesson_payload.get("guidance_pack"), dict):
        raise ValueError("package_contract.document_outputs.guidance requires lesson_payload.guidance_pack.")
    if outputs.get("homework") and not isinstance(lesson_payload.get("homework_pack"), dict):
        raise ValueError("package_contract.document_outputs.homework requires lesson_payload.homework_pack.")
    if outputs.get("review") and not isinstance(lesson_payload.get("review_pack"), dict):
        raise ValueError("package_contract.document_outputs.review requires lesson_payload.review_pack.")
    return outputs


def _normalize_presentation_requirements(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing package_contract.presentation_requirements.")
    enabled = bool(value.get("enabled", True))
    raw_min_slides = value.get("min_slides", 1 if enabled else 0)
    try:
        min_slides = int(raw_min_slides)
    except (TypeError, ValueError):
        raise ValueError("OpenClaw result has invalid package_contract.presentation_requirements.min_slides.")
    if min_slides < 0:
        raise ValueError("OpenClaw result has invalid package_contract.presentation_requirements.min_slides.")
    required_page_families = _normalize_optional_string_list(
        value.get("required_page_families"),
        "package_contract.presentation_requirements.required_page_families",
    )
    return {
        "enabled": enabled,
        "min_slides": min_slides,
        "required_page_families": required_page_families,
    }


def _normalize_question_pack(value: Any, scope: str, section_keys: Iterable[str]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    pack = {"title": _require_string(value, "title", scope)}
    for key in section_keys:
        pack[key] = _normalize_question_list(value.get(key), "{}.{}".format(scope, key))
    return pack


def _normalize_review_pack(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.review_pack.")
    return {
        "title": _require_string(value, "title", "lesson_payload.review_pack"),
        "knowledge_checklist": _normalize_string_list(
            value.get("knowledge_checklist"),
            "lesson_payload.review_pack.knowledge_checklist",
        ),
        "high_frequency_judgments": _normalize_string_list(
            value.get("high_frequency_judgments"),
            "lesson_payload.review_pack.high_frequency_judgments",
        ),
        "common_mistakes": _normalize_string_list(
            value.get("common_mistakes"),
            "lesson_payload.review_pack.common_mistakes",
        ),
        "example_questions": _normalize_question_list(
            value.get("example_questions"),
            "lesson_payload.review_pack.example_questions",
        ),
        "review_advice": _normalize_string_list(
            value.get("review_advice"),
            "lesson_payload.review_pack.review_advice",
        ),
    }


def _normalize_flagship(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.flagship_storyline.")
    return {
        "title": _require_string(value, "title", "lesson_payload.flagship_storyline"),
        "summary": _require_string(value, "summary", "lesson_payload.flagship_storyline"),
        "highlights": _normalize_string_list(
            value.get("highlights"),
            "lesson_payload.flagship_storyline.highlights",
        ),
        "evidence_chain": _normalize_string_list(
            value.get("evidence_chain"),
            "lesson_payload.flagship_storyline.evidence_chain",
        ),
        "presentation_value": _normalize_string_list(
            value.get("presentation_value"),
            "lesson_payload.flagship_storyline.presentation_value",
        ),
    }


def _normalize_project_advantages(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OpenClaw result is missing lesson_payload.project_advantages.")
    result = {"title": _require_string(value, "title", "lesson_payload.project_advantages")}
    result.update(_normalize_named_lists(value, PROJECT_ADVANTAGE_KEYS, "lesson_payload.project_advantages"))
    return result


def _normalize_modules(lesson_payload: Dict[str, Any], package_contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_modules = lesson_payload.get("modules")
    if not isinstance(raw_modules, list) or not raw_modules:
        raw_modules = lesson_payload.get("theme_lessons")
    modules = _normalize_theme_lessons(raw_modules)
    module_requirements = package_contract["module_requirements"]
    if len(modules) < module_requirements["min_count"]:
        raise ValueError(
            "OpenClaw result has incomplete modules: expected at least {}, got {}.".format(
                module_requirements["min_count"],
                len(modules),
            )
        )
    expected_module_ids = module_requirements.get("expected_module_ids", [])
    if expected_module_ids:
        returned_ids = {item["theme_id"] for item in modules}
        missing = [item for item in expected_module_ids if item not in returned_ids]
        if missing:
            raise ValueError("OpenClaw result is missing required modules: {}.".format(", ".join(missing)))
    return modules


def _normalize_theme_lessons(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("OpenClaw result is missing lesson_payload.modules.")
    lessons: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid lesson_payload.theme_lessons[{}].".format(index))
        theme_scope = "lesson_payload.theme_lessons[{}]".format(index)
        lesson = {key: _require_string(item, key, theme_scope) for key in THEME_REQUIRED_KEYS}
        lesson["core_questions"] = _normalize_string_list(item.get("core_questions"), "{}.core_questions".format(theme_scope))
        lesson["teaching_objectives"] = _normalize_string_list(
            item.get("teaching_objectives"),
            "{}.teaching_objectives".format(theme_scope),
        )
        lesson["evidence"] = _normalize_string_list(item.get("evidence"), "{}.evidence".format(theme_scope))
        lesson["activities"] = _normalize_string_list(item.get("activities"), "{}.activities".format(theme_scope))
        lesson["evaluation_points"] = _normalize_string_list(
            item.get("evaluation_points"),
            "{}.evaluation_points".format(theme_scope),
        )
        lesson["summary"] = _normalize_string_list(item.get("summary"), "{}.summary".format(theme_scope))
        lesson["board_plan"] = _normalize_string_list(item.get("board_plan"), "{}.board_plan".format(theme_scope))
        lesson["homework"] = _normalize_string_list(item.get("homework"), "{}.homework".format(theme_scope))
        lesson["reflection"] = _normalize_string_list(item.get("reflection"), "{}.reflection".format(theme_scope))
        lesson["teaching_process"] = _normalize_teaching_process(item.get("teaching_process"), "{}.teaching_process".format(theme_scope))
        lessons.append(lesson)
    return lessons


def _normalize_slide_contract(value: Any, package_contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    presentation_requirements = package_contract["presentation_requirements"]
    if not presentation_requirements.get("enabled"):
        return []
    if not isinstance(value, list) or not value:
        raise ValueError("OpenClaw result is missing slide_contract.")
    slides = [_normalize_slide(slide, index) for index, slide in enumerate(value)]
    if len(slides) < presentation_requirements.get("min_slides", 1):
        raise ValueError(
            "OpenClaw result has incomplete slide_contract: expected at least {} slides.".format(
                presentation_requirements.get("min_slides", 1)
            )
        )
    required_page_families = presentation_requirements.get("required_page_families", [])
    if required_page_families:
        available = {slide.get("expected_page_family") or slide.get("recommended_visual") for slide in slides}
        missing = [item for item in required_page_families if item not in available]
        if missing:
            raise ValueError("OpenClaw result is missing required slide page families: {}.".format(", ".join(missing)))
    return slides


def _normalize_teaching_process(value: Any, scope: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    stages: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid {}[{}].".format(scope, index))
        stage_scope = "{}[{}]".format(scope, index)
        stages.append(
            {
                "stage": _require_string(item, "stage", stage_scope),
                "duration": _require_string(item, "duration", stage_scope),
                "teacher_activity": _normalize_string_list(item.get("teacher_activity"), "{}.teacher_activity".format(stage_scope)),
                "student_activity": _normalize_string_list(item.get("student_activity"), "{}.student_activity".format(stage_scope)),
                "goal": _require_string(item, "goal", stage_scope),
                "assessment": _normalize_string_list(item.get("assessment"), "{}.assessment".format(stage_scope)),
            }
        )
    return stages


def _normalize_question_list(value: Any, scope: str) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    questions: List[Dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid {}[{}].".format(scope, index))
        question_scope = "{}[{}]".format(scope, index)
        questions.append(
            {
                "prompt": _require_string(item, "prompt", question_scope),
                "answer": _require_string(item, "answer", question_scope),
                "analysis": _require_string(item, "analysis", question_scope),
            }
        )
    return questions


def _normalize_optional_string_list(value: Any, scope: str) -> List[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("OpenClaw result has invalid {}.".format(scope))
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_required_sections(lesson: Dict[str, Any], package_contract: Dict[str, Any]) -> None:
    required_sections = package_contract.get("required_sections", [])
    for section in required_sections:
        if section == "modules":
            if not lesson.get("modules"):
                raise ValueError("OpenClaw result is missing required section lesson_payload.modules.")
            continue
        value = lesson.get(section)
        if isinstance(value, list) and value:
            continue
        if isinstance(value, dict) and value:
            continue
        if isinstance(value, str) and value.strip():
            continue
        raise ValueError("OpenClaw result is missing required section lesson_payload.{}.".format(section))


def _normalize_slide(slide: Any, index: int) -> Dict[str, Any]:
    if not isinstance(slide, dict):
        raise ValueError("OpenClaw result has invalid slide_contract[{}].".format(index))
    normalized = {
        key: _require_string(slide, key, "slide_contract[{}]".format(index))
        for key in REQUIRED_SLIDE_KEYS
        if key != "supporting_points"
    }
    normalized["supporting_points"] = _normalize_string_list(
        slide.get("supporting_points"),
        "slide_contract[{}].supporting_points".format(index),
    )
    normalized["hero_metrics"] = _normalize_metric_cards(slide.get("hero_metrics"), "slide_contract[{}].hero_metrics".format(index))
    normalized["metrics"] = _normalize_metric_cards(slide.get("metrics"), "slide_contract[{}].metrics".format(index))
    normalized["chart_points"] = _normalize_metric_cards(slide.get("chart_points"), "slide_contract[{}].chart_points".format(index))
    normalized["steps"] = _normalize_steps(slide.get("steps"), "slide_contract[{}].steps".format(index))
    normalized["side_cards"] = _normalize_side_cards(slide.get("side_cards"), "slide_contract[{}].side_cards".format(index))
    normalized["expected_page_family"] = str(slide.get("expected_page_family", "")).strip()
    for key in OPTIONAL_SLIDE_LIST_KEYS:
        value = slide.get(key)
        normalized[key] = _normalize_string_list(value, "slide_contract[{}].{}".format(index, key)) if value else []
    return normalized


def _normalize_metric_cards(value: Any, scope: str) -> List[Dict[str, str]]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("OpenClaw result has invalid {}.".format(scope))
    items: List[Dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid {}[{}].".format(scope, index))
        label = _require_string(item, "label", "{}[{}]".format(scope, index))
        raw_value = item.get("value")
        if raw_value is None or str(raw_value).strip() == "":
            raise ValueError("OpenClaw result is missing {}[{}].value.".format(scope, index))
        items.append({"label": label, "value": str(raw_value).strip()})
    return items


def _normalize_steps(value: Any, scope: str) -> List[Dict[str, Any]]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("OpenClaw result has invalid {}.".format(scope))
    items: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid {}[{}].".format(scope, index))
        items.append(
            {
                "title": _require_string(item, "title", "{}[{}]".format(scope, index)),
                "bullets": _normalize_string_list(item.get("bullets"), "{}[{}].bullets".format(scope, index)),
            }
        )
    return items


def _normalize_side_cards(value: Any, scope: str) -> List[Dict[str, str]]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("OpenClaw result has invalid {}.".format(scope))
    items: List[Dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("OpenClaw result has invalid {}[{}].".format(scope, index))
        items.append(
            {
                "title": _require_string(item, "title", "{}[{}]".format(scope, index)),
                "body": _require_string(item, "body", "{}[{}]".format(scope, index)),
            }
        )
    return items


def _upgrade_legacy_lesson_payload(lesson_payload: Dict[str, Any]) -> Dict[str, Any]:
    theme_modules = lesson_payload.get("theme_modules") or []
    teaching_process = lesson_payload.get("teaching_process") or []
    flagship = lesson_payload.get("flagship_storyline") or {}
    qgis_guidance = lesson_payload.get("qgis_guidance") or {}
    legacy_objectives = lesson_payload.get("lesson_objectives") or {}

    theme_lessons: List[Dict[str, Any]] = []
    for index, theme in enumerate(theme_modules):
        if not isinstance(theme, dict):
            continue
        theme_lessons.append(
            {
                "theme_id": "theme{}".format(index + 1),
                "title": str(theme.get("title") or "主题 {}".format(index + 1)).strip(),
                "focus": str(theme.get("focus") or "主题核心").strip(),
                "periods": str(theme.get("periods") or "1 课时").strip(),
                "core_questions": _legacy_list(theme.get("core_questions"), ["围绕人口地理核心问题展开探究。"]),
                "teaching_objectives": _legacy_list(
                    legacy_objectives.get("knowledge_and_skills"),
                    ["能够结合地图和材料说明人口地理现象。"],
                ),
                "evidence": _legacy_list(theme.get("evidence"), ["人口相关地图与图表材料。"]),
                "teaching_process": _legacy_process(teaching_process),
                "activities": _legacy_list(theme.get("activities"), ["读图分析", "合作讨论"]),
                "evaluation_points": _legacy_list(theme.get("evaluation_points"), ["能够用证据解释地理现象。"]),
                "summary": ["梳理本主题的概念、规律与解释框架。"],
                "board_plan": _legacy_list(theme.get("activities"), ["核心概念", "分布规律", "成因分析"]),
                "homework": _legacy_list(lesson_payload.get("homework"), ["整理主题知识结构。"]),
                "reflection": ["根据课堂表现优化后续主题衔接与证据使用。"],
            }
        )

    if not theme_lessons:
        theme_lessons.append(
            {
                "theme_id": "theme1",
                "title": "主题 1 人口分布",
                "focus": "围绕人口分布与变化展开单元探究",
                "periods": "2 课时",
                "core_questions": ["为什么人口空间分布存在明显差异？"],
                "teaching_objectives": ["能够借助地图和材料解释人口分布现象。"],
                "evidence": ["人口分布图", "人口密度图"],
                "teaching_process": _legacy_process(teaching_process),
                "activities": ["读图判断", "合作解释"],
                "evaluation_points": ["能够结合证据解释人口现象。"],
                "summary": ["梳理人口分布的基本格局与影响因素。"],
                "board_plan": ["人口分布", "差异特征", "影响因素"],
                "homework": _legacy_list(lesson_payload.get("homework"), ["整理单元知识结构。"]),
                "reflection": ["根据课堂生成补充案例与图表证据。"],
            }
        )

    return {
        "unit_meta": {
            "title": str(lesson_payload.get("title") or "地理单元教学设计").strip(),
            "audience": str(lesson_payload.get("audience") or "高中学生").strip(),
            "course": "高中地理必修二",
            "grade": "高中一年级",
            "time_allocation": "{} 课时".format(max(len(theme_lessons) * 2, 4)),
            "unit_overview": str(lesson_payload.get("unit_overview") or "围绕人口分布、迁移与容量组织教学。").strip(),
            "showcase_positioning": "面向答辩展示与教学落地的完整成果包。",
        },
        "curriculum_requirements": ["结合地图、图表和区域案例认识人口地理现象及其影响。"],
        "discipline_literacy_targets": {
            "human_earth_coordination": ["形成人口与区域环境协调发展的认识。"],
            "regional_cognition": ["能够从区域差异视角理解人口空间分布。"],
            "comprehensive_thinking": ["能够综合自然、社会和经济因素分析人口问题。"],
            "geographical_practice": ["能够根据教学问题设计读图、判读和表达任务。"],
        },
        "material_analysis": ["以教材人口单元为主线，串联分布、迁移与合理容量。"],
        "student_analysis": ["学生对人口概念有初步认识，但对成因解释和多尺度证据组织仍需支架。"],
        "unit_objectives": {
            "knowledge_and_skills": _legacy_list(
                legacy_objectives.get("knowledge_and_skills"),
                ["理解人口分布、迁移与合理容量的基本概念。"],
            ),
            "process_and_methods": _legacy_list(
                legacy_objectives.get("process_and_methods"),
                ["通过地图与图表证据组织课堂探究。"],
            ),
            "values": _legacy_list(
                legacy_objectives.get("values"),
                ["形成人口与区域环境协调发展的认识。"],
            ),
        },
        "key_and_difficult_points": {
            "key_points": ["人口分布规律", "人口迁移原因与影响", "人口合理容量讨论"],
            "difficult_points": ["用综合因素解释人口现象", "将地图证据转化为课堂结论"],
        },
        "assessment_design": {
            "formative": _legacy_list(lesson_payload.get("assessment"), ["课堂提问、讨论与展示评价。"]),
            "summative": ["通过单元任务单、作业与复习检测检验学习效果。"],
        },
        "theme_lessons": theme_lessons,
        "guidance_pack": {
            "title": "人口单元导学建议",
            "preclass_tasks": ["阅读教材，标注主题 1/2/3 的核心概念。"],
            "inclass_inquiry_tasks": ["比较人口分布与迁移图表，提出解释结论。"],
            "method_guidance": ["先识别空间格局，再联系影响因素，最后形成判断。"],
            "common_pitfalls": ["只背结论，不会结合证据解释。"],
        },
        "homework_pack": {
            "title": "人口单元分层作业",
            "basic_questions": [{"prompt": "说出人口单元的三大主题。", "answer": "人口分布、人口迁移、人口合理容量。", "analysis": "先建立单元结构，再开展深入分析。"}],
            "advanced_questions": [{"prompt": "说明人口迁移与区域发展的关系。", "answer": "人口迁移会影响劳动力供给、产业布局和区域结构。", "analysis": "回答时应从迁入地和迁出地双向分析。"}],
            "integrated_questions": [{"prompt": "结合人口分布与迁移，概述胡焕庸线的教学价值。", "answer": "胡焕庸线是观察人口格局、迁移趋势和区域差异的重要线索。", "analysis": "需联系空间差异与时代变化回答。"}],
        },
        "review_pack": {
            "title": "人口单元复习材料",
            "knowledge_checklist": ["人口分布基本格局", "人口迁移类型与影响", "人口合理容量含义"],
            "high_frequency_judgments": ["人口分布与自然条件密切相关。", "人口迁移受经济机会显著影响。"],
            "common_mistakes": ["把人口密度与总人口混为一谈。", "忽视政策和历史因素对迁移的影响。"],
            "example_questions": [{"prompt": "说明人口合理容量与资源环境的关系。", "answer": "人口合理容量受资源禀赋、环境条件和技术水平共同制约。", "analysis": "答题时要体现动态性和综合性。"}],
            "review_advice": ["按主题梳理概念、规律、原因、影响和案例。"],
        },
        "flagship_storyline": {
            "title": str(flagship.get("title") or "胡焕庸线与当代人口流动").strip(),
            "summary": str(flagship.get("summary") or "以人口分布和迁移构成答辩主线。").strip(),
            "highlights": _legacy_list(flagship.get("highlights"), ["分布差异", "迁移方向", "容量讨论"]),
            "evidence_chain": ["中国人口分布图", "人口迁移示意图", "容量与资源环境案例"],
            "presentation_value": ["形成强主线叙事", "突出项目数据联动优势"],
        },
        "qgis_guidance": {
            "recommended_layers": _legacy_list(qgis_guidance.get("recommended_layers"), ["china_provinces_population.geojson"]),
            "recommended_templates": _legacy_list(qgis_guidance.get("recommended_templates"), ["population_change_comparison"]),
            "key_fields": _legacy_list(qgis_guidance.get("key_fields"), ["population", "density"]),
            "suggested_exports": _legacy_list(qgis_guidance.get("suggested_exports"), ["Theme 1 地图", "Theme 2 地图"]),
            "notes": _legacy_list(qgis_guidance.get("notes"), ["后续可由 GeoBot 本地或 QGIS-only 模式执行。"]),
        },
        "project_advantages": {
            "title": "GeoBot 项目特色与优势",
            "capabilities": ["从教学意图直接生成完整成果包。", "用结构化内容驱动后续 PPT 生成。"],
            "difference_from_normal_teaching": ["不再停留在手工拼接教案和 PPT。", "可自然衔接后续 QGIS 制图执行。"],
            "showcase_tips": ["答辩时先讲主线，再切换到成果包和地图计划。"],
        },
    }


def _legacy_process(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return [
            {
                "stage": "导入",
                "duration": "10 分钟",
                "teacher_activity": ["抛出核心问题，建立学习情境。"],
                "student_activity": ["观察材料，提出初步判断。"],
                "goal": "建立单元探究主线。",
                "assessment": ["课堂提问"],
            }
        ]
    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "stage": str(item.get("stage") or "环节").strip(),
                "duration": str(item.get("duration") or "10 分钟").strip(),
                "teacher_activity": _legacy_list(item.get("teacher_activity"), ["引导学生阅读材料。"]),
                "student_activity": _legacy_list(item.get("student_activity"), ["依据材料形成判断。"]),
                "goal": str(item.get("goal") or "形成课堂结论。").strip(),
                "assessment": _legacy_list(item.get("assessment"), ["课堂交流"]),
            }
        )
    return normalized or [
        {
            "stage": "导入",
            "duration": "10 分钟",
            "teacher_activity": ["引导学生进入主题。"],
            "student_activity": ["观察材料并作答。"],
            "goal": "建立学习主线。",
            "assessment": ["课堂提问"],
        }
    ]


def _legacy_list(value: Any, fallback: List[str]) -> List[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return fallback


def _require_string(payload: Dict[str, Any], key: str, scope: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("OpenClaw result is missing {}.{}.".format(scope, key))
    return value.strip()


def _normalize_string_list(value: Any, scope: str) -> List[str]:
    if not isinstance(value, list):
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise ValueError("OpenClaw result is missing {}.".format(scope))
    return items


def _render_unit_design_markdown(lesson: Dict[str, Any]) -> str:
    meta = lesson["unit_meta"]
    lines: List[str] = [
        "# {}".format(meta["title"]),
        "",
        "## 基本信息",
        "- 适用对象：{}".format(meta["audience"]),
        "- 课程归属：{}".format(meta["course"]),
        "- 年级：{}".format(meta["grade"]),
        "- 课时安排：{}".format(meta["time_allocation"]),
        "- 单元概述：{}".format(meta["unit_overview"]),
        "- 展示定位：{}".format(meta["showcase_positioning"]),
        "",
        "## 课程标准要求",
    ]
    lines.extend(_bullet_lines(lesson["curriculum_requirements"]))
    lines.extend(["", "## 地理核心素养目标"])
    lines.extend(_named_bullet_section("### 人地协调观", lesson["discipline_literacy_targets"]["human_earth_coordination"]))
    lines.extend(_named_bullet_section("### 区域认知", lesson["discipline_literacy_targets"]["regional_cognition"]))
    lines.extend(_named_bullet_section("### 综合思维", lesson["discipline_literacy_targets"]["comprehensive_thinking"]))
    lines.extend(_named_bullet_section("### 地理实践力", lesson["discipline_literacy_targets"]["geographical_practice"]))
    lines.extend(["", "## 教材分析"])
    lines.extend(_bullet_lines(lesson["material_analysis"]))
    lines.extend(["", "## 学情分析"])
    lines.extend(_bullet_lines(lesson["student_analysis"]))
    lines.extend(["", "## 单元目标"])
    lines.extend(_named_bullet_section("### 知识与技能", lesson["unit_objectives"]["knowledge_and_skills"]))
    lines.extend(_named_bullet_section("### 过程与方法", lesson["unit_objectives"]["process_and_methods"]))
    lines.extend(_named_bullet_section("### 情感态度与价值观", lesson["unit_objectives"]["values"]))
    lines.extend(["", "## 教学重点与难点"])
    lines.extend(_named_bullet_section("### 重点", lesson["key_and_difficult_points"]["key_points"]))
    lines.extend(_named_bullet_section("### 难点", lesson["key_and_difficult_points"]["difficult_points"]))
    lines.extend(["", "## 单元主题结构"])
    for theme in lesson["theme_lessons"]:
        lines.extend(
            [
                "",
                "### {}".format(theme["title"]),
                "- 主题编号：{}".format(theme["theme_id"]),
                "- 核心聚焦：{}".format(theme["focus"]),
                "- 课时建议：{}".format(theme["periods"]),
                "#### 核心问题",
            ]
        )
        lines.extend(_bullet_lines(theme["core_questions"]))
        lines.extend(["", "#### 教学目标"])
        lines.extend(_bullet_lines(theme["teaching_objectives"]))
        lines.extend(["", "#### 核心地图与证据"])
        lines.extend(_bullet_lines(theme["evidence"]))
        lines.extend(["", "#### 教学过程"])
        for stage in theme["teaching_process"]:
            lines.extend(
                [
                    "",
                    "##### {}（{}）".format(stage["stage"], stage["duration"]),
                    "###### 教师活动",
                ]
            )
            lines.extend(_bullet_lines(stage["teacher_activity"]))
            lines.extend(["", "###### 学生活动"])
            lines.extend(_bullet_lines(stage["student_activity"]))
            lines.extend(["", "- 设计意图：{}".format(stage["goal"]), "###### 评价方式"])
            lines.extend(_bullet_lines(stage["assessment"]))
        lines.extend(["", "#### 课堂活动与评价"])
        lines.extend(_named_bullet_section("##### 课堂活动", theme["activities"]))
        lines.extend(_named_bullet_section("##### 评价要点", theme["evaluation_points"]))
        lines.extend(["", "#### 课堂小结"])
        lines.extend(_bullet_lines(theme["summary"]))
        lines.extend(["", "#### 板书或结构化总结"])
        lines.extend(_bullet_lines(theme["board_plan"]))
        lines.extend(["", "#### 主题作业"])
        lines.extend(_bullet_lines(theme["homework"]))
        lines.extend(["", "#### 教学反思"])
        lines.extend(_bullet_lines(theme["reflection"]))
    lines.extend(["", "## 旗舰主线"])
    lines.extend(_render_flagship_section(lesson["flagship_storyline"]))
    lines.extend(["", "## 单元评价设计"])
    lines.extend(_named_bullet_section("### 形成性评价", lesson["assessment_design"]["formative"]))
    lines.extend(_named_bullet_section("### 总结性评价", lesson["assessment_design"]["summative"]))
    lines.extend(["", "## 建议 QGIS 操作"])
    lines.extend(_render_qgis_section(lesson["qgis_guidance"]))
    lines.extend(["", "## GeoBot 项目特色与优势"])
    lines.extend(_render_project_advantage_section(lesson["project_advantages"]))
    return "\n".join(lines).strip() + "\n"


def _render_guidance_markdown(lesson: Dict[str, Any]) -> str:
    meta = lesson["unit_meta"]
    guidance = lesson["guidance_pack"]
    lines: List[str] = [
        "# {}".format(guidance["title"]),
        "",
        "## 适用单元",
        "- {}".format(meta["title"]),
        "",
        "## 课前预习任务",
    ]
    lines.extend(_bullet_lines(guidance["preclass_tasks"]))
    lines.extend(["", "## 课堂探究任务"])
    lines.extend(_bullet_lines(guidance["inclass_inquiry_tasks"]))
    lines.extend(["", "## 学习方法提示"])
    lines.extend(_bullet_lines(guidance["method_guidance"]))
    lines.extend(["", "## 易错提醒"])
    lines.extend(_bullet_lines(guidance["common_pitfalls"]))
    lines.extend(["", "## 主题衔接建议"])
    for theme in lesson["theme_lessons"]:
        lines.extend(
            [
                "",
                "### {}".format(theme["title"]),
                "- 核心问题：{}".format("；".join(theme["core_questions"])),
                "- 核心证据：{}".format("；".join(theme["evidence"])),
            ]
        )
    lines.extend(["", "## 建议 QGIS 操作"])
    lines.extend(_render_qgis_section(lesson["qgis_guidance"]))
    return "\n".join(lines).strip() + "\n"


def _render_homework_markdown(lesson: Dict[str, Any]) -> str:
    meta = lesson["unit_meta"]
    homework = lesson["homework_pack"]
    lines: List[str] = [
        "# {}".format(homework["title"]),
        "",
        "## 适用单元",
        "- {}".format(meta["title"]),
        "",
    ]
    lines.extend(_render_question_section("## 基础题", homework["basic_questions"]))
    lines.extend([""])
    lines.extend(_render_question_section("## 提升题", homework["advanced_questions"]))
    lines.extend([""])
    lines.extend(_render_question_section("## 综合题", homework["integrated_questions"]))
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _render_review_markdown(lesson: Dict[str, Any]) -> str:
    meta = lesson["unit_meta"]
    review = lesson["review_pack"]
    lines: List[str] = [
        "# {}".format(review["title"]),
        "",
        "## 适用单元",
        "- {}".format(meta["title"]),
        "",
        "## 知识清单",
    ]
    lines.extend(_bullet_lines(review["knowledge_checklist"]))
    lines.extend(["", "## 高频判断点"])
    lines.extend(_bullet_lines(review["high_frequency_judgments"]))
    lines.extend(["", "## 易错点"])
    lines.extend(_bullet_lines(review["common_mistakes"]))
    lines.extend([""])
    lines.extend(_render_question_section("## 典型题与答案", review["example_questions"]))
    lines.extend(["", "## 单元回顾建议"])
    lines.extend(_bullet_lines(review["review_advice"]))
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _render_flagship_section(flagship: Dict[str, Any]) -> List[str]:
    lines = [
        "### {}".format(flagship["title"]),
        flagship["summary"],
        "",
        "#### 关键展示点",
    ]
    lines.extend(_bullet_lines(flagship["highlights"]))
    lines.extend(["", "#### 证据链"])
    lines.extend(_bullet_lines(flagship["evidence_chain"]))
    lines.extend(["", "#### 展示价值"])
    lines.extend(_bullet_lines(flagship["presentation_value"]))
    return lines


def _render_qgis_section(qgis_guidance: Dict[str, List[str]]) -> List[str]:
    lines = ["### 推荐图层"]
    lines.extend(_bullet_lines(qgis_guidance["recommended_layers"]))
    lines.extend(["", "### 推荐模板"])
    lines.extend(_bullet_lines(qgis_guidance["recommended_templates"]))
    lines.extend(["", "### 关键字段"])
    lines.extend(_bullet_lines(qgis_guidance["key_fields"]))
    lines.extend(["", "### 建议导出物"])
    lines.extend(_bullet_lines(qgis_guidance["suggested_exports"]))
    lines.extend(["", "### 说明"])
    lines.extend(_bullet_lines(qgis_guidance["notes"]))
    return lines


def _render_project_advantage_section(project_advantages: Dict[str, Any]) -> List[str]:
    lines = ["### {}".format(project_advantages["title"]), "#### 项目能力"]
    lines.extend(_bullet_lines(project_advantages["capabilities"]))
    lines.extend(["", "#### 相比常规教学的优势"])
    lines.extend(_bullet_lines(project_advantages["difference_from_normal_teaching"]))
    lines.extend(["", "#### 答辩展示提示"])
    lines.extend(_bullet_lines(project_advantages["showcase_tips"]))
    return lines


def _render_question_section(title: str, questions: List[Dict[str, str]]) -> List[str]:
    lines = [title]
    for index, item in enumerate(questions, start=1):
        lines.extend(
            [
                "",
                "### 题目 {}".format(index),
                "- 题目：{}".format(item["prompt"]),
                "- 参考答案：{}".format(item["answer"]),
                "- 解析：{}".format(item["analysis"]),
            ]
        )
    return lines


def _named_bullet_section(title: str, items: List[str]) -> List[str]:
    return [title] + _bullet_lines(items)


def _bullet_lines(items: Iterable[str]) -> List[str]:
    return ["- {}".format(item) for item in items]


def _markdown_to_paragraphs(markdown_text: str) -> List[Dict[str, str]]:
    paragraphs: List[Dict[str, str]] = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            paragraphs.append({"style": "Normal", "text": ""})
            continue
        if line.startswith("###### "):
            paragraphs.append({"style": "Heading4", "text": line[7:].strip()})
        elif line.startswith("##### "):
            paragraphs.append({"style": "Heading4", "text": line[6:].strip()})
        elif line.startswith("#### "):
            paragraphs.append({"style": "Heading4", "text": line[5:].strip()})
        elif line.startswith("### "):
            paragraphs.append({"style": "Heading3", "text": line[4:].strip()})
        elif line.startswith("## "):
            paragraphs.append({"style": "Heading2", "text": line[3:].strip()})
        elif line.startswith("# "):
            paragraphs.append({"style": "Heading1", "text": line[2:].strip()})
        elif line.startswith("- "):
            paragraphs.append({"style": "Normal", "text": "- {}".format(line[2:].strip())})
        elif line.startswith("  - "):
            paragraphs.append({"style": "Normal", "text": "  - {}".format(line[4:].strip())})
        else:
            paragraphs.append({"style": "Normal", "text": line})
    return paragraphs


def _docx_content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def _docx_root_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def _docx_document_relationships() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""


def _docx_app_properties() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>GeoBot</Application>
</Properties>
"""


def _docx_core_properties() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>GeoBot Lesson Package</dc:title>
  <dc:creator>GeoBot</dc:creator>
</cp:coreProperties>
"""


def _docx_styles() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr><w:b/><w:sz w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr><w:b/><w:sz w:val="28"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr><w:b/><w:sz w:val="24"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading4">
    <w:name w:val="heading 4"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr><w:b/><w:sz w:val="22"/></w:rPr>
  </w:style>
</w:styles>
"""


def _docx_document(paragraphs: List[Dict[str, str]]) -> str:
    body = []
    for item in paragraphs:
        text = escape(item["text"])
        style = item["style"]
        runs = '<w:r><w:t xml:space="preserve">{}</w:t></w:r>'.format(text if text else "")
        body.append(
            '<w:p><w:pPr><w:pStyle w:val="{}"/></w:pPr>{}</w:p>'.format(
                escape(style),
                runs,
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>{}<w:sectPr/></w:body></w:document>'.format("".join(body))
    )
