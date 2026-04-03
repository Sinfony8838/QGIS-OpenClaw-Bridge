from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .base_service import BaseGeoAIService


class TeachingService(BaseGeoAIService):
    def _expect_success(self, response):
        if response.get("status") != "success":
            raise RuntimeError(response.get("message", "Operation failed"))
        return response

    def _finalize_template(self, session, title, auto_layout, export_path, legend_title, layer_order=None, hidden_layers=None):
        artifacts = self.session_artifacts(session)
        if auto_layout:
            self._expect_success(
                self.call_in_main_thread(
                    self.server.cartography_service.auto_layout,
                    title=title,
                    layout_name=session["requested_layout_name"],
                    map_session=session["map_session"],
                    extent_mode=session.get("extent_mode", "session_union"),
                )
            )
            self._expect_success(
                self.call_in_main_thread(
                    self.server.cartography_service.customize_layout_legend,
                    layout_name=session["layout_name"],
                    title=legend_title,
                    layer_order=layer_order,
                    hidden_layers=hidden_layers or [],
                    map_session=session["map_session"],
                )
            )

        if export_path:
            self._expect_success(
                self.call_in_main_thread(
                    self.server.cartography_service.export_map,
                    file_path=export_path,
                    layout_name=session["layout_name"],
                    map_session=session["map_session"],
                )
            )
            artifacts["export_path"] = export_path

        return artifacts

    def _emit_template_summary(self, title, summary_lines, artifacts):
        self.emit_execution_summary(title=title, summary_lines=summary_lines, artifacts=artifacts)

    def generate_dynamic_hu_huanyong_line(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        output_name="Hu Huanyong Comparison",
        target_share=0.94,
        angle_range_degrees=20,
        angle_steps=41,
        shift_steps=81,
        add_labels=True,
        map_session=None,
    ):
        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = self.ensure_map_session(
                map_session=map_session,
                title=output_name,
                create_new=not map_session,
            ) if map_session else None
            if session:
                self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)

            target_crs = source_layer.crs() if source_layer.crs().isValid() else self.project.crs()
            weighted_points = self.feature_weighted_points(source_layer, weight_field, target_crs)

            classic_start, classic_end = self.classic_hu_points(target_crs)
            classic_direction = self.normalize_vector(classic_end.x() - classic_start.x(), classic_end.y() - classic_start.y())
            classic_anchor = QgsPointXY(
                (classic_start.x() + classic_end.x()) / 2.0,
                (classic_start.y() + classic_end.y()) / 2.0,
            )
            reference_point = self.transform_point_xy(
                QgsPointXY(121.47, 31.23),
                source_crs=QgsCoordinateReferenceSystem("EPSG:4326"),
                target_crs=target_crs,
            )
            classic_share = self.population_share_for_line(weighted_points, classic_anchor, classic_direction, reference_point)

            xs = [point.x() for point, _ in weighted_points]
            ys = [point.y() for point, _ in weighted_points]
            diagonal = max(((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5, 1.0)
            shift_limit = diagonal * 0.35
            angle_range_radians = float(angle_range_degrees) * 3.141592653589793 / 180.0

            best_candidate = None
            for angle_index in range(max(int(angle_steps), 2)):
                angle_ratio = angle_index / float(max(int(angle_steps) - 1, 1))
                angle_delta = -angle_range_radians + 2.0 * angle_range_radians * angle_ratio
                direction = self.rotate_vector(classic_direction[0], classic_direction[1], angle_delta)
                direction = self.normalize_vector(direction[0], direction[1])
                normal = (-direction[1], direction[0])

                for shift_index in range(max(int(shift_steps), 2)):
                    shift_ratio = shift_index / float(max(int(shift_steps) - 1, 1))
                    shift_value = -shift_limit + 2.0 * shift_limit * shift_ratio
                    anchor = QgsPointXY(
                        classic_anchor.x() + normal[0] * shift_value,
                        classic_anchor.y() + normal[1] * shift_value,
                    )
                    share = self.population_share_for_line(weighted_points, anchor, direction, reference_point)
                    score = abs(share - float(target_share))
                    candidate = {
                        "score": score,
                        "share": share,
                        "anchor": anchor,
                        "direction": direction,
                        "angle_delta_degrees": angle_delta * 180.0 / 3.141592653589793,
                        "shift_distance": shift_value,
                    }
                    if best_candidate is None or candidate["score"] < best_candidate["score"]:
                        best_candidate = candidate

            result_layer = QgsVectorLayer(f"LineString?crs={target_crs.authid()}", output_name, "memory")
            provider = result_layer.dataProvider()
            provider.addAttributes(
                [
                    QgsField("name", QVariant.String),
                    QgsField("line_type", QVariant.String),
                    QgsField("east_share", QVariant.Double),
                    QgsField("target", QVariant.Double),
                    QgsField("angle_delta", QVariant.Double),
                    QgsField("shift", QVariant.Double),
                ]
            )
            result_layer.updateFields()

            classic_segment = self.segment_for_line(classic_anchor, classic_direction, weighted_points)
            fitted_segment = self.segment_for_line(best_candidate["anchor"], best_candidate["direction"], weighted_points)

            classic_feature = QgsFeature(result_layer.fields())
            classic_feature.setGeometry(QgsGeometry.fromPolylineXY([classic_segment[0], classic_segment[1]]))
            classic_feature["name"] = "Classic Hu Huanyong Line"
            classic_feature["line_type"] = "classic"
            classic_feature["east_share"] = round(classic_share, 6)
            classic_feature["target"] = float(target_share)
            classic_feature["angle_delta"] = 0.0
            classic_feature["shift"] = 0.0

            dynamic_feature = QgsFeature(result_layer.fields())
            dynamic_feature.setGeometry(QgsGeometry.fromPolylineXY([fitted_segment[0], fitted_segment[1]]))
            dynamic_feature["name"] = "Fitted Dynamic Line"
            dynamic_feature["line_type"] = "dynamic"
            dynamic_feature["east_share"] = round(best_candidate["share"], 6)
            dynamic_feature["target"] = float(target_share)
            dynamic_feature["angle_delta"] = round(best_candidate["angle_delta_degrees"], 4)
            dynamic_feature["shift"] = round(best_candidate["shift_distance"], 4)

            provider.addFeatures([classic_feature, dynamic_feature])
            result_layer.updateExtents()

            categories = [
                QgsRendererCategory(
                    "classic",
                    QgsLineSymbol.createSimple({"color": "#1d3557", "width": "0.9", "line_style": "dash"}),
                    "Classic Hu Huanyong Line",
                ),
                QgsRendererCategory(
                    "dynamic",
                    QgsLineSymbol.createSimple({"color": "#e63946", "width": "1.2"}),
                    "Fitted Dynamic Line",
                ),
            ]
            result_layer.setRenderer(QgsCategorizedSymbolRenderer("line_type", categories))
            self.add_map_layer(result_layer)
            self.refresh_layer(result_layer)

            if session:
                self.register_layer_with_session(
                    session,
                    result_layer,
                    role="comparison_line",
                    owned=True,
                    include_in_layout=True,
                    source_tag="hu_huanyong_comparison",
                )

            if add_labels:
                self._expect_success(
                    self.call_in_main_thread(
                        self.server.cartography_service.set_layer_labels,
                        layer_id=result_layer.id(),
                        field="name",
                        color="#111827",
                        size=10,
                        map_session=map_session,
                    )
                )

            artifacts = {
                "comparison_layer": self.artifact_for_layer(result_layer),
                "source_layer": self.artifact_for_layer(source_layer),
            }
            artifacts.update(self.session_artifacts(session))
            return self.success(
                "Dynamic Hu Huanyong comparison line generated",
                data={
                    "source_layer": source_layer.name(),
                    "weight_field": weight_field,
                    "target_share": float(target_share),
                    "classic_share": round(classic_share, 6),
                    "dynamic_share": round(best_candidate["share"], 6),
                    "angle_delta_degrees": round(best_candidate["angle_delta_degrees"], 4),
                    "shift_distance": round(best_candidate["shift_distance"], 4),
                },
                artifacts=artifacts,
                **self.artifact_for_layer(result_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_population_distribution_map(
        self,
        layer_id=None,
        layer_name=None,
        value_field=None,
        label_field=None,
        classes=5,
        mode="jenks",
        color_ramp="YlOrRd",
        title="Population Distribution Map",
        legend_title="Population Distribution",
        auto_layout=False,
        layout_name="GeoAI_Output",
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = self.ensure_map_session(
                map_session=map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
                create_new=not map_session,
            )
            self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)

            self._expect_success(
                self.call_in_main_thread(
                    self.server.cartography_service.apply_graduated_renderer,
                    layer_id=source_layer.id(),
                    field=value_field,
                    mode=mode,
                    classes=classes,
                    color_ramp=color_ramp,
                    map_session=session["map_session"],
                )
            )

            if label_field:
                self._expect_success(
                    self.call_in_main_thread(
                        self.server.cartography_service.set_layer_labels,
                        layer_id=source_layer.id(),
                        field=label_field,
                        color="#222222",
                        size=10,
                        map_session=session["map_session"],
                    )
                )

            artifacts = {"thematic_layer": self.artifact_for_layer(source_layer)}
            artifacts.update(
                self._finalize_template(
                    session=session,
                    title=title,
                    auto_layout=auto_layout,
                    export_path=export_path,
                    legend_title=legend_title,
                    layer_order=[source_layer.name()],
                )
            )
            summary_lines = [
                f"Thematic layer: {source_layer.name()}",
                f"Value field: {value_field}",
                f"Classes: {classes}",
            ]
            if label_field:
                summary_lines.append(f"Label field: {label_field}")
            self._emit_template_summary(title, summary_lines, artifacts)

            return self.success(
                "Population distribution map created",
                data={"title": title},
                artifacts=artifacts,
                map_session=session["map_session"],
                **self.artifact_for_layer(source_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_population_density_map(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        radius=15,
        pixel_size=5,
        title="Population Density Map",
        auto_layout=False,
        layout_name="GeoAI_Output",
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = self.ensure_map_session(
                map_session=map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
                create_new=not map_session,
            )
            self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)

            heatmap_response = self._expect_success(
                self.server.analysis_service.create_heatmap(
                    layer_id=source_layer.id(),
                    radius=radius,
                    pixel_size=pixel_size,
                    weight_field=weight_field,
                    map_session=session["map_session"],
                )
            )

            heatmap_name = heatmap_response.get("layer_name")
            artifacts = {
                "source_layer": self.artifact_for_layer(source_layer),
                "heatmap_layer": {
                    "layer_id": heatmap_response.get("layer_id"),
                    "layer_name": heatmap_name,
                },
            }
            artifacts.update(
                self._finalize_template(
                    session=session,
                    title=title,
                    auto_layout=auto_layout,
                    export_path=export_path,
                    legend_title="Population Density",
                    layer_order=[source_layer.name(), heatmap_name],
                )
            )
            self._emit_template_summary(
                title,
                [
                    f"Source layer: {source_layer.name()}",
                    f"Heatmap layer: {heatmap_name}",
                    f"Weight field: {weight_field or 'not set'}",
                ],
                artifacts,
            )

            return self.success(
                "Population density map created",
                data=heatmap_response.get("data", {}),
                warnings=heatmap_response.get("warnings", []),
                artifacts=artifacts,
                map_session=session["map_session"],
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_population_migration_map(
        self,
        origins_layer,
        destinations_layer,
        origin_id_field,
        destination_id_field,
        title="Population Migration Map",
        color="#d1495b",
        auto_layout=False,
        layout_name="GeoAI_Output",
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        try:
            session = self.ensure_map_session(
                map_session=map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
                create_new=not map_session,
            )
            connection_response = self._expect_success(
                self.server.layer_service.create_connection_lines(
                    origins_layer=origins_layer,
                    destinations_layer=destinations_layer,
                    origin_id_field=origin_id_field,
                    destination_id_field=destination_id_field,
                    output_name="Population_Migration_Connections",
                    map_session=session["map_session"],
                )
            )
            arrow_response = self._expect_success(
                self.call_in_main_thread(
                    self.server.analysis_service.create_flow_arrows,
                    layer_id=connection_response.get("layer_id"),
                    color=color,
                    map_session=session["map_session"],
                )
            )

            arrow_layer_name = arrow_response.get("layer_name")
            artifacts = {
                "connection_layer": {
                    "layer_id": connection_response.get("layer_id"),
                    "layer_name": connection_response.get("layer_name"),
                },
                "flow_layer": {
                    "layer_id": arrow_response.get("layer_id"),
                    "layer_name": arrow_layer_name,
                },
            }
            artifacts.update(
                self._finalize_template(
                    session=session,
                    title=title,
                    auto_layout=auto_layout,
                    export_path=export_path,
                    legend_title="Population Migration",
                    layer_order=[arrow_layer_name, origins_layer, destinations_layer],
                    hidden_layers=[origins_layer, destinations_layer],
                )
            )
            self._emit_template_summary(
                title,
                [
                    f"Origins: {origins_layer}",
                    f"Destinations: {destinations_layer}",
                    f"Flow layer: {arrow_layer_name}",
                ],
                artifacts,
            )

            return self.success(
                "Population migration map created",
                data={"flow_layer_name": arrow_layer_name},
                warnings=arrow_response.get("warnings", []),
                artifacts=artifacts,
                map_session=session["map_session"],
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_hu_line_comparison_map(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        label_field=None,
        classes=5,
        color_ramp="YlOrRd",
        title="Hu Huanyong Line Comparison",
        auto_layout=False,
        layout_name="GeoAI_Output",
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = self.ensure_map_session(
                map_session=map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
                create_new=not map_session,
            )
            self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)

            if source_layer.geometryType() not in (QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry):
                self._expect_success(
                    self.call_in_main_thread(
                        self.server.cartography_service.apply_graduated_renderer,
                        layer_id=source_layer.id(),
                        field=weight_field,
                        classes=classes,
                        color_ramp=color_ramp,
                        map_session=session["map_session"],
                    )
                )

            if label_field:
                self._expect_success(
                    self.call_in_main_thread(
                        self.server.cartography_service.set_layer_labels,
                        layer_id=source_layer.id(),
                        field=label_field,
                        color="#1f2933",
                        size=10,
                        map_session=session["map_session"],
                    )
                )

            comparison_response = self._expect_success(
                self.generate_dynamic_hu_huanyong_line(
                    layer_id=source_layer.id(),
                    weight_field=weight_field,
                    output_name="Hu_Huanyong_Comparison",
                    add_labels=True,
                    map_session=session["map_session"],
                )
            )
            comparison_layer_name = comparison_response.get("layer_name")
            artifacts = {
                "source_layer": self.artifact_for_layer(source_layer),
                "comparison_layer": {
                    "layer_id": comparison_response.get("layer_id"),
                    "layer_name": comparison_layer_name,
                },
            }
            artifacts.update(
                self._finalize_template(
                    session=session,
                    title=title,
                    auto_layout=auto_layout,
                    export_path=export_path,
                    legend_title="Hu Huanyong Comparison",
                    layer_order=[comparison_layer_name, source_layer.name()],
                )
            )
            self._emit_template_summary(
                title,
                [
                    f"Base layer: {source_layer.name()}",
                    f"Weight field: {weight_field}",
                    f"Classic east share: {comparison_response['data']['classic_share']}",
                    f"Dynamic east share: {comparison_response['data']['dynamic_share']}",
                ],
                artifacts,
            )

            return self.success(
                "Hu Huanyong comparison map created",
                data=comparison_response.get("data", {}),
                artifacts=artifacts,
                map_session=session["map_session"],
            )
        except Exception as exc:
            return self.error(str(exc))
