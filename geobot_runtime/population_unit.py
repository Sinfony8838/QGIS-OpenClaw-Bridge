from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

from .lesson_ppt_local import DEFAULT_PRESENTATION_STYLE, load_presentation_styles, resolve_presentation_style
from .models import utc_now


POPULATION_SHOWCASE_PRESET = (
    "请为高中地理必修二《人口》单元生成完整教学成果包与答辩 PPT，"
    "综合人口知识库中的教学设计、导学、作业、复习和课件资料，"
    "围绕“胡焕庸线 + 当代人口流动”构建旗舰主线，并在主文档中附上“建议 QGIS 操作”部分。"
)

WORLD_POPULATION_FIELDS = ("population", "pop_est", "pop", "density", "pop2020", "pop_2020")
CAPACITY_FIELDS = ("capacity", "carrying_capacity", "reasonable_capacity", "pressure", "score")

KNOWLEDGE_CATEGORY_SPECS: Dict[str, Dict[str, Any]] = {
    "theme1_refs": {"root": "teaching_design", "matchers": ("theme1", "distribution"), "label": "Theme 1 references"},
    "theme2_refs": {"root": "teaching_design", "matchers": ("theme2", "migration"), "label": "Theme 2 references"},
    "theme3_refs": {"root": "teaching_design", "matchers": ("theme3", "capacity"), "label": "Theme 3 references"},
    "guidance_refs": {"root": "guidance_on_learning", "matchers": (), "label": "Learning guidance references"},
    "homework_refs": {"root": "homework", "matchers": (), "label": "Homework references"},
    "review_refs": {"root": "review_materials", "matchers": (), "label": "Review references"},
    "courseware_refs": {"root": "example_of_courseware", "matchers": (), "label": "Courseware references"},
    "summary_refs": {"root": "", "matchers": ("population_summary.docx",), "label": "Unit summary reference"},
}

