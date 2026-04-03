from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .config import RuntimeConfig
from .qgis_bridge import QgisBridgeClient


TEMPLATE_SPECS = {
    "population_distribution": {
        "tool_name": "create_population_distribution_map",
        "title": "Population Distribution Map",
        "file_stub": "population_distribution_map",
        "description": "Build a choropleth map for provincial or municipal population data.",
        "sample_payload": {
            "layer_name": "china_population",
            "value_field": "population",
        },
    },
    "population_density": {
        "tool_name": "create_population_density_map",
        "title": "Population Density Map",
        "file_stub": "population_density_map",
        "description": "Create a density or heatmap layer from point or polygon population data.",
        "sample_payload": {
            "layer_name": "china_population_points",
            "weight_field": "population",
        },
    },
    "population_migration": {
        "tool_name": "create_population_migration_map",
        "title": "Population Migration Map",
        "file_stub": "population_migration_map",
        "description": "Create a migration flow map from line data or origin and destination layers.",
        "sample_payload": {
            "line_layer_name": "migration_flows",
            "width_field": "value",
        },
    },
    "hu_line_comparison": {
        "tool_name": "create_hu_line_comparison_map",
        "title": "Hu Line Comparison Map",
        "file_stub": "hu_line_comparison_map",
        "description": "Compare the classic Hu Huanyong line with a line fitted from current data.",
        "sample_payload": {
            "layer_name": "china_population",
            "weight_field": "population",
        },
    },
}


class TemplateExecutor:
    def __init__(self, config: RuntimeConfig, qgis: QgisBridgeClient):
        self.config = config
        self.qgis = qgis

    def execute(self, project_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if template_id not in TEMPLATE_SPECS:
            raise ValueError(f"Unknown template: {template_id}")

        spec = TEMPLATE_SPECS[template_id]
        output_path = self._build_output_path(project_id, spec["file_stub"])
        params = dict(payload)
        params.setdefault("auto_layout", True)
        params.setdefault("title", spec["title"])
        params.setdefault("layout_name", f"GeoBot_{project_id[:8]}")
        params["export_path"] = str(output_path)

        response = self.qgis.call(spec["tool_name"], **params)
        if response.get("status") != "success":
            raise RuntimeError(response.get("message", f"{template_id} failed"))

        return {
            "template_id": template_id,
            "title": spec["title"],
            "tool_name": spec["tool_name"],
            "response": response,
            "export_path": str(output_path),
        }

    def list_templates(self) -> Dict[str, Any]:
        items = []
        for template_id, spec in TEMPLATE_SPECS.items():
            items.append(
                {
                    "template_id": template_id,
                    "title": spec["title"],
                    "description": spec["description"],
                    "tool_name": spec["tool_name"],
                    "sample_payload": spec["sample_payload"],
                }
            )
        return {"items": items}

    def build_output_path(self, project_id: str, template_id: str) -> Path:
        if template_id not in TEMPLATE_SPECS:
            raise ValueError(f"Unknown template: {template_id}")
        spec = TEMPLATE_SPECS[template_id]
        return self._build_output_path(project_id, spec["file_stub"])

    def _build_output_path(self, project_id: str, file_stub: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.config.project_output_dir(project_id) / f"{file_stub}_{timestamp}.png"
