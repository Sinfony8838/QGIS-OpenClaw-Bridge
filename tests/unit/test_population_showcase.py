import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from geobot_runtime.config import RuntimeConfig
from geobot_runtime.population_unit import (
    PopulationShowcase,
    build_population_dataset_manifest,
    build_population_knowledge_bundle,
    build_population_preflight,
)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_docx_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:body></w:document>'.format(text)
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)


class PopulationShowcaseTest(unittest.TestCase):
    def build_knowledge_root(self, temp_dir: str) -> Path:
        knowledge_root = Path(temp_dir) / "knowledge" / "geography" / "population"
        write_docx_text(knowledge_root / "population_summary.docx", "人口单元总结")
        write_docx_text(knowledge_root / "teaching_design" / "theme1_population_distribution_design.docx", "主题1 人口分布 教学设计")
        write_docx_text(knowledge_root / "teaching_design" / "theme2_population_migration_design.docx", "主题2 人口迁移 教学设计")
        write_docx_text(knowledge_root / "teaching_design" / "theme3_population_capacity_design.docx", "主题3 人口合理容量 教学设计")
        write_docx_text(knowledge_root / "guidance_on_learning" / "population_guidance.docx", "导学资料")
        write_docx_text(knowledge_root / "homework" / "set1" / "population_homework.docx", "作业资料")
        write_docx_text(knowledge_root / "review_materials" / "population_review.docx", "复习资料")
        write_text(knowledge_root / "example_of_courseware" / "population_courseware.md", "# 课件参考")
        write_text(
            knowledge_root / "test_data" / "china_provinces_population.geojson",
            json.dumps(
                {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "A", "population": 100}, "geometry": None}]},
                ensure_ascii=False,
            ),
        )
        write_text(
            knowledge_root / "test_data" / "china_population_sample.csv",
            "city_name,population,longitude,latitude,province\nA,100,100,30,P1\n",
        )
        write_text(
            knowledge_root / "test_data" / "china_migration_sample.csv",
            "from_city,to_city,migration_count\nA,B,10\n",
        )
        write_text(
            knowledge_root / "test_data" / "province_population_2020.csv",
            "省名,人口_万\n甲省,1000\n",
        )
        write_text(
            knowledge_root / "test_data" / "world_countries.geojson",
            json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "World A"}, "geometry": None}]}, ensure_ascii=False),
        )
        return knowledge_root

    def test_manifest_and_preflight_report_missing_rasters_and_world_attributes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_root = self.build_knowledge_root(temp_dir)
            manifest_path = Path(temp_dir) / "population_manifest.json"

            manifest = build_population_dataset_manifest(knowledge_root, manifest_path)
            preflight = build_population_preflight(manifest)

            self.assertEqual(manifest["dataset_count"], len(manifest["datasets"]))
            self.assertIn("population_grid_2000", preflight["checks"][1]["dataset_ids"])
            self.assertEqual(preflight["checks"][1]["status"], "error")
            world_check = next(check for check in preflight["checks"] if check["check_id"] == "world_population_attributes")
            self.assertEqual(world_check["status"], "warning")
            self.assertIn("flagship", preflight["theme_readiness"])

    def test_knowledge_bundle_collects_all_reference_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_root = self.build_knowledge_root(temp_dir)
            bundle = build_population_knowledge_bundle(knowledge_root)

            self.assertEqual(bundle["source_counts"]["theme1_refs"], 1)
            self.assertEqual(bundle["source_counts"]["theme2_refs"], 1)
            self.assertEqual(bundle["source_counts"]["theme3_refs"], 1)
            self.assertEqual(bundle["source_counts"]["guidance_refs"], 1)
            self.assertEqual(bundle["source_counts"]["homework_refs"], 1)
            self.assertEqual(bundle["source_counts"]["review_refs"], 1)
            self.assertEqual(bundle["source_counts"]["courseware_refs"], 1)
            self.assertEqual(bundle["source_counts"]["summary_refs"], 1)
            self.assertEqual(len(bundle["module_refs"]), 3)
            self.assertIn("人口单元总结", bundle["summary_refs"][0]["excerpt"])

    def test_population_showcase_default_artifacts_match_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            knowledge_root = self.build_knowledge_root(temp_dir)
            config = RuntimeConfig(app_root=Path(temp_dir) / "app", population_knowledge_root=knowledge_root)
            showcase = PopulationShowcase(config)

            artifacts = showcase.default_artifacts(Path(temp_dir) / "outputs", "job_demo")

            self.assertEqual(artifacts["pptx"]["artifact_type"], "pptx")
            self.assertEqual(artifacts["theme1_map"]["artifact_type"], "map_export")
            self.assertTrue(artifacts["lesson_plan_docx"]["path"].endswith(".docx"))
            self.assertTrue(artifacts["guidance"]["path"].endswith(".md"))
            self.assertTrue(artifacts["homework_docx"]["path"].endswith(".docx"))
            self.assertTrue(artifacts["review"]["path"].endswith(".md"))
            self.assertTrue(artifacts["deck_scenario"]["path"].endswith(".scenario.json"))
            self.assertEqual(showcase.package_profile()["profile_id"], "population_unit")


if __name__ == "__main__":
    unittest.main()
