import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from geobot_runtime.lesson_ppt_local import (
    build_ppt_scenario,
    load_presentation_styles,
    render_document_package,
    render_lesson_markdown,
    resolve_presentation_style,
    summarize_package_contract,
    validate_lesson_blueprint,
    write_docx_from_markdown,
)


def sample_blueprint_payload():
    return {
        "summary": "Prepared lesson blueprint.",
        "notes": "",
        "package_contract": {
            "package_type": "unit_teaching_package",
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
                "min_count": 1,
                "required_fields": [
                    "theme_id",
                    "title",
                    "focus",
                    "periods",
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
                "expected_module_ids": ["theme1"],
                "recommended_module_roles": ["population_distribution"],
            },
            "document_outputs": {
                "lesson_plan": True,
                "guidance": True,
                "homework": True,
                "review": True,
            },
            "presentation_requirements": {
                "enabled": True,
                "min_slides": 1,
                "required_page_families": ["cover"],
            },
            "completion_checks": ["Provide a complete lesson package."],
        },
        "lesson_payload": {
            "unit_meta": {
                "title": "高中地理必修二《人口》单元教学设计",
                "audience": "高中一年级",
                "course": "高中地理必修二",
                "grade": "高中一年级",
                "time_allocation": "6 课时",
                "unit_overview": "围绕人口分布、迁移和合理容量组织教学成果包。",
                "showcase_positioning": "面向答辩展示与教学落地。",
            },
            "curriculum_requirements": ["结合地图和区域案例认识人口地理现象及其影响。"],
            "discipline_literacy_targets": {
                "human_earth_coordination": ["形成人口与区域环境协调发展的认识。"],
                "regional_cognition": ["从区域差异视角理解人口问题。"],
                "comprehensive_thinking": ["综合分析人口分布和迁移。"],
                "geographical_practice": ["借助地图和图表组织表达。"],
            },
            "material_analysis": ["教材内容适合构建空间差异与流动主线。"],
            "student_analysis": ["学生具备基础概念，但证据链组织仍需支架。"],
            "unit_objectives": {
                "knowledge_and_skills": ["掌握人口分布与迁移的核心概念。"],
                "process_and_methods": ["通过地图和图表组织证据分析。"],
                "values": ["认识人口与环境协调发展的重要性。"],
            },
            "key_and_difficult_points": {
                "key_points": ["人口空间分布格局", "人口迁移影响"],
                "difficult_points": ["用综合因素解释人口现象"],
            },
            "assessment_design": {
                "formative": ["课堂提问与任务单评价。"],
                "summative": ["单元作业与复习检测。"],
            },
            "modules": [
                {
                    "theme_id": "theme1",
                    "title": "主题 1 人口分布",
                    "focus": "胡焕庸线与人口空间差异",
                    "periods": "2 课时",
                    "core_questions": ["为什么人口空间分布极不均衡？"],
                    "teaching_objectives": ["能够结合地图解释人口分布差异。"],
                    "evidence": ["人口分布图", "人口密度图"],
                    "teaching_process": [
                        {
                            "stage": "导入",
                            "duration": "10 分钟",
                            "teacher_activity": ["抛出人口分布差异问题"],
                            "student_activity": ["观察地图并提出判断"],
                            "goal": "建立单元核心问题",
                            "assessment": ["课堂提问"],
                        }
                    ],
                    "activities": ["读图判断"],
                    "evaluation_points": ["能用地图证据解释人口差异"],
                    "summary": ["梳理人口空间差异与影响因素。"],
                    "board_plan": ["人口分布", "胡焕庸线", "影响因素"],
                    "homework": ["整理主题 1 知识结构。"],
                    "reflection": ["强化证据链表达。"],
                }
            ],
            "guidance_pack": {
                "title": "人口单元导学建议",
                "preclass_tasks": ["预习教材并梳理三大主题。"],
                "inclass_inquiry_tasks": ["结合地图证据解释人口差异。"],
                "method_guidance": ["先看格局，再析成因。"],
                "common_pitfalls": ["只背结论，不会解释。"],
            },
            "homework_pack": {
                "title": "人口单元分层作业",
                "basic_questions": [{"prompt": "说出人口单元的三大主题。", "answer": "人口分布、人口迁移、人口合理容量。", "analysis": "先建立主题结构。"}],
                "advanced_questions": [{"prompt": "说明人口迁移对区域发展的影响。", "answer": "人口迁移会影响劳动力供给和区域结构。", "analysis": "回答要体现双向影响。"}],
                "integrated_questions": [{"prompt": "概述胡焕庸线的教学价值。", "answer": "它是解释人口格局和迁移趋势的重要线索。", "analysis": "应联系空间差异与时代变化。"}],
            },
            "review_pack": {
                "title": "人口单元复习材料",
                "knowledge_checklist": ["人口分布", "人口迁移", "合理容量"],
                "high_frequency_judgments": ["人口分布与自然条件密切相关。"],
                "common_mistakes": ["混淆总人口和人口密度。"],
                "example_questions": [{"prompt": "说明人口合理容量与资源环境的关系。", "answer": "它受资源、环境和技术条件共同制约。", "analysis": "答题时要体现综合性。"}],
                "review_advice": ["按主题梳理概念、规律、原因和案例。"],
            },
            "flagship_storyline": {
                "title": "胡焕庸线与当代人口流动",
                "summary": "串联人口分布与迁移两大主题。",
                "highlights": ["空间差异", "流向判断"],
                "evidence_chain": ["人口分布图", "人口迁移图"],
                "presentation_value": ["形成强主线叙事"],
            },
            "qgis_guidance": {
                "recommended_layers": ["china_provinces_population.geojson"],
                "recommended_templates": ["population_change_comparison"],
                "key_fields": ["population", "density"],
                "suggested_exports": ["Theme 1 地图"],
                "notes": ["后续由 QGIS-only 模式执行。"],
            },
            "project_advantages": {
                "title": "GeoBot 项目特色与优势",
                "capabilities": ["从教学意图生成完整成果包。"],
                "difference_from_normal_teaching": ["不再手工拼接教案和 PPT。"],
                "showcase_tips": ["答辩时先讲主线，再讲成果包。"],
            },
        },
        "slide_contract": [
            {
                "slide_id": "cover",
                "title": "人口单元答辩展示",
                "subtitle": "围绕分布、迁移与合理容量构建整套展示",
                "page_goal": "建立展示主线",
                "core_message": "人口单元展示要围绕空间差异与人口流动展开。",
                "evidence_type": "process",
                "recommended_visual": "cover",
                "speaker_note": "先交代单元结构和展示主线。",
                "supporting_points": ["主题 1", "主题 2", "主题 3"],
                "hero_metrics": [{"label": "主题", "value": "3"}],
                "expected_page_family": "cover",
            }
        ],
    }


