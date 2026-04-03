import math

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsApplication,
    QgsArrowSymbolLayer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    import processing
except ImportError:
    processing = None

from .base_service import BaseGeoAIService
from .service_utils import resolve_processing_inputs


class AnalysisService(BaseGeoAIService):
    def run_algorithm(self, algorithm_id, params, load_result=True, map_session=None, role=None):
        if not processing:
            return self.error("QGIS processing module is unavailable")

        try:
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None
            algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
            if not algorithm:
                return self.error(f"Algorithm not found: {algorithm_id}")

            fixed_params, resolved_layers = resolve_processing_inputs(
                params=params,
                definitions=algorithm.parameterDefinitions(),
                layer_resolver=self.resolve_layer,
            )
            if session:
                for layer in resolved_layers:
                    self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)

            if "OUTPUT" not in fixed_params:
                fixed_params["OUTPUT"] = "TEMPORARY_OUTPUT"

            result = self.run_processing_with_supported_params(algorithm_id, fixed_params)
            artifacts = {}

            if load_result:
                for value in result.values():
                    output_layer = self.load_result_layer(
                        value,
                        f"Result_{algorithm_id.split(':')[-1]}",
                        map_session=map_session,
                        role=role,
                        source_tag=algorithm_id,
                    )
                    if output_layer:
                        artifacts["layer"] = self.artifact_for_layer(output_layer)
                        artifacts.update(self.session_artifacts(session))
                        return self.success(
                            "Algorithm executed and layer loaded",
                            data=result,
                            artifacts=artifacts,
                            **self.artifact_for_layer(output_layer),
                        )

            artifacts.update(self.session_artifacts(session))
            return self.success("Algorithm executed", data=result, artifacts=artifacts)
        except Exception as exc:
            return self.error(f"Algorithm error: {exc}")

    def get_algorithm_help(self, algorithm_id):
        try:
            algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
            if not algorithm:
                return self.error("Algorithm not found")
            params = {definition.name(): definition.description() for definition in algorithm.parameterDefinitions()}
            return self.success("Algorithm help loaded", data=params)
        except Exception as exc:
            return self.error(str(exc))

    def create_heatmap(
        self,
        layer_id=None,
        layer_name=None,
        radius=15,
        pixel_size=5,
        weight_field=None,
        output_mode="memory",
        map_session=None,
    ):
        if not processing:
            return self.error("QGIS processing module is unavailable")

        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None
            if session:
                self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)
            if weight_field:
                self.require_field(source_layer, weight_field)

            working_layer, warnings = self.prepare_heatmap_input_layer(source_layer, map_session=map_session)
            algorithm_id = self.find_processing_algorithm(
                [
                    "qgis:heatmapkerneldensityestimation",
                    "native:heatmapkerneldensityestimation",
                    "heatmapkerneldensityestimation",
                ]
            )
            if not algorithm_id:
                return self.error("Heatmap algorithm is unavailable in this QGIS environment")

            algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
            param_names = {definition.name() for definition in algorithm.parameterDefinitions()}
            params = {}
            if "INPUT" in param_names:
                params["INPUT"] = working_layer
            elif "POINTS" in param_names:
                params["POINTS"] = working_layer

            if "RADIUS" in param_names:
                params["RADIUS"] = float(radius)
            if "PIXEL_SIZE" in param_names:
                params["PIXEL_SIZE"] = float(pixel_size)
            if "PIXELSIZE" in param_names:
                params["PIXELSIZE"] = float(pixel_size)
            if weight_field:
                if "WEIGHT_FIELD" in param_names:
                    params["WEIGHT_FIELD"] = weight_field
                elif "WEIGHT" in param_names:
                    params["WEIGHT"] = weight_field
            if "KERNEL" in param_names:
                params["KERNEL"] = 0
            if "DECAY" in param_names:
                params["DECAY"] = 0
            if "OUTPUT_VALUE" in param_names:
                params["OUTPUT_VALUE"] = 0
            if "OUTPUT" in param_names:
                params["OUTPUT"] = self.coerce_output_target(output_mode, default_suffix=".tif")

            result = self.run_processing_with_supported_params(algorithm_id, params)
            output_layer = None
            for value in result.values():
                output_layer = self.load_result_layer(
                    value,
                    f"{source_layer.name()}_heatmap",
                    map_session=map_session,
                    role="surface",
                    source_tag="heatmap",
                )
                if output_layer:
                    break

            if not output_layer:
                return self.error("Heatmap finished but output layer could not be loaded", data=result, warnings=warnings)

            artifacts = {"layer": self.artifact_for_layer(output_layer)}
            artifacts.update(self.session_artifacts(session))
            return self.success(
                "Heatmap created",
                data={
                    "source_layer": source_layer.name(),
                    "working_layer": working_layer.name(),
                    "algorithm_id": algorithm_id,
                },
                warnings=warnings,
                artifacts=artifacts,
                **self.artifact_for_layer(output_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_flow_arrows(
        self,
        layer_id=None,
        layer_name=None,
        start_x=None,
        start_y=None,
        end_x=None,
        end_y=None,
        width_field=None,
        color="#d1495b",
        scale_mode="fixed",
        map_session=None,
    ):
        try:
            source_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            target_layer = source_layer
            warnings = []
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None
            if session:
                self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=True)

            if all(value is not None for value in [start_x, start_y, end_x, end_y]):
                for field_name in [start_x, start_y, end_x, end_y]:
                    self.require_field(source_layer, field_name)

                target_layer = QgsVectorLayer(
                    f"LineString?crs={source_layer.crs().authid()}",
                    f"{source_layer.name()}_flow_arrows",
                    "memory",
                )
                provider = target_layer.dataProvider()
                provider.addAttributes([QgsField("source_id", QVariant.String)])
                if width_field and source_layer.fields().indexFromName(width_field) >= 0:
                    provider.addAttributes([QgsField(width_field, QVariant.Double)])
                target_layer.updateFields()

                features = []
                for feature in source_layer.getFeatures():
                    points = [
                        QgsPointXY(float(feature[start_x]), float(feature[start_y])),
                        QgsPointXY(float(feature[end_x]), float(feature[end_y])),
                    ]
                    new_feature = QgsFeature(target_layer.fields())
                    new_feature.setGeometry(QgsGeometry.fromPolylineXY(points))
                    new_feature["source_id"] = str(feature.id())
                    if width_field and target_layer.fields().indexFromName(width_field) >= 0:
                        new_feature[width_field] = float(feature[width_field] or 0)
                    features.append(new_feature)
                provider.addFeatures(features)
                target_layer.updateExtents()
                self.add_map_layer(target_layer)
                warnings.append("generated_line_layer_from_coordinates")
                if session:
                    self.register_layer_with_session(
                        session,
                        target_layer,
                        role="flow_line",
                        owned=True,
                        include_in_layout=True,
                        source_tag="flow_arrows",
                    )

            width_value = 0.8
            if width_field and target_layer.fields().indexFromName(width_field) >= 0:
                values = [float(feature[width_field]) for feature in target_layer.getFeatures() if feature[width_field] not in (None, "")]
                if values:
                    width_value = max(0.4, sum(values) / len(values))
                    if scale_mode == "normalized":
                        width_value = max(0.4, min(3.0, width_value))

            symbol = QgsLineSymbol.createSimple({"color": color, "width": str(width_value)})
            arrow_layer = QgsArrowSymbolLayer.create(
                {
                    "arrow_width": str(width_value),
                    "head_length": "4",
                    "head_thickness": "2",
                    "color": color,
                }
            )
            if arrow_layer:
                symbol.changeSymbolLayer(0, arrow_layer)

            target_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            self.refresh_layer(target_layer)
            if session:
                self.register_layer_with_session(
                    session,
                    target_layer,
                    role="flow_line",
                    owned=target_layer.id() != source_layer.id(),
                    include_in_layout=True,
                    source_tag="flow_arrows",
                )
            return self.success(
                "Flow arrows created",
                data={"scale_mode": scale_mode, "width": width_value},
                warnings=warnings,
                artifacts=dict({"layer": self.artifact_for_layer(target_layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(target_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def _to_project_point(self, layer, geometry, target_crs):
        point = geometry.centroid().asPoint()
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(layer.crs(), target_crs, self.project)
            point = transform.transform(point)
        return point

    def run_population_attraction_model(
        self,
        origins_layer,
        destinations_layer,
        origin_pop_field,
        destination_pop_field,
        distance_source="centroid",
        beta=2.0,
        output_type="lines",
        map_session=None,
    ):
        try:
            origins = self.require_vector_layer(layer_name=origins_layer)
            destinations = self.require_vector_layer(layer_name=destinations_layer)
            self.require_field(origins, origin_pop_field)
            self.require_field(destinations, destination_pop_field)
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None
            if session:
                self.register_layer_with_session(session, origins, owned=False, include_in_layout=True)
                self.register_layer_with_session(session, destinations, owned=False, is_reference=True, include_in_layout=True)

            target_crs = self.project.crs() or origins.crs()
            pairs = []
            for origin in origins.getFeatures():
                origin_point = self._to_project_point(origins, origin.geometry(), target_crs)
                origin_population = float(origin[origin_pop_field] or 0)

                for destination in destinations.getFeatures():
                    if origins.id() == destinations.id() and origin.id() == destination.id():
                        continue
                    if distance_source != "centroid":
                        return self.error("Only centroid distance is supported in v1")

                    destination_point = self._to_project_point(destinations, destination.geometry(), target_crs)
                    destination_population = float(destination[destination_pop_field] or 0)
                    distance = max(origin_point.distance(destination_point), 1.0)
                    score = (origin_population * destination_population) / math.pow(distance, float(beta))
                    pairs.append(
                        {
                            "origin_id": str(origin.id()),
                            "destination_id": str(destination.id()),
                            "distance": round(distance, 4),
                            "score": round(score, 6),
                            "origin_point": origin_point,
                            "destination_point": destination_point,
                        }
                    )

            if output_type == "records":
                response_pairs = [
                    {key: value for key, value in pair.items() if key not in ("origin_point", "destination_point")}
                    for pair in pairs
                ]
                return self.success(
                    "Population attraction model calculated",
                    data=response_pairs,
                    artifacts=self.session_artifacts(session),
                )

            result_layer = QgsVectorLayer(f"LineString?crs={target_crs.authid()}", "Population_Attraction", "memory")
            provider = result_layer.dataProvider()
            provider.addAttributes(
                [
                    QgsField("origin_id", QVariant.String),
                    QgsField("dest_id", QVariant.String),
                    QgsField("distance", QVariant.Double),
                    QgsField("score", QVariant.Double),
                ]
            )
            result_layer.updateFields()

            features = []
            for pair in pairs:
                feature = QgsFeature(result_layer.fields())
                feature.setGeometry(QgsGeometry.fromPolylineXY([pair["origin_point"], pair["destination_point"]]))
                feature["origin_id"] = pair["origin_id"]
                feature["dest_id"] = pair["destination_id"]
                feature["distance"] = pair["distance"]
                feature["score"] = pair["score"]
                features.append(feature)
            provider.addFeatures(features)
            result_layer.updateExtents()
            self.add_map_layer(result_layer)
            if session:
                self.register_layer_with_session(session, result_layer, role="line", owned=True, include_in_layout=True, source_tag="population_attraction")

            return self.success(
                "Population attraction model calculated",
                data={"pair_count": len(pairs), "beta": float(beta)},
                artifacts=dict({"layer": self.artifact_for_layer(result_layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(result_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def style_population_attraction_result(
        self,
        layer_id=None,
        layer_name=None,
        field="score",
        style_mode="graduated",
        classes=5,
        color_ramp="Magma",
        color="#e76f51",
        map_session=None,
    ):
        try:
            if style_mode == "flow_arrows":
                return self.create_flow_arrows(layer_id=layer_id, layer_name=layer_name, color=color, map_session=map_session)
            return self.server.cartography_service.apply_graduated_renderer(
                layer_id=layer_id,
                layer_name=layer_name,
                field=field,
                classes=classes,
                color_ramp=color_ramp,
                map_session=map_session,
            )
        except Exception as exc:
            return self.error(str(exc))