POPULATION_PACKAGE_PROFILE: Dict[str, Any] = {
    "profile_id": "population_unit",
    "package_type": "unit_teaching_package",
    "suggested_module_roles": [
        "population_distribution",
        "population_migration",
        "population_capacity",
    ],
    "suggested_document_outputs": ["lesson_plan", "guidance", "homework", "review"],
    "suggested_required_sections": [
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
    "suggested_required_page_families": ["cover", "agenda", "comparison", "summary"],
    "flagship_storyline": "胡焕庸线 + 当代人口流动",
}

POPULATION_DATASET_SPECS: List[Dict[str, Any]] = [
    {"dataset_id": "main_textbook", "title": "Main Textbook", "relative_path": "main_textbook.pdf", "category": "knowledge_pdf", "required": False, "layer_role": "reference", "themes": ["theme1", "theme2", "theme3"]},
    {"dataset_id": "pep_reference", "title": "PEP Population Reference", "relative_path": "PEP.pdf", "category": "knowledge_pdf", "required": False, "layer_role": "reference", "themes": ["theme1", "theme2", "theme3"]},
    {"dataset_id": "population_summary", "title": "Population Unit Summary", "relative_path": "population_summary.docx", "category": "knowledge_doc", "required": True, "layer_role": "summary", "themes": ["theme1", "theme2", "theme3", "flagship"]},
    {"dataset_id": "theme1_teaching_design", "title": "Theme 1 Teaching Design", "relative_path": "teaching_design/theme1_population_distribution_design.docx", "category": "knowledge_doc", "required": True, "layer_role": "lesson_design", "themes": ["theme1", "flagship"]},
    {"dataset_id": "theme2_teaching_design", "title": "Theme 2 Teaching Design", "relative_path": "teaching_design/theme2_population_migration_design.docx", "category": "knowledge_doc", "required": True, "layer_role": "lesson_design", "themes": ["theme2", "flagship"]},
    {"dataset_id": "theme3_teaching_design", "title": "Theme 3 Teaching Design", "relative_path": "teaching_design/theme3_population_capacity_design.docx", "category": "knowledge_doc", "required": True, "layer_role": "lesson_design", "themes": ["theme3"]},
    {"dataset_id": "china_provinces_population", "title": "China Provinces Population", "relative_path": "test_data/china_provinces_population.geojson", "category": "gis_vector", "required": True, "year": 2020, "scale": "province", "expected_fields": ["name", "population"], "layer_role": "distribution_base", "themes": ["theme1", "flagship"]},
    {"dataset_id": "china_population_sample", "title": "China Population Sample Points", "relative_path": "test_data/china_population_sample.csv", "category": "gis_table", "required": True, "year": 2020, "scale": "city", "expected_fields": ["city_name", "population", "longitude", "latitude"], "layer_role": "density_points", "themes": ["theme1", "flagship"]},
    {"dataset_id": "china_migration_sample", "title": "China Migration Sample", "relative_path": "test_data/china_migration_sample.csv", "category": "gis_table", "required": True, "year": 2020, "scale": "province", "expected_fields": ["from_city", "to_city", "migration_count"], "layer_role": "migration_flow", "themes": ["theme2", "flagship"]},
    {"dataset_id": "province_population_2020", "title": "Province Population 2020", "relative_path": "test_data/province_population_2020.csv", "category": "gis_table", "required": True, "year": 2020, "scale": "province", "expected_fields": ["省名", "人口_万"], "layer_role": "support_table", "themes": ["theme1", "theme3"]},
    {"dataset_id": "world_countries", "title": "World Countries", "relative_path": "test_data/world_countries.geojson", "category": "gis_vector", "required": True, "scale": "country", "expected_fields": ["name"], "layer_role": "world_distribution", "themes": ["theme1"]},
    {"dataset_id": "population_grid_2000", "title": "China Population Grid 2000", "relative_path": "test_data/chn_pd_2000_1km.tif", "category": "gis_raster", "required": True, "year": 2000, "scale": "grid_1km", "layer_role": "population_raster", "themes": ["theme1", "flagship"]},
    {"dataset_id": "population_grid_2010", "title": "China Population Grid 2010", "relative_path": "test_data/chn_pd_2010_1km.tif", "category": "gis_raster", "required": True, "year": 2010, "scale": "grid_1km", "layer_role": "population_raster", "themes": ["theme1", "flagship"]},
    {"dataset_id": "population_grid_2020", "title": "China Population Grid 2020", "relative_path": "test_data/chn_pd_2020_1km.tif", "category": "gis_raster", "required": True, "year": 2020, "scale": "grid_1km", "layer_role": "population_raster", "themes": ["theme1", "flagship"]},
]


def _status_rank(status: str) -> int:
    return {"success": 0, "warning": 1, "error": 2}.get(status, 1)


def _merge_status(*statuses: str) -> str:
    if not statuses:
        return "warning"
    return max(statuses, key=_status_rank)


def _read_text_with_fallback(path: Path, encodings: Optional[List[str]] = None) -> str:
    for encoding in encodings or ["utf-8", "utf-8-sig", "gb18030"]:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_geojson_fields(path: Path) -> Dict[str, Any]:
    payload = json.loads(_read_text_with_fallback(path))
    features = payload.get("features", []) if isinstance(payload, dict) else []
    if not features:
        return {"fields": [], "feature_count": 0}
    properties = features[0].get("properties", {}) if isinstance(features[0], dict) else {}
    fields = list(properties.keys()) if isinstance(properties, dict) else []
    return {"fields": fields, "feature_count": len(features)}


def _read_csv_fields(path: Path) -> Dict[str, Any]:
    text = _read_text_with_fallback(path, encodings=["utf-8-sig", "utf-8", "gb18030"])
    reader = csv.DictReader(text.splitlines())
    fieldnames = list(reader.fieldnames or [])
    row_count = 0
    for _ in reader:
        row_count += 1
    return {"fields": fieldnames, "row_count": row_count}


def inspect_dataset(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".geojson":
        return _read_geojson_fields(path)
    if suffix == ".csv":
        return _read_csv_fields(path)
    return {}


def build_population_dataset_manifest(
    knowledge_root: Path,
    manifest_path: Path,
    showcase_mode: str = "population_unit",
) -> Dict[str, Any]:
    datasets: List[Dict[str, Any]] = []
    for spec in POPULATION_DATASET_SPECS:
        record = dict(spec)
        path = knowledge_root / spec["relative_path"]
        record["path"] = str(path)
        record["exists"] = path.exists()
        record["size_bytes"] = path.stat().st_size if path.exists() else 0
        record["fields"] = []
        record["missing_fields"] = list(spec.get("expected_fields", []))
        if path.exists():
            inspected = inspect_dataset(path)
            record.update(inspected)
            fields = [str(value) for value in inspected.get("fields", [])]
            lowered = {name.lower() for name in fields}
            record["fields"] = fields
            record["missing_fields"] = [field for field in spec.get("expected_fields", []) if field.lower() not in lowered]
        datasets.append(record)

    manifest = {
        "status": "success",
        "showcase_mode": showcase_mode,
        "generated_at": utc_now(),
        "knowledge_root": str(knowledge_root),
        "dataset_manifest_path": str(manifest_path),
        "dataset_count": len(datasets),
        "datasets": datasets,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_population_preflight(manifest: Dict[str, Any]) -> Dict[str, Any]:
    datasets = {item["dataset_id"]: item for item in manifest.get("datasets", [])}
    knowledge_root = Path(manifest.get("knowledge_root", ""))
    checks: List[Dict[str, Any]] = []

    def add_check(check_id: str, status: str, summary: str, detail: str = "", dataset_ids: Optional[List[str]] = None) -> None:
        checks.append({"check_id": check_id, "status": status, "summary": summary, "detail": detail, "dataset_ids": dataset_ids or []})

    add_check(
        "knowledge_root",
        "success" if knowledge_root.exists() else "error",
        "Population knowledge root is available." if knowledge_root.exists() else "Population knowledge root is missing.",
        str(knowledge_root),
    )

    raster_ids = ["population_grid_2000", "population_grid_2010", "population_grid_2020"]
    missing_rasters = [dataset_id for dataset_id in raster_ids if not datasets.get(dataset_id, {}).get("exists")]
    add_check(
        "population_raster_timeseries",
        "success" if not missing_rasters else "error",
        "Population raster time series is complete." if not missing_rasters else "Population raster time series is incomplete.",
        ", ".join(missing_rasters) if missing_rasters else "",
        dataset_ids=raster_ids,
    )

    province_layer = datasets.get("china_provinces_population", {})
    province_missing_fields = province_layer.get("missing_fields", [])
    add_check(
        "province_distribution_layer",
        "success" if province_layer.get("exists") and not province_missing_fields else "error",
        "Province-level population layer is ready." if province_layer.get("exists") and not province_missing_fields else "Province-level population layer is incomplete.",
        ", ".join(province_missing_fields),
        dataset_ids=["china_provinces_population"],
    )

    world_layer = datasets.get("world_countries", {})
    world_fields = {field.lower() for field in world_layer.get("fields", [])}
    has_world_population_fields = bool(world_fields.intersection(WORLD_POPULATION_FIELDS))
    add_check(
        "world_population_attributes",
        "success" if world_layer.get("exists") and has_world_population_fields else "warning",
        "World population attributes are available." if world_layer.get("exists") and has_world_population_fields else "World-scale vector exists but lacks population or density attributes.",
        ", ".join(sorted(world_fields)),
        dataset_ids=["world_countries"],
    )

    migration_table = datasets.get("china_migration_sample", {})
    migration_rows = int(migration_table.get("row_count", 0) or 0)
    migration_status = "error" if not migration_table.get("exists") else "warning" if migration_rows < 20 else "success"
    add_check(
        "migration_od_depth",
        migration_status,
        "Migration OD sample is ready for showcase." if migration_status == "success" else "Migration OD data is only sufficient for prototype showcase." if migration_status == "warning" else "Migration OD data is missing.",
        str(migration_rows),
        dataset_ids=["china_migration_sample"],
    )

    city_points = datasets.get("china_population_sample", {})
    city_missing_fields = city_points.get("missing_fields", [])
    add_check(
        "density_points",
        "success" if city_points.get("exists") and not city_missing_fields else "warning",
        "City sample points can support density and chart prototypes." if city_points.get("exists") and not city_missing_fields else "City sample points are incomplete for density and chart prototypes.",
        ", ".join(city_missing_fields),
        dataset_ids=["china_population_sample"],
    )

    capacity_ready = False
    for dataset in manifest.get("datasets", []):
        if "theme3" not in dataset.get("themes", []):
            continue
        fields = {field.lower() for field in dataset.get("fields", [])}
        if dataset.get("exists") and fields.intersection(CAPACITY_FIELDS):
            capacity_ready = True
            break
    add_check(
        "capacity_case_data",
        "success" if capacity_ready else "warning",
        "Capacity-specific GIS data is ready." if capacity_ready else "Theme 3 only has teaching docs and still lacks GIS-ready capacity data.",
        "",
        dataset_ids=["theme3_teaching_design", "province_population_2020"],
    )

    theme_readiness = {
        "theme1": _merge_status(
            "success" if province_layer.get("exists") and not province_missing_fields else "error",
            "success" if city_points.get("exists") and not city_missing_fields else "warning",
            "success" if not missing_rasters else "warning",
            "success" if world_layer.get("exists") and has_world_population_fields else "warning",
        ),
        "theme2": _merge_status("success" if migration_status != "error" else "error", migration_status),
        "theme3": "success" if capacity_ready else "warning",
    }
    theme_readiness["flagship"] = _merge_status(theme_readiness["theme1"], theme_readiness["theme2"])

    overall_status = "success"
    for check in checks:
        overall_status = _merge_status(overall_status, check["status"])

    required_missing = sum(
        1
        for dataset in manifest.get("datasets", [])
        if dataset.get("required") and (not dataset.get("exists") or dataset.get("missing_fields"))
    )
    ready_themes = [theme for theme, status in theme_readiness.items() if status != "error"]
    headline = "Population showcase preflight: {}. Ready themes={}/4, required gaps={}.".format(overall_status, len(ready_themes), required_missing)
    return {
        "status": overall_status,
        "headline": headline,
        "knowledge_root": manifest.get("knowledge_root", ""),
        "dataset_manifest_path": manifest.get("dataset_manifest_path", ""),
        "checks": checks,
        "required_missing_count": required_missing,
        "theme_readiness": theme_readiness,
        "ready_themes": ready_themes,
    }


def build_population_knowledge_bundle(knowledge_root: Path) -> Dict[str, Any]:
    bundle: Dict[str, Any] = {"knowledge_root": str(knowledge_root), "source_counts": {}}
    total_refs = 0
    for key, spec in KNOWLEDGE_CATEGORY_SPECS.items():
        refs = _collect_knowledge_refs(knowledge_root, spec["root"], spec["matchers"])
        bundle[key] = refs
        bundle["source_counts"][key] = len(refs)
        total_refs += len(refs)
    bundle["module_refs"] = [
        {"module_id": "population_distribution", "refs": bundle.get("theme1_refs", [])},
        {"module_id": "population_migration", "refs": bundle.get("theme2_refs", [])},
        {"module_id": "population_capacity", "refs": bundle.get("theme3_refs", [])},
    ]
    bundle["source_counts"]["module_refs"] = sum(len(item["refs"]) for item in bundle["module_refs"])
    bundle["total_refs"] = total_refs
    return bundle


def build_population_package_profile() -> Dict[str, Any]:
    return json.loads(json.dumps(POPULATION_PACKAGE_PROFILE, ensure_ascii=False))


def _collect_knowledge_refs(knowledge_root: Path, root_name: str, matchers: tuple) -> List[Dict[str, Any]]:
    if root_name:
        root = knowledge_root / root_name
        if not root.exists():
            return []
        candidates = sorted(path for path in root.rglob("*") if path.is_file())
    else:
        candidates = [knowledge_root / matcher for matcher in matchers if (knowledge_root / matcher).exists()]

    refs: List[Dict[str, Any]] = []
    lowered_matchers = tuple(matcher.lower() for matcher in matchers)
    for path in candidates:
        path_key = path.name.lower()
        if lowered_matchers and not any(matcher in path_key for matcher in lowered_matchers):
            continue
        refs.append(
            {
                "title": path.stem.replace("_", " "),
                "path": str(path),
                "source_type": path.suffix.lower().lstrip("."),
                "excerpt": _extract_reference_excerpt(path),
            }
        )
    return refs


def _extract_reference_excerpt(path: Path, max_chars: int = 360) -> str:
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix == ".docx":
            text = _extract_docx_text(path)
        elif suffix in {".md", ".txt", ".json", ".csv"}:
            text = _read_text_with_fallback(path)
        else:
            text = path.stem
    except Exception:
        text = path.stem
    compact = " ".join(text.split())
    return compact[:max_chars]


def _extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except zipfile.BadZipFile:
        return _read_text_with_fallback(path)
    root = ElementTree.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    texts = [node.text or "" for node in root.findall(".//w:t", namespace)]
    return "".join(texts)


class PopulationShowcase:
    def __init__(self, config):
        self.config = config

    def manifest(self) -> Dict[str, Any]:
        return build_population_dataset_manifest(
            knowledge_root=Path(self.config.population_knowledge_root),
            manifest_path=Path(self.config.population_dataset_manifest_path),
            showcase_mode=self.config.population_showcase_mode,
        )

    def knowledge_bundle(self) -> Dict[str, Any]:
        return build_population_knowledge_bundle(Path(self.config.population_knowledge_root))

    def package_profile(self) -> Dict[str, Any]:
        return build_population_package_profile()

    def preflight(self) -> Dict[str, Any]:
        return build_population_preflight(self.manifest())

    def health_payload(self) -> Dict[str, Any]:
        return {
            "showcase_mode": self.config.population_showcase_mode,
            "knowledge_root": str(self.config.population_knowledge_root),
            "dataset_manifest_path": str(self.config.population_dataset_manifest_path),
            "status": "success",
            "headline": "Population unit assets are linked.",
            "theme_readiness": {},
            "required_missing_count": 0,
        }

    def describe(self) -> Dict[str, Any]:
        manifest = self.manifest()
        knowledge_bundle = self.knowledge_bundle()
        return {
            "status": "success",
            "showcase_mode": self.config.population_showcase_mode,
            "knowledge_root": str(self.config.population_knowledge_root),
            "dataset_manifest_path": str(self.config.population_dataset_manifest_path),
            "preset_message": POPULATION_SHOWCASE_PRESET,
            "default_presentation_style": resolve_presentation_style(DEFAULT_PRESENTATION_STYLE, Path(self.config.ppt_studio_skill_dir)),
            "presentation_styles": load_presentation_styles(Path(self.config.ppt_studio_skill_dir)),
            "recommended_templates": ["population_change_comparison", "population_migration", "population_capacity_dashboard"],
            "manifest": manifest,
            "knowledge_bundle_counts": knowledge_bundle.get("source_counts", {}),
            "package_profile": self.package_profile(),
        }

    def default_artifacts(self, output_dir: Path, job_id: str) -> Dict[str, Dict[str, Any]]:
        unit_design_md = output_dir / "population_unit_design_{}.md".format(job_id)
        unit_design_docx = output_dir / "population_unit_design_{}.docx".format(job_id)
        guidance_md = output_dir / "population_guidance_{}.md".format(job_id)
        guidance_docx = output_dir / "population_guidance_{}.docx".format(job_id)
        homework_md = output_dir / "population_homework_{}.md".format(job_id)
        homework_docx = output_dir / "population_homework_{}.docx".format(job_id)
        review_md = output_dir / "population_review_{}.md".format(job_id)
        review_docx = output_dir / "population_review_{}.docx".format(job_id)
        deck_path = output_dir / "population_flagship_deck_{}.pptx".format(job_id)
        deck_scenario_path = output_dir / "population_flagship_deck_{}.scenario.json".format(job_id)
        theme1_path = output_dir / "theme1_population_distribution_{}.png".format(job_id)
        theme2_path = output_dir / "theme2_population_migration_{}.png".format(job_id)
        theme3_path = output_dir / "theme3_population_capacity_{}.png".format(job_id)
        return {
            "lesson_plan": {"artifact_type": "lesson_plan", "title": "Population Unit Teaching Design", "path": str(unit_design_md), "metadata": {"showcase_priority": 60}},
            "lesson_plan_docx": {"artifact_type": "docx", "title": "Population Unit Teaching Design (Word)", "path": str(unit_design_docx), "metadata": {"showcase_priority": 62}},
            "guidance": {"artifact_type": "markdown", "title": "Population Learning Guidance", "path": str(guidance_md), "metadata": {"showcase_priority": 70}},
            "guidance_docx": {"artifact_type": "docx", "title": "Population Learning Guidance (Word)", "path": str(guidance_docx), "metadata": {"showcase_priority": 72}},
            "homework": {"artifact_type": "markdown", "title": "Population Homework Package", "path": str(homework_md), "metadata": {"showcase_priority": 80}},
            "homework_docx": {"artifact_type": "docx", "title": "Population Homework Package (Word)", "path": str(homework_docx), "metadata": {"showcase_priority": 82}},
            "review": {"artifact_type": "markdown", "title": "Population Review Package", "path": str(review_md), "metadata": {"showcase_priority": 90}},
            "review_docx": {"artifact_type": "docx", "title": "Population Review Package (Word)", "path": str(review_docx), "metadata": {"showcase_priority": 92}},
            "pptx": {"artifact_type": "pptx", "title": "Population Flagship Deck", "path": str(deck_path), "metadata": {"showcase_priority": 10}},
            "deck_scenario": {"artifact_type": "json", "title": "Population Flagship Deck Scenario", "path": str(deck_scenario_path), "metadata": {"showcase_priority": 95}},
            "map_export": {"artifact_type": "map_export", "title": "Population Theme 1 Showcase Map", "path": str(theme1_path), "metadata": {"showcase_priority": 30}},
            "theme1_map": {"artifact_type": "map_export", "title": "Theme 1 Population Distribution Map", "path": str(theme1_path), "metadata": {"showcase_priority": 30}},
            "theme2_map": {"artifact_type": "map_export", "title": "Theme 2 Population Migration Map", "path": str(theme2_path), "metadata": {"showcase_priority": 40}},
            "theme3_map": {"artifact_type": "map_export", "title": "Theme 3 Population Capacity Map", "path": str(theme3_path), "metadata": {"showcase_priority": 50}},
        }