class LessonPptLocalTest(unittest.TestCase):
    def test_validate_and_render_document_package(self):
        blueprint = validate_lesson_blueprint(sample_blueprint_payload())
        docs = render_document_package(blueprint)
        self.assertIn("# 高中地理必修二《人口》单元教学设计", docs["lesson_plan"])
        self.assertIn("## 课程标准要求", docs["lesson_plan"])
        self.assertIn("## 建议 QGIS 操作", docs["lesson_plan"])
        self.assertIn("# 人口单元导学建议", docs["guidance"])
        self.assertIn("# 人口单元分层作业", docs["homework"])
        self.assertIn("# 人口单元复习材料", docs["review"])

    def test_render_document_package_respects_contract_outputs(self):
        payload = sample_blueprint_payload()
        payload["package_contract"]["document_outputs"] = {
            "lesson_plan": True,
            "guidance": False,
            "homework": False,
            "review": False,
        }
        blueprint = validate_lesson_blueprint(payload)
        docs = render_document_package(blueprint)
        self.assertIn("lesson_plan", docs)
        self.assertNotIn("guidance", docs)
        self.assertNotIn("homework", docs)
        self.assertNotIn("review", docs)

    def test_validate_lesson_blueprint_enforces_contract_module_count(self):
        payload = sample_blueprint_payload()
        payload["package_contract"]["module_requirements"]["min_count"] = 2
        with self.assertRaises(ValueError):
            validate_lesson_blueprint(payload)

    def test_render_lesson_markdown_returns_main_design(self):
        blueprint = validate_lesson_blueprint(sample_blueprint_payload())
        markdown = render_lesson_markdown(blueprint)
        self.assertIn("## GeoBot 项目特色与优势", markdown)
        self.assertIn("### 主题 1 人口分布", markdown)

    def test_write_docx_from_markdown_creates_word_package(self):
        markdown = "# 标题\n\n## 小节\n- 内容\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "lesson_plan.docx"
            write_docx_from_markdown(markdown, output_path)
            self.assertTrue(output_path.exists())
            with zipfile.ZipFile(output_path) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("标题", document_xml)
            self.assertIn("内容", document_xml)

    def test_build_ppt_scenario_maps_supporting_points_to_bullets(self):
        blueprint = validate_lesson_blueprint(sample_blueprint_payload())
        scenario = build_ppt_scenario(blueprint, "data_analysis", "deck_demo")
        self.assertEqual(scenario["style_family"], "data_analysis")
        self.assertEqual(scenario["slides"][0]["bullets"], ["主题 1", "主题 2", "主题 3"])

    def test_summarize_package_contract_returns_human_readable_items(self):
        blueprint = validate_lesson_blueprint(sample_blueprint_payload())
        summary = summarize_package_contract(blueprint)
        self.assertTrue(any("成果包类型" in item for item in summary))
        self.assertTrue(any("模块要求" in item for item in summary))

    def test_load_and_resolve_presentation_styles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "assets" / "design_system" / "registries" / "style_families.json"
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                json.dumps(
                    {
                        "style_families": [
                            {"id": "data_analysis", "label": "Data Analysis", "theme_id": "data_analysis"},
                            {"id": "minimal", "label": "Minimal", "theme_id": "minimal"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertEqual(len(load_presentation_styles(root)), 2)
            self.assertEqual(resolve_presentation_style("minimal", root), "minimal")
            self.assertEqual(resolve_presentation_style("unknown", root), "data_analysis")


if __name__ == "__main__":
    unittest.main()
