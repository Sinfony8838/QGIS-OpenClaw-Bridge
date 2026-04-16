from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .base_service import BaseGeoAIService


FIELD_TYPE_MAP = {
    "string": QVariant.String,
    "str": QVariant.String,
    "text": QVariant.String,
    "int": QVariant.Int,
    "integer": QVariant.Int,
    "double": QVariant.Double,
    "float": QVariant.Double,
    "real": QVariant.Double,
    "bool": QVariant.Bool,
    "boolean": QVariant.Bool,
}


class LayerService(BaseGeoAIService):
    def _layer_order_index(self):
        root = self.project.layerTreeRoot()
        order = {}
        counter = {"value": 0}

        def collect(node):
            for child in node.children():
                if hasattr(child, "layerId"):
                    layer_id = child.layerId()
                    if layer_id:
                        order[layer_id] = counter["value"]
                        counter["value"] += 1
                elif hasattr(child, "children"):
                    collect(child)

        if root:
            collect(root)
        return order

    def get_layers(self):
        active_layer_id = ""
        if self.iface:
            try:
                active_layer = self.iface.activeLayer()
                active_layer_id = active_layer.id() if active_layer else ""
            except Exception:
                active_layer_id = ""

        root = self.project.layerTreeRoot()
        order_index = self._layer_order_index()
        layers = []
        for layer in self.project.mapLayers().values():
            fields = []
            if hasattr(layer, "fields"):
                try:
                    fields = [field.name() for field in layer.fields()]
                except Exception:
                    fields = []
            layer_node = root.findLayer(layer.id()) if root else None
            is_visible = True
            if layer_node and hasattr(layer_node, "isVisible"):
                try:
                    is_visible = bool(layer_node.isVisible())
                except Exception:
                    is_visible = True
            labels_enabled = False
            if hasattr(layer, "labelsEnabled"):
                try:
                    labels_enabled = bool(layer.labelsEnabled())
                except Exception:
                    labels_enabled = False
            layers.append(
                {
                    "name": layer.name(),
                    "id": layer.id(),
                    "type": layer.type(),
                    "provider": layer.providerType() if hasattr(layer, "providerType") else None,
                    "crs": layer.crs().authid() if hasattr(layer, "crs") and layer.crs().isValid() else None,
                    "fields": fields,
                    "geometry_type": self._resolve_geometry_type(layer),
                    "is_visible": is_visible,
                    "is_active": layer.id() == active_layer_id,
                    "labels_enabled": labels_enabled,
                    "order_index": order_index.get(layer.id(), -1),
                }
            )
        return self.success("Layers loaded", data=layers)

    def _resolve_geometry_type(self, layer):
        if isinstance(layer, QgsVectorLayer) and hasattr(layer, "geometryType"):
            geometry_type = layer.geometryType()
            if geometry_type == QgsWkbTypes.PointGeometry:
                return "point"
            if geometry_type == QgsWkbTypes.LineGeometry:
                return "line"
            if geometry_type == QgsWkbTypes.PolygonGeometry:
                return "polygon"
            return str(geometry_type)
        if getattr(layer, "type", None) and callable(layer.type):
            try:
                if str(layer.type()).lower() == "1":
                    return "raster"
            except Exception:
                pass
        return ""

    def add_layer_from_path(self, file_path, layer_name="New Layer", map_session=None, role=None):
        if file_path.lower().endswith((".shp", ".geojson", ".gpkg", ".kml", ".tab")):
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
        else:
            from qgis.core import QgsRasterLayer

            layer = QgsRasterLayer(file_path, layer_name)

        if not layer.isValid():
            return self.error("Invalid file path or unsupported layer format")

        self.add_map_layer(layer)
        session = None
        if map_session:
            session = self.ensure_map_session(map_session=map_session, create_new=False)
            self.register_layer_with_session(session, layer, role=role, owned=True, include_in_layout=True, source_tag=layer_name)
        artifacts = {"layer": self.artifact_for_layer(layer)}
        artifacts.update(self.session_artifacts(session))
        return self.success("Layer added", artifacts=artifacts, **self.artifact_for_layer(layer))

    def set_layer_z_order(self, layer_id=None, layer_name=None, position="top"):
        try:
            layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)
            root = self.project.layerTreeRoot()
            layer_node = root.findLayer(layer.id())
            if not layer_node:
                return self.error("Layer tree node not found")

            parent = layer_node.parent()
            clone = layer_node.clone()
            if position == "bottom":
                parent.addChildNode(clone)
            else:
                parent.insertChildNode(0, clone)
            parent.removeChildNode(layer_node)
            return self.success(
                "Layer order updated",
                data={"position": position},
                artifacts={"layer": self.artifact_for_layer(layer)},
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def set_layer_visibility(self, layer_id=None, layer_name=None, visible=True):
        try:
            layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)

            def _set_visibility():
                root = self.project.layerTreeRoot()
                layer_node = root.findLayer(layer.id()) if root else None
                if not layer_node:
                    raise ValueError("Layer tree node not found")
                layer_node.setItemVisibilityChecked(bool(visible))
                if self.iface:
                    self.iface.layerTreeView().refreshLayerSymbology(layer.id())
                    self.iface.mapCanvas().refresh()

            self.call_in_main_thread(_set_visibility)
            return self.success(
                "Layer visibility updated",
                data={"visible": bool(visible)},
                artifacts={"layer": self.artifact_for_layer(layer)},
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def set_active_layer(self, layer_id=None, layer_name=None):
        try:
            if not self.iface:
                return self.error("QGIS interface is unavailable")
            layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)

            def _activate():
                self.iface.setActiveLayer(layer)
                try:
                    self.iface.layerTreeView().setCurrentLayer(layer)
                except Exception:
                    pass

            self.call_in_main_thread(_activate)
            return self.success(
                "Active layer updated",
                artifacts={"layer": self.artifact_for_layer(layer)},
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def fly_to(self, lat, lon, scale):
        try:
            if not self.iface:
                return self.error("QGIS interface is unavailable")
            canvas = self.iface.mapCanvas()
            point = QgsPointXY(float(lon), float(lat))
            src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            dst_crs = canvas.mapSettings().destinationCrs()
            if src_crs != dst_crs:
                transform = QgsCoordinateTransform(src_crs, dst_crs, self.project)
                point = transform.transform(point)
            canvas.setCenter(point)
            canvas.zoomScale(float(scale))
            canvas.refresh()
            return self.success("Canvas moved", data={"center": {"x": point.x(), "y": point.y()}, "scale": float(scale)})
        except Exception as exc:
            return self.error(str(exc))

    def zoom_to_layer(self, layer_id=None, layer_name=None):
        try:
            if not self.iface:
                return self.error("QGIS interface is unavailable")
            layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)
            canvas = self.iface.mapCanvas()
            extent = layer.extent()
            layer_crs = layer.crs()
            canvas_crs = canvas.mapSettings().destinationCrs()

            if layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, self.project)
                extent = transform.transformBoundingBox(extent)

            if extent.isEmpty():
                return self.error("Layer extent is empty")

            extent.scale(1.1)
            canvas.setExtent(extent)
            canvas.refresh()
            return self.success(
                "Canvas zoomed to layer",
                artifacts={"layer": self.artifact_for_layer(layer)},
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def prepare_layer(
        self,
        layer_id=None,
        layer_name=None,
        fix_geometry=True,
        reproject_to=None,
        force_points=False,
        map_session=None,
    ):
        try:
            original_layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            working_layer = original_layer
            warnings = []
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None

            if session:
                self.register_layer_with_session(session, original_layer, owned=False, include_in_layout=True)

            if fix_geometry and self.layer_has_invalid_geometry(working_layer):
                fix_algorithm = self.find_processing_algorithm(["native:fixgeometries"])
                if not fix_algorithm:
                    return self.error("Invalid geometries detected, but fix geometries algorithm is unavailable")
                result = self.run_processing_with_supported_params(
                    fix_algorithm,
                    {"INPUT": working_layer, "OUTPUT": "TEMPORARY_OUTPUT"},
                )
                fixed_layer = None
                for value in result.values():
                    fixed_layer = self.load_result_layer(
                        value,
                        f"{working_layer.name()}_fixed",
                        map_session=map_session,
                        include_in_layout=False,
                        source_tag="fixed",
                    )
                    if fixed_layer:
                        break
                if not fixed_layer:
                    return self.error("Failed to load fixed geometry layer")
                working_layer = fixed_layer
                warnings.append("invalid_geometries_fixed")

            if reproject_to:
                target_crs = QgsCoordinateReferenceSystem(reproject_to)
                if not target_crs.isValid():
                    return self.error(f"Invalid CRS: {reproject_to}")
                if working_layer.crs() != target_crs:
                    reproject_algorithm = self.find_processing_algorithm(["native:reprojectlayer"])
                    if not reproject_algorithm:
                        return self.error("Reproject algorithm is unavailable")
                    result = self.run_processing_with_supported_params(
                        reproject_algorithm,
                        {
                            "INPUT": working_layer,
                            "TARGET_CRS": target_crs,
                            "OUTPUT": "TEMPORARY_OUTPUT",
                        },
                    )
                    reprojected_layer = None
                    for value in result.values():
                        reprojected_layer = self.load_result_layer(
                            value,
                            f"{working_layer.name()}_{target_crs.authid().replace(':', '_')}",
                            map_session=map_session,
                            include_in_layout=True,
                            source_tag="reprojected",
                        )
                        if reprojected_layer:
                            break
                    if not reprojected_layer:
                        return self.error("Failed to load reprojected layer")
                    working_layer = reprojected_layer
                    warnings.append(f"reprojected_to_{target_crs.authid()}")

            if force_points and working_layer.geometryType() != QgsWkbTypes.PointGeometry:
                working_layer = self.create_centroids_from_layer(
                    working_layer,
                    output_name=f"{working_layer.name()}_points",
                    map_session=map_session,
                    include_in_layout=True,
                )
                warnings.append("converted_to_points")

            artifacts = {
                "original_layer": self.artifact_for_layer(original_layer),
                "result_layer": self.artifact_for_layer(working_layer),
            }
            artifacts.update(self.session_artifacts(session))
            return self.success(
                "Layer prepared",
                data={"source_layer": original_layer.name(), "result_layer": working_layer.name()},
                warnings=warnings,
                artifacts=artifacts,
                **self.artifact_for_layer(working_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def calculate_field(self, layer_id=None, layer_name=None, field_name=None, expression=None, field_type="double"):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            self.require_field(layer, field_name) if layer.fields().indexFromName(field_name) >= 0 else None

            if not expression:
                return self.error("Expression is required")

            field_variant = FIELD_TYPE_MAP.get(str(field_type).lower(), QVariant.Double)
            expression_object = QgsExpression(expression)
            if expression_object.hasParserError():
                return self.error(expression_object.parserErrorString())

            if not layer.isEditable() and not layer.startEditing():
                return self.error("Failed to start editing layer")

            field_index = layer.fields().indexFromName(field_name)
            warnings = []
            if field_index < 0:
                provider = layer.dataProvider()
                provider.addAttributes([QgsField(field_name, field_variant)])
                layer.updateFields()
                field_index = layer.fields().indexFromName(field_name)
            else:
                warnings.append("field_already_exists")

            context = QgsExpressionContext()
            for scope in QgsExpressionContextUtils.globalProjectLayerScopes(layer):
                context.appendScope(scope)

            updated = 0
            for feature in layer.getFeatures():
                context.setFeature(feature)
                value = expression_object.evaluate(context)
                if expression_object.hasEvalError():
                    continue
                layer.changeAttributeValue(feature.id(), field_index, value)
                updated += 1

            if not layer.commitChanges():
                layer.rollBack()
                return self.error("Failed to commit calculated field changes")

            return self.success(
                "Field calculated",
                data={"field_name": field_name, "updated_features": updated},
                warnings=warnings,
                artifacts={"layer": self.artifact_for_layer(layer)},
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def filter_layer(self, layer_id=None, layer_name=None, expression=None, output_name=None, map_session=None):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            if not expression:
                return self.error("Expression is required")

            expression_object = QgsExpression(expression)
            if expression_object.hasParserError():
                return self.error(expression_object.parserErrorString())

            memory_layer = QgsVectorLayer(
                f"{QgsWkbTypes.displayString(layer.wkbType())}?crs={layer.crs().authid()}",
                output_name or f"{layer.name()}_filtered",
                "memory",
            )
            provider = memory_layer.dataProvider()
            provider.addAttributes(layer.fields())
            memory_layer.updateFields()

            request = QgsFeatureRequest().setFilterExpression(expression)
            copied = []
            for feature in layer.getFeatures(request):
                new_feature = QgsFeature(memory_layer.fields())
                new_feature.setGeometry(feature.geometry())
                new_feature.setAttributes(feature.attributes())
                copied.append(new_feature)

            provider.addFeatures(copied)
            memory_layer.updateExtents()
            self.add_map_layer(memory_layer)
            session = None
            if map_session:
                session = self.ensure_map_session(map_session=map_session, create_new=False)
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
                self.register_layer_with_session(session, memory_layer, owned=True, include_in_layout=True)

            artifacts = {"layer": self.artifact_for_layer(memory_layer)}
            artifacts.update(self.session_artifacts(session))
            return self.success(
                "Filtered layer created",
                data={"match_count": len(copied), "expression": expression},
                artifacts=artifacts,
                **self.artifact_for_layer(memory_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def join_attributes(self, target_layer, join_layer, target_field, join_field, fields=None, map_session=None):
        try:
            target = self.require_vector_layer(layer_name=target_layer)
            join = self.require_vector_layer(layer_name=join_layer)
            self.require_field(target, target_field)
            self.require_field(join, join_field)

            if isinstance(fields, str):
                fields = [fields]
            join_field_names = fields or [field.name() for field in join.fields() if field.name() != join_field]

            join_index = {}
            duplicate_count = 0
            for feature in join.getFeatures():
                key = feature[join_field]
                if key in join_index:
                    duplicate_count += 1
                    continue
                join_index[key] = feature

            memory_layer = QgsVectorLayer(
                f"{QgsWkbTypes.displayString(target.wkbType())}?crs={target.crs().authid()}",
                f"{target.name()}_joined",
                "memory",
            )
            provider = memory_layer.dataProvider()
            provider.addAttributes(target.fields())
            extra_fields = []
            for field_name in join_field_names:
                if join.fields().indexFromName(field_name) < 0:
                    continue
                source_field = join.fields().field(join.fields().indexFromName(field_name))
                alias = field_name if memory_layer.fields().indexFromName(field_name) < 0 else f"join_{field_name}"
                extra_fields.append((field_name, alias))
                provider.addAttributes([QgsField(alias, source_field.type())])
            memory_layer.updateFields()

            created = []
            for feature in target.getFeatures():
                key = feature[target_field]
                join_feature = join_index.get(key)
                output_feature = QgsFeature(memory_layer.fields())
                output_feature.setGeometry(feature.geometry())
                attributes = list(feature.attributes())
                for field_name, _alias in extra_fields:
                    attributes.append(join_feature[field_name] if join_feature else None)
                output_feature.setAttributes(attributes)
                created.append(output_feature)

            provider.addFeatures(created)
            memory_layer.updateExtents()
            self.add_map_layer(memory_layer)
            session = None
            if map_session:
                session = self.ensure_map_session(map_session=map_session, create_new=False)
                self.register_layer_with_session(session, target, owned=False, include_in_layout=True)
                self.register_layer_with_session(session, join, owned=False, is_reference=True, include_in_layout=True)
                self.register_layer_with_session(session, memory_layer, owned=True, include_in_layout=True)

            warnings = ["duplicate_join_keys_ignored"] if duplicate_count else []
            return self.success(
                "Attributes joined",
                data={"output_features": len(created), "joined_fields": [alias for _, alias in extra_fields]},
                warnings=warnings,
                artifacts=dict({"layer": self.artifact_for_layer(memory_layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(memory_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_centroids(self, layer_id=None, layer_name=None, output_name=None, map_session=None):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            if map_session:
                session = self.ensure_map_session(map_session=map_session, create_new=False)
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
            else:
                session = None
            centroid_layer = self.create_centroids_from_layer(
                layer,
                output_name=output_name or f"{layer.name()}_centroids",
                map_session=map_session,
                include_in_layout=True,
            )
            return self.success(
                "Centroid layer created",
                artifacts=dict({"layer": self.artifact_for_layer(centroid_layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(centroid_layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def create_connection_lines(
        self,
        origins_layer,
        destinations_layer,
        origin_id_field,
        destination_id_field,
        output_name=None,
        map_session=None,
    ):
        try:
            origins = self.require_vector_layer(layer_name=origins_layer)
            destinations = self.require_vector_layer(layer_name=destinations_layer)
            self.require_field(origins, origin_id_field)
            self.require_field(destinations, destination_id_field)

            target_crs = origins.crs() if origins.crs().isValid() else destinations.crs()
            destination_lookup = {}
            for destination in destinations.getFeatures():
                destination_lookup.setdefault(destination[destination_id_field], []).append(destination)

            memory_layer = QgsVectorLayer(
                f"LineString?crs={target_crs.authid()}",
                output_name or f"{origins.name()}_{destinations.name()}_connections",
                "memory",
            )
            provider = memory_layer.dataProvider()
            provider.addAttributes(
                [
                    QgsField("origin_key", QVariant.String),
                    QgsField("dest_key", QVariant.String),
                ]
            )
            memory_layer.updateFields()

            created = []
            for origin in origins.getFeatures():
                matches = destination_lookup.get(origin[origin_id_field], [])
                if not matches:
                    continue

                origin_geom = origin.geometry()
                origin_point = origin_geom.asPoint() if origins.geometryType() == QgsWkbTypes.PointGeometry else origin_geom.centroid().asPoint()
                origin_point = QgsPointXY(origin_point)
                if origins.crs() != target_crs:
                    transform = QgsCoordinateTransform(origins.crs(), target_crs, self.project)
                    origin_point = transform.transform(origin_point)

                for destination in matches:
                    destination_geom = destination.geometry()
                    destination_point = destination_geom.asPoint() if destinations.geometryType() == QgsWkbTypes.PointGeometry else destination_geom.centroid().asPoint()
                    destination_point = QgsPointXY(destination_point)
                    if destinations.crs() != target_crs:
                        transform = QgsCoordinateTransform(destinations.crs(), target_crs, self.project)
                        destination_point = transform.transform(destination_point)

                    feature = QgsFeature(memory_layer.fields())
                    feature.setGeometry(QgsGeometry.fromPolylineXY([origin_point, destination_point]))
                    feature["origin_key"] = str(origin[origin_id_field])
                    feature["dest_key"] = str(destination[destination_id_field])
                    created.append(feature)

            provider.addFeatures(created)
            memory_layer.updateExtents()
            self.add_map_layer(memory_layer)
            session = None
            if map_session:
                session = self.ensure_map_session(map_session=map_session, create_new=False)
                self.register_layer_with_session(session, origins, owned=False, include_in_layout=True)
                self.register_layer_with_session(session, destinations, owned=False, is_reference=True, include_in_layout=True)
                self.register_layer_with_session(session, memory_layer, role="line", owned=True, include_in_layout=True, source_tag="connections")

            return self.success(
                "Connection lines created",
                data={"line_count": len(created)},
                artifacts=dict({"layer": self.artifact_for_layer(memory_layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(memory_layer),
            )
        except Exception as exc:
            return self.error(str(exc))
