from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

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
            "label_field": "name",
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
        "title": "Population Migration Map",
        "file_stub": "population_migration_map",
        "description": "Create a migration flow showcase from OD layers or an existing migration line layer.",
        "sample_payload": {
            "line_layer_name": "migration_flows",
            "width_field": "migration_count",
        },
        "executor": "_execute_population_migration",
    },
    "hu_line_comparison": {
        "tool_name": "create_hu_line_comparison_map",
        "title": "Hu Line Comparison Map",
        "file_stub": "hu_line_comparison_map",
        "description": "Compare the classic Hu Huanyong line with a line fitted from current data.",
        "sample_payload": {
            "layer_name": "china_population",
            "weight_field": "population",
            "label_field": "name",
        },
    },
    "population_change_comparison": {
        "title": "Population Change Comparison",
        "file_stub": "population_change_comparison",
        "description": "Compose a showcase map with distribution, density, Hu line comparison, and an embedded chart.",
        "sample_payload": {
            "layer_name": "china_population",
            "value_field": "population",
            "label_field": "name",
            "density_layer_name": "china_population_points",
            "density_weight_field": "population",
            "chart_category_field": "name",
            "chart_value_field": "population",
        },
        "executor": "_execute_population_change_comparison",
    },
    "population_capacity_dashboard": {
        "title": "Population Capacity Dashboard",
        "file_stub": "population_capacity_dashboard",
        "description": "Build a capacity-themed dashboard map with embedded comparison charts.",
        "sample_payload": {
            "layer_name": "province_capacity",
            "value_field": "capacity",
            "label_field": "name",
            "chart_category_field": "name",
            "chart_value_field": "capacity",
        },
        "executor": "_execute_population_capacity_dashboard",
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
        custom_executor = spec.get("executor")
        if custom_executor:
            return getattr(self, custom_executor)(project_id, template_id, payload or {})

        output_path = self._build_output_path(project_id, spec["file_stub"])
        params = dict(payload or {})
        params.setdefault("auto_layout", True)
        params.setdefault("title", spec["title"])
        params.setdefault("layout_name", f"GeoBot_{project_id[:8]}")
        params["export_path"] = str(output_path)

        response = self._call_qgis(spec["tool_name"], **params)
        return {
            "template_id": template_id,
            "title": spec["title"],
            "tool_name": spec["tool_name"],
            "response": response,
            "export_path": str(output_path),
            "artifact_bundle": self._build_artifact_bundle(spec["title"], output_path),
        }

    def list_templates(self) -> Dict[str, Any]:
        items = []
        for template_id, spec in TEMPLATE_SPECS.items():
            items.append(
                {
                    "template_id": template_id,
                    "title": spec["title"],
                    "description": spec["description"],
                    "tool_name": spec.get("tool_name", spec.get("executor", "")),
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

    def _call_qgis(self, tool_name: str, **params: Any) -> Dict[str, Any]:
        response = self.qgis.call(tool_name, **params)
        if response.get("status") != "success":
            raise RuntimeError(response.get("message", f"{tool_name} failed"))
        return response

    def _extract_map_session(self, *responses: Dict[str, Any]) -> str:
        for response in responses:
            if response and response.get("map_session"):
                return str(response["map_session"])
        return ""

    def _build_artifact_bundle(
        self,
        title: str,
        export_path: Path,
        extras: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        bundle: Dict[str, Dict[str, Any]] = {
            "map_export": {
                "artifact_type": "map_export",
                "title": title,
                "path": str(export_path),
            }
        }
        if extras:
            bundle.update(extras)
        return bundle

    def _chart_artifact(
        self,
        response: Dict[str, Any],
        artifact_key: str,
        title: str,
        priority: int,
    ) -> Dict[str, Dict[str, Any]]:
        chart_path = str(response.get("artifacts", {}).get("chart_image", "")).strip()
        if not chart_path:
            return {}
        return {
            artifact_key: {
                "artifact_type": "image",
                "title": title,
                "path": chart_path,
                "metadata": {"showcase_priority": priority},
            }
        }

    def _first_non_empty(self, *values: Any) -> str:
        for value in values:
            if value:
                return str(value)
        return ""

    def _normalize_hidden_layers(self, hidden_layers: Any) -> Iterable[str]:
        if not hidden_layers:
            return []
        if isinstance(hidden_layers, str):
            return [hidden_layers]
        return [str(value) for value in hidden_layers if value]

    def _execute_population_migration(self, project_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        spec = TEMPLATE_SPECS[template_id]
        output_path = self._build_output_path(project_id, spec["file_stub"])
        title = payload.get("title", spec["title"])
        layout_name = payload.get("layout_name", f"GeoBot_{project_id[:8]}")
        legend_title = payload.get("legend_title", "Population Migration")
        hidden_layers = list(self._normalize_hidden_layers(payload.get("hidden_layers")))

        if payload.get("origins_layer") and payload.get("destinations_layer"):
            base_response = self._call_qgis(
                "create_population_migration_map",
                origins_layer=payload["origins_layer"],
                destinations_layer=payload["destinations_layer"],
                origin_id_field=payload.get("origin_id_field") or "origin_id",
                destination_id_field=payload.get("destination_id_field") or "destination_id",
                title=title,
                color=payload.get("color", "#d1495b"),
                auto_layout=False,
                layout_name=layout_name,
                map_session=payload.get("map_session"),
            )
            map_session = self._extract_map_session(base_response)
            artifact_bundle = self._build_artifact_bundle(spec["title"], output_path)

            if payload.get("origin_pop_field") and payload.get("destination_pop_field"):
                attraction_response = self._call_qgis(
                    "run_population_attraction_model",
                    origins_layer=payload["origins_layer"],
                    destinations_layer=payload["destinations_layer"],
                    origin_pop_field=payload["origin_pop_field"],
                    destination_pop_field=payload["destination_pop_field"],
                    beta=payload.get("beta", 2.0),
                    output_type="lines",
                    map_session=map_session,
                )
                map_session = self._extract_map_session(attraction_response, base_response)

                attraction_layer_name = self._first_non_empty(
                    attraction_response.get("layer_name"),
                    attraction_response.get("artifacts", {}).get("layer", {}).get("layer_name"),
                )
                if attraction_layer_name:
                    self._call_qgis(
                        "style_population_attraction_result",
                        layer_name=attraction_layer_name,
                        field=payload.get("attraction_field", "score"),
                        style_mode=payload.get("attraction_style_mode", "graduated"),
                        classes=payload.get("attraction_classes", 5),
                        color_ramp=payload.get("attraction_color_ramp", "Magma"),
                        map_session=map_session,
                    )

            flow_layer_name = self._first_non_empty(
                base_response.get("data", {}).get("flow_layer_name"),
                base_response.get("artifacts", {}).get("flow_layer", {}).get("layer_name"),
            )
            self._call_qgis(
                "auto_layout",
                title=title,
                layout_name=layout_name,
                map_session=map_session,
            )
            self._call_qgis(
                "customize_layout_legend",
                layout_name=layout_name,
                title=legend_title,
                layer_order=[value for value in [flow_layer_name, payload["origins_layer"], payload["destinations_layer"]] if value],
                hidden_layers=hidden_layers,
                map_session=map_session,
            )
            export_response = self._call_qgis(
                "export_map",
                file_path=str(output_path),
                layout_name=layout_name,
                map_session=map_session,
            )
            return {
                "template_id": template_id,
                "title": spec["title"],
                "tool_name": "create_population_migration_map",
                "response": export_response,
                "export_path": str(output_path),
                "artifact_bundle": artifact_bundle,
            }

        line_layer_name = payload.get("line_layer_name") or payload.get("layer_name")
        if not line_layer_name:
            raise ValueError("population_migration requires line_layer_name or origins_layer/destinations_layer")

        flow_response = self._call_qgis(
            "create_flow_arrows",
            layer_name=line_layer_name,
            start_x=payload.get("start_x"),
            start_y=payload.get("start_y"),
            end_x=payload.get("end_x"),
            end_y=payload.get("end_y"),
            width_field=payload.get("width_field"),
            color=payload.get("color", "#d1495b"),
            scale_mode=payload.get("scale_mode", "fixed"),
            map_session=payload.get("map_session"),
        )
        map_session = self._extract_map_session(flow_response)
        flow_layer_name = self._first_non_empty(
            flow_response.get("layer_name"),
            flow_response.get("artifacts", {}).get("layer", {}).get("layer_name"),
            line_layer_name,
        )
        self._call_qgis("auto_layout", title=title, layout_name=layout_name, map_session=map_session)
        self._call_qgis(
            "customize_layout_legend",
            layout_name=layout_name,
            title=legend_title,
            layer_order=[flow_layer_name],
            hidden_layers=hidden_layers,
            map_session=map_session,
        )
        export_response = self._call_qgis(
            "export_map",
            file_path=str(output_path),
            layout_name=layout_name,
            map_session=map_session,
        )
        return {
            "template_id": template_id,
            "title": spec["title"],
            "tool_name": "create_flow_arrows",
            "response": export_response,
            "export_path": str(output_path),
            "artifact_bundle": self._build_artifact_bundle(spec["title"], output_path),
        }

    def _execute_population_change_comparison(self, project_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        spec = TEMPLATE_SPECS[template_id]
        output_path = self._build_output_path(project_id, spec["file_stub"])
        title = payload.get("title", spec["title"])
        layout_name = payload.get("layout_name", f"GeoBot_{project_id[:8]}")
        layer_name = payload.get("layer_name")
        if not layer_name:
            raise ValueError("population_change_comparison requires layer_name")

        density_layer_name = payload.get("density_layer_name") or layer_name
        chart_layer_name = payload.get("chart_layer_name") or layer_name
        value_field = payload.get("value_field") or "population"
        label_field = payload.get("label_field") or ""
        density_weight_field = payload.get("density_weight_field") or payload.get("weight_field") or value_field
        chart_category_field = payload.get("chart_category_field") or label_field or "name"
        chart_value_field = payload.get("chart_value_field") or value_field
        chart_title = payload.get("chart_title", "人口分布对比")
        legend_title = payload.get("legend_title", "Population Showcase")

        distribution_response = self._call_qgis(
            "create_population_distribution_map",
            layer_name=layer_name,
            value_field=value_field,
            label_field=label_field,
            title=title,
            legend_title="Population Distribution",
            auto_layout=False,
            layout_name=layout_name,
            map_session=payload.get("map_session"),
        )
        map_session = self._extract_map_session(distribution_response)

        density_response = self._call_qgis(
            "create_population_density_map",
            layer_name=density_layer_name,
            weight_field=density_weight_field,
            radius=payload.get("density_radius", 15),
            pixel_size=payload.get("density_pixel_size", 5),
            title=title,
            auto_layout=False,
            layout_name=layout_name,
            map_session=map_session,
        )
        map_session = self._extract_map_session(density_response, distribution_response)

        hu_line_response = self._call_qgis(
            "create_hu_line_comparison_map",
            layer_name=layer_name,
            weight_field=payload.get("hu_weight_field") or value_field,
            label_field=label_field,
            title=title,
            auto_layout=False,
            layout_name=layout_name,
            map_session=map_session,
        )
        map_session = self._extract_map_session(hu_line_response, density_response, distribution_response)

        chart_response = self._call_qgis(
            "embed_chart",
            layer_name=chart_layer_name,
            chart_type=payload.get("chart_type", "bar"),
            category_field=chart_category_field,
            value_field=chart_value_field,
            aggregation=payload.get("chart_aggregation", "sum"),
            title=chart_title,
            layout_embed=True,
            dock_preview=False,
            layout_name=layout_name,
            chart_slot=payload.get("chart_slot", "primary"),
            map_session=map_session,
        )
        map_session = self._extract_map_session(chart_response, hu_line_response, density_response, distribution_response)

        heatmap_layer_name = self._first_non_empty(
            density_response.get("artifacts", {}).get("heatmap_layer", {}).get("layer_name"),
            density_layer_name,
        )
        comparison_layer_name = self._first_non_empty(
            hu_line_response.get("artifacts", {}).get("comparison_layer", {}).get("layer_name"),
        )
        self._call_qgis(
            "auto_layout",
            title=title,
            layout_name=layout_name,
            map_session=map_session,
        )
        self._call_qgis(
            "customize_layout_legend",
            layout_name=layout_name,
            title=legend_title,
            layer_order=[value for value in [comparison_layer_name, heatmap_layer_name, layer_name] if value],
            hidden_layers=list(self._normalize_hidden_layers(payload.get("hidden_layers"))),
            map_session=map_session,
        )
        export_response = self._call_qgis(
            "export_map",
            file_path=str(output_path),
            layout_name=layout_name,
            map_session=map_session,
        )
        artifact_bundle = self._build_artifact_bundle(
            spec["title"],
            output_path,
            extras=self._chart_artifact(chart_response, "chart_preview", "Population Comparison Chart", 60),
        )
        return {
            "template_id": template_id,
            "title": spec["title"],
            "tool_name": "population_change_comparison",
            "response": export_response,
            "export_path": str(output_path),
            "artifact_bundle": artifact_bundle,
        }

    def _execute_population_capacity_dashboard(self, project_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        spec = TEMPLATE_SPECS[template_id]
        output_path = self._build_output_path(project_id, spec["file_stub"])
        title = payload.get("title", spec["title"])
        layout_name = payload.get("layout_name", f"GeoBot_{project_id[:8]}")
        layer_name = payload.get("layer_name")
        if not layer_name:
            raise ValueError("population_capacity_dashboard requires layer_name")

        value_field = payload.get("value_field") or "capacity"
        label_field = payload.get("label_field") or ""
        chart_layer_name = payload.get("chart_layer_name") or layer_name
        chart_category_field = payload.get("chart_category_field") or label_field or "name"
        chart_value_field = payload.get("chart_value_field") or value_field
        secondary_value_field = payload.get("secondary_value_field")
        legend_title = payload.get("legend_title", "Population Capacity")

        distribution_response = self._call_qgis(
            "create_population_distribution_map",
            layer_name=layer_name,
            value_field=value_field,
            label_field=label_field,
            title=title,
            legend_title=legend_title,
            auto_layout=False,
            layout_name=layout_name,
            map_session=payload.get("map_session"),
        )
        map_session = self._extract_map_session(distribution_response)

        primary_chart_response = self._call_qgis(
            "embed_chart",
            layer_name=chart_layer_name,
            chart_type=payload.get("chart_type", "bar"),
            category_field=chart_category_field,
            value_field=chart_value_field,
            aggregation=payload.get("chart_aggregation", "sum"),
            title=payload.get("chart_title", "人口合理容量对比"),
            layout_embed=True,
            dock_preview=False,
            layout_name=layout_name,
            chart_slot=payload.get("chart_slot", "primary"),
            map_session=map_session,
        )
        map_session = self._extract_map_session(primary_chart_response, distribution_response)

        chart_artifacts = self._chart_artifact(primary_chart_response, "primary_chart", "Population Capacity Chart", 60)
        if secondary_value_field:
            secondary_chart_response = self._call_qgis(
                "embed_chart",
                layer_name=chart_layer_name,
                chart_type=payload.get("secondary_chart_type", payload.get("chart_type", "bar")),
                category_field=chart_category_field,
                value_field=secondary_value_field,
                aggregation=payload.get("secondary_chart_aggregation", payload.get("chart_aggregation", "sum")),
                title=payload.get("secondary_chart_title", "承载压力对比"),
                layout_embed=True,
                dock_preview=False,
                layout_name=layout_name,
                chart_slot=payload.get("secondary_chart_slot", "secondary"),
                map_session=map_session,
            )
            map_session = self._extract_map_session(secondary_chart_response, primary_chart_response, distribution_response)
            chart_artifacts.update(self._chart_artifact(secondary_chart_response, "secondary_chart", "Population Pressure Chart", 65))

        self._call_qgis(
            "auto_layout",
            title=title,
            layout_name=layout_name,
            map_session=map_session,
        )
        self._call_qgis(
            "customize_layout_legend",
            layout_name=layout_name,
            title=legend_title,
            layer_order=[layer_name],
            hidden_layers=list(self._normalize_hidden_layers(payload.get("hidden_layers"))),
            map_session=map_session,
        )
        export_response = self._call_qgis(
            "export_map",
            file_path=str(output_path),
            layout_name=layout_name,
            map_session=map_session,
        )
        return {
            "template_id": template_id,
            "title": spec["title"],
            "tool_name": "population_capacity_dashboard",
            "response": export_response,
            "export_path": str(output_path),
            "artifact_bundle": self._build_artifact_bundle(spec["title"], output_path, extras=chart_artifacts),
        }
