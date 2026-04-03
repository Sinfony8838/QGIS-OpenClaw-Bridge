import builtins
import contextlib
import io
import json
import math
import os
import tempfile
import traceback

import qgis.core as qgis_core
import qgis.gui as qgis_gui
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    import processing
except ImportError:
    processing = None

from .response_utils import error_response, success_response
from .session_utils import (
    DEFAULT_CHART_SLOT,
    DEFAULT_GROUP_PREFIX,
    DEFAULT_LAYOUT_NAME,
    build_layer_id_sequence,
    chart_slot_position,
    normalize_role,
    ordered_session_entries,
    slugify_text,
    unique_name,
)


class BaseGeoAIService:
    def __init__(self, server):
        self.server = server

    @property
    def iface(self):
        return self.server.iface

    @property
    def project(self):
        return QgsProject.instance()

    @property
    def map_sessions(self):
        return self.server.map_sessions

    def call_in_main_thread(self, func, *args, **kwargs):
        callback = getattr(self.server, "call_in_main_thread", None)
        if callable(callback):
            return callback(func, *args, **kwargs)
        return func(*args, **kwargs)

    def success(self, message="", data=None, warnings=None, artifacts=None, **extra):
        return success_response(message=message, data=data, warnings=warnings, artifacts=artifacts, **extra)

    def error(self, message, data=None, warnings=None, artifacts=None, **extra):
        return error_response(message=message, data=data, warnings=warnings, artifacts=artifacts, **extra)

    def log(self, channel, message, level=Qgis.Info):
        try:
            QgsMessageLog.logMessage(f"[{channel}] {message}", "GeoAI", level)
        except Exception:
            print(f"[GeoAI][{channel}] {message}")

    def push_banner(self, text, level=Qgis.Info):
        self.log("tool", text, level=level)
        if self.iface:
            def _push():
                self.iface.messageBar().pushMessage("GeoAI", text, level=level, duration=5)

            self.call_in_main_thread(_push)

    def refresh_layer(self, layer):
        def _refresh():
            layer.triggerRepaint()
            if self.iface:
                self.iface.layerTreeView().refreshLayerSymbology(layer.id())
                self.iface.mapCanvas().refresh()

        self.call_in_main_thread(_refresh)

    def emit_chart_preview(self, image_path, title, summary):
        callback = getattr(self.server, "chart_preview_callback", None)
        if callable(callback):
            try:
                self.call_in_main_thread(callback, image_path=image_path, title=title, summary=summary)
            except TypeError:
                self.call_in_main_thread(callback, image_path, title, summary)

    def emit_execution_summary(self, title, summary_lines, artifacts=None):
        callback = getattr(self.server, "execution_summary_callback", None)
        if callable(callback):
            payload = {
                "title": title,
                "summary_lines": summary_lines or [],
                "artifacts": artifacts or {},
            }
            try:
                self.call_in_main_thread(callback, payload)
            except TypeError:
                self.call_in_main_thread(callback, title, summary_lines, artifacts or {})

    def resolve_layer(self, layer_id=None, layer_name=None):
        def _resolve():
            if layer_id:
                layer = self.project.mapLayer(layer_id)
                if layer:
                    return layer
            if layer_name:
                matches = self.project.mapLayersByName(layer_name)
                if matches:
                    return matches[0]
            return None

        return self.call_in_main_thread(_resolve)

    def require_layer(self, layer_id=None, layer_name=None):
        layer = self.resolve_layer(layer_id=layer_id, layer_name=layer_name)
        if not layer:
            raise ValueError("Layer not found")
        return layer

    def require_vector_layer(self, layer_id=None, layer_name=None):
        layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)
        if not isinstance(layer, QgsVectorLayer):
            raise ValueError("Layer must be a vector layer")
        return layer

    def require_field(self, layer, field_name):
        if not field_name:
            raise ValueError("Field name is required")
        if layer.fields().indexFromName(field_name) < 0:
            raise ValueError(f"Field not found: {field_name}")

    def next_map_session_id(self, title=None):
        self.server.map_session_counter += 1
        return f"map_{self.server.map_session_counter}_{slugify_text(title, fallback='output')}"

    def project_layout_names(self):
        def _project_layout_names():
            manager = self.project.layoutManager()
            candidates = manager.printLayouts() if hasattr(manager, "printLayouts") else manager.layouts()
            layouts = []
            for candidate in candidates:
                layout_name = getattr(candidate, "name", None)
                if callable(layout_name):
                    layouts.append(layout_name())
                elif layout_name:
                    layouts.append(layout_name)
            return layouts

        return self.call_in_main_thread(_project_layout_names)

    def resolve_session_layout_name(self, session, requested_layout_name=None):
        existing_names = set(self.project_layout_names())
        for session_id, session_data in self.map_sessions.items():
            if session_id == session["map_session"]:
                continue
            layout_name = session_data.get("layout_name")
            if layout_name:
                existing_names.add(layout_name)
        return unique_name(
            requested_layout_name or session.get("requested_layout_name") or DEFAULT_LAYOUT_NAME,
            existing_names,
            suffix_hint=session["map_session"],
        )

    def resolve_reference_layers(self, reference_layers):
        if reference_layers in (None, "", []):
            return []
        values = reference_layers
        if isinstance(values, (str, dict)):
            values = [values]

        resolved = []
        seen = set()
        for item in values:
            layer = None
            if isinstance(item, dict):
                layer = self.resolve_layer(layer_id=item.get("layer_id"), layer_name=item.get("layer_name") or item.get("name"))
            else:
                layer = self.resolve_layer(layer_id=str(item), layer_name=str(item))
            if layer and layer.id() not in seen:
                seen.add(layer.id())
                resolved.append(layer)
        return resolved

    def get_visible_canvas_layers(self):
        def _visible_layers():
            layers = []
            if self.iface and hasattr(self.iface.mapCanvas(), "layers"):
                try:
                    layers = [layer for layer in self.iface.mapCanvas().layers() if layer]
                except Exception:
                    layers = []
            if layers:
                return layers

            root = self.project.layerTreeRoot()
            visible = []

            def collect(group):
                for child in group.children():
                    if hasattr(child, "layerId"):
                        layer = self.project.mapLayer(child.layerId())
                        child_visible = True
                        if hasattr(child, "isVisible"):
                            try:
                                child_visible = child.isVisible()
                            except Exception:
                                child_visible = True
                        if layer and child_visible:
                            visible.append(layer)
                    elif hasattr(child, "children"):
                        collect(child)

            collect(root)
            return visible

        return self.call_in_main_thread(_visible_layers)

    def create_map_session(
        self,
        map_session=None,
        title="GeoAI Output",
        layout_name=DEFAULT_LAYOUT_NAME,
        reference_layers=None,
        extent_mode="session_union",
    ):
        session_id = map_session or self.next_map_session_id(title=title)
        session = self.map_sessions.get(session_id)
        if session:
            if title:
                session["title"] = title
            if layout_name:
                session["requested_layout_name"] = layout_name
            if extent_mode:
                session["extent_mode"] = extent_mode
        else:
            session = {
                "map_session": session_id,
                "title": title or "GeoAI Output",
                "requested_layout_name": layout_name or DEFAULT_LAYOUT_NAME,
                "layout_name": None,
                "extent_mode": extent_mode or "session_union",
                "group_name": f"{DEFAULT_GROUP_PREFIX} {session_id}",
                "entries": {},
                "next_order": 0,
                "chart_slots": {},
            }
            self.map_sessions[session_id] = session

        for layer in self.resolve_reference_layers(reference_layers):
            self.register_layer_with_session(
                session,
                layer,
                owned=False,
                is_reference=True,
                include_in_layout=True,
            )

        if not session.get("layout_name"):
            session["layout_name"] = self.resolve_session_layout_name(session, session.get("requested_layout_name"))
        return session

    def ensure_map_session(
        self,
        map_session=None,
        title="GeoAI Output",
        layout_name=DEFAULT_LAYOUT_NAME,
        reference_layers=None,
        extent_mode="session_union",
        create_new=False,
        snapshot_visible_layers=False,
    ):
        if map_session and map_session in self.map_sessions:
            session = self.create_map_session(
                map_session=map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
            )
        else:
            session = self.create_map_session(
                map_session=None if create_new or not map_session else map_session,
                title=title,
                layout_name=layout_name,
                reference_layers=reference_layers,
                extent_mode=extent_mode,
            )
        if snapshot_visible_layers and not session["entries"]:
            for layer in self.get_visible_canvas_layers():
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
        return session

    def session_artifacts(self, session):
        if not session:
            return {}
        artifacts = {
            "map_session": session["map_session"],
            "layer_group": session.get("group_name"),
        }
        if session.get("layout_name"):
            artifacts["layout"] = self.artifact_for_layout(
                session["layout_name"],
                map_session=session["map_session"],
                layer_group=session.get("group_name"),
            )
        return artifacts

    def infer_layer_role(self, layer, role_hint=None, source_tag=None):
        explicit_role = normalize_role(role_hint, fallback=None) if role_hint else None
        if explicit_role:
            return explicit_role

        source_value = str(source_tag or "").lower()
        if "heatmap" in source_value:
            return "surface"
        if any(token in source_value for token in ("flow", "arrow", "migration")):
            return "flow_line"
        if any(token in source_value for token in ("comparison", "hu_huanyong", "hu line")):
            return "comparison_line"
        if any(token in source_value for token in ("boundary", "outline")):
            return "boundary"

        if isinstance(layer, QgsRasterLayer):
            return "raster"
        if isinstance(layer, QgsVectorLayer):
            geometry_type = layer.geometryType()
            if geometry_type == QgsWkbTypes.PointGeometry:
                return "point"
            if geometry_type == QgsWkbTypes.LineGeometry:
                return "line"
            if geometry_type == QgsWkbTypes.PolygonGeometry:
                return "polygon"
        return "default"

    def find_layer_group(self, root, group_name):
        if hasattr(root, "findGroup"):
            group = root.findGroup(group_name)
            if group:
                return group
        for child in root.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                return child
            if hasattr(child, "children"):
                group = self.find_layer_group(child, group_name)
                if group:
                    return group
        return None

    def ensure_session_group(self, session):
        def _ensure_group():
            root = self.project.layerTreeRoot()
            group = self.find_layer_group(root, session["group_name"])
            if group:
                return group
            return root.addGroup(session["group_name"])

        return self.call_in_main_thread(_ensure_group)

    def move_layer_to_group(self, layer, group):
        def _move_layer():
            root = self.project.layerTreeRoot()
            layer_node = root.findLayer(layer.id())
            if not layer_node:
                return
            if layer_node.parent() == group:
                return
            parent = layer_node.parent()
            clone = layer_node.clone()
            group.insertChildNode(0, clone)
            if parent:
                parent.removeChildNode(layer_node)

        self.call_in_main_thread(_move_layer)

    def apply_session_group_order(self, session):
        def _apply_order():
            group = self.ensure_session_group(session)
            owned_entries = [entry for entry in session["entries"].values() if entry.get("owned")]
            ordered_ids = build_layer_id_sequence(owned_entries, include_reference=False)
            if ordered_ids:
                self.reorder_layer_tree(group, ordered_ids)

        self.call_in_main_thread(_apply_order)

    def register_layer_with_session(
        self,
        session,
        layer,
        role=None,
        owned=False,
        is_reference=False,
        include_in_layout=True,
        source_tag=None,
    ):
        if not session or not layer:
            return None

        entry = session["entries"].get(layer.id())
        if not entry:
            session["next_order"] += 1
            entry = {
                "layer_id": layer.id(),
                "layer_name": layer.name(),
                "role": self.infer_layer_role(layer, role_hint=role, source_tag=source_tag),
                "order": session["next_order"],
                "owned": bool(owned),
                "is_reference": bool(is_reference),
                "include_in_layout": bool(include_in_layout),
            }
            session["entries"][layer.id()] = entry
        else:
            entry["layer_name"] = layer.name()
            if role:
                entry["role"] = self.infer_layer_role(layer, role_hint=role, source_tag=source_tag)
            entry["owned"] = entry.get("owned", False) or bool(owned)
            entry["is_reference"] = entry.get("is_reference", False) or bool(is_reference)
            entry["include_in_layout"] = entry.get("include_in_layout", False) or bool(include_in_layout)

        if entry.get("owned"):
            group = self.ensure_session_group(session)
            self.move_layer_to_group(layer, group)
            self.apply_session_group_order(session)
        return entry

    def session_entries(self, session, include_reference=True):
        entries = list((session or {}).get("entries", {}).values())
        if not include_reference:
            entries = [entry for entry in entries if not entry.get("is_reference")]
        return [entry for entry in entries if entry.get("include_in_layout", True)]

    def session_layer_ids(self, session, include_reference=True):
        return build_layer_id_sequence(self.session_entries(session, include_reference=include_reference), include_reference=include_reference)

    def session_layers(self, session, include_reference=True):
        def _session_layers():
            layers = []
            for layer_id in self.session_layer_ids(session, include_reference=include_reference):
                layer = self.project.mapLayer(layer_id)
                if layer:
                    layers.append(layer)
            return layers

        return self.call_in_main_thread(_session_layers)

    def session_extent(self, session, extent_mode="session_union"):
        def _session_extent():
            if not session:
                return self.iface.mapCanvas().extent() if self.iface else None
            if extent_mode != "session_union":
                return self.iface.mapCanvas().extent() if self.iface else None

            target_crs = self.project.crs()
            if not target_crs.isValid() and self.iface:
                target_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

            combined = None
            for layer in self.session_layers(session):
                if not hasattr(layer, "extent"):
                    continue
                extent = layer.extent()
                if not extent or extent.isEmpty():
                    continue
                try:
                    if target_crs.isValid() and hasattr(layer, "crs") and layer.crs().isValid() and layer.crs() != target_crs:
                        transform = QgsCoordinateTransform(layer.crs(), target_crs, self.project)
                        extent = transform.transformBoundingBox(extent)
                except Exception:
                    pass

                if combined is None:
                    combined = QgsRectangle(extent)
                else:
                    combined.combineExtentWith(extent)

            if combined:
                combined.scale(1.08)
                return combined
            return self.iface.mapCanvas().extent() if self.iface else None

        return self.call_in_main_thread(_session_extent)

    def apply_session_to_map_item(self, map_item, session):
        def _apply():
            if not map_item or not session:
                return
            layers = self.session_layers(session)
            if hasattr(map_item, "setKeepLayerSet"):
                map_item.setKeepLayerSet(True)
            if hasattr(map_item, "setFollowVisibilityPreset"):
                try:
                    map_item.setFollowVisibilityPreset(False)
                except Exception:
                    pass
            if hasattr(map_item, "setLayers"):
                map_item.setLayers(layers)
            extent = self.session_extent(session, extent_mode=session.get("extent_mode"))
            if extent:
                if hasattr(map_item, "zoomToExtent"):
                    map_item.zoomToExtent(extent)
                elif hasattr(map_item, "setExtent"):
                    map_item.setExtent(extent)

        self.call_in_main_thread(_apply)

    def prune_layer_tree_to_allowed(self, group, allowed_ids):
        for child in list(group.children()):
            if hasattr(child, "layerId"):
                if child.layerId() not in allowed_ids:
                    group.removeChildNode(child)
            elif hasattr(child, "children"):
                self.prune_layer_tree_to_allowed(child, allowed_ids)
                if not child.children():
                    group.removeChildNode(child)

    def clone_session_layer_tree(self, session):
        def _clone():
            cloned_root = self.project.layerTreeRoot().clone()
            allowed_ids = set(self.session_layer_ids(session))
            self.prune_layer_tree_to_allowed(cloned_root, allowed_ids)
            self.reorder_layer_tree(cloned_root, self.session_layer_ids(session))
            return cloned_root

        return self.call_in_main_thread(_clone)

    def find_layout_item_by_id(self, layout, item_id):
        for item in layout.items():
            item_getter = getattr(item, "id", None)
            if callable(item_getter):
                if item_getter() == item_id:
                    return item
            elif item_getter == item_id:
                return item
        return None

    def artifact_for_layer(self, layer):
        if not layer:
            return {}
        payload = {
            "layer_id": layer.id(),
            "layer_name": layer.name(),
        }
        if hasattr(layer, "source"):
            payload["source"] = layer.source()
        if hasattr(layer, "crs") and layer.crs().isValid():
            payload["crs"] = layer.crs().authid()
        return payload

    def artifact_for_layout(self, layout_name, map_session=None, layer_group=None):
        if not layout_name:
            return {}
        payload = {"layout_name": layout_name}
        if map_session:
            payload["map_session"] = map_session
        if layer_group:
            payload["layer_group"] = layer_group
        return payload

    def add_map_layer(self, layer):
        if not layer:
            return None
        return self.call_in_main_thread(self.project.addMapLayer, layer)

    def load_result_layer(
        self,
        output,
        layer_name,
        map_session=None,
        role=None,
        owned=True,
        include_in_layout=True,
        source_tag=None,
    ):
        if isinstance(output, (QgsVectorLayer, QgsRasterLayer)):
            layer = output
        else:
            vector_layer = QgsVectorLayer(output, layer_name, "ogr")
            layer = vector_layer if vector_layer.isValid() else QgsRasterLayer(output, layer_name)
        if layer and layer.isValid():
            self.add_map_layer(layer)
            if map_session:
                session = self.ensure_map_session(map_session=map_session, create_new=False)
                self.register_layer_with_session(
                    session,
                    layer,
                    role=role,
                    owned=owned,
                    include_in_layout=include_in_layout,
                    source_tag=source_tag or layer_name,
                )
            return layer
        return None

    def coerce_output_target(self, output_mode, default_suffix=".tif"):
        if output_mode in (None, "", "memory", "temporary"):
            return "TEMPORARY_OUTPUT"
        if output_mode == "file":
            fd, file_path = tempfile.mkstemp(suffix=default_suffix)
            os.close(fd)
            return file_path
        return output_mode

    def find_processing_algorithm(self, candidates):
        registry = QgsApplication.processingRegistry()
        for candidate in candidates:
            if registry.algorithmById(candidate):
                return candidate
        return None

    def run_processing_with_supported_params(self, algorithm_id, params):
        if not processing:
            raise RuntimeError("QGIS processing module is unavailable")

        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if not algorithm:
            raise ValueError(f"Processing algorithm not found: {algorithm_id}")

        supported_names = {definition.name() for definition in algorithm.parameterDefinitions()}
        filtered_params = {key: value for key, value in params.items() if key in supported_names}
        try:
            return processing.run(algorithm_id, filtered_params)
        except Exception as exc:
            self.log("processing-error", f"{algorithm_id}: {exc}", level=Qgis.Warning)
            raise

    def layer_has_invalid_geometry(self, layer, sample_limit=1000):
        checked = 0
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry and not geometry.isEmpty() and not geometry.isGeosValid():
                return True
            checked += 1
            if checked >= sample_limit:
                break
        return False

    def create_centroids_from_layer(self, layer, output_name=None, map_session=None, include_in_layout=False):
        centroid_algorithm = self.find_processing_algorithm(["native:centroids", "qgis:centroids"])
        if not centroid_algorithm:
            raise RuntimeError("Centroid algorithm is unavailable in this QGIS environment")

        result = self.run_processing_with_supported_params(
            centroid_algorithm,
            {"INPUT": layer, "ALL_PARTS": False, "OUTPUT": "TEMPORARY_OUTPUT"},
        )
        centroid_layer = None
        for value in result.values():
            centroid_layer = self.load_result_layer(
                value,
                output_name or f"{layer.name()}_centroids",
                map_session=map_session,
                role="centroid",
                include_in_layout=include_in_layout,
                source_tag="centroid",
            )
            if centroid_layer:
                break
        if not centroid_layer:
            raise RuntimeError("Failed to load centroid output layer")
        return centroid_layer

    def prepare_heatmap_input_layer(self, layer, map_session=None):
        working_layer = layer
        warnings = []

        if self.layer_has_invalid_geometry(working_layer):
            fix_algorithm = self.find_processing_algorithm(["native:fixgeometries"])
            if not fix_algorithm:
                raise RuntimeError("Invalid geometries detected, but fix geometries algorithm is unavailable")

            fixed_result = self.run_processing_with_supported_params(
                fix_algorithm,
                {"INPUT": working_layer, "OUTPUT": "TEMPORARY_OUTPUT"},
            )
            fixed_layer = None
            for value in fixed_result.values():
                fixed_layer = self.load_result_layer(
                    value,
                    f"{layer.name()}_fixed",
                    map_session=map_session,
                    role="polygon",
                    include_in_layout=False,
                    source_tag="fixed",
                )
                if fixed_layer:
                    break
            if not fixed_layer:
                raise RuntimeError("Failed to load geometry-fixed layer for heatmap")

            working_layer = fixed_layer
            warnings.append("invalid_geometries_fixed")

        if working_layer.geometryType() != QgsWkbTypes.PointGeometry:
            working_layer = self.create_centroids_from_layer(
                working_layer,
                output_name=f"{layer.name()}_heatmap_points",
                map_session=map_session,
                include_in_layout=False,
            )
            warnings.append("converted_to_points")

        return working_layer, warnings

    def find_session_by_layout_name(self, layout_name):
        for session in self.map_sessions.values():
            if session.get("layout_name") == layout_name:
                return session
        return None

    def get_layout(self, layout_name=DEFAULT_LAYOUT_NAME, create_if_missing=False, title="GeoAI Output", map_session=None):
        def _get_layout():
            manager = self.project.layoutManager()
            actual_layout_name = layout_name
            session = self.map_sessions.get(map_session) if map_session else self.find_session_by_layout_name(layout_name)
            if session and session.get("layout_name"):
                actual_layout_name = session["layout_name"]
            layout = manager.layoutByName(actual_layout_name)
            if layout or not create_if_missing:
                return layout
            response = self.server.cartography_service.auto_layout(title=title, layout_name=actual_layout_name, map_session=map_session)
            if response.get("status") != "success":
                raise RuntimeError(response.get("message", "Failed to create layout"))
            return manager.layoutByName(actual_layout_name)

        return self.call_in_main_thread(_get_layout)

    def find_layout_item(self, layout, item_type):
        for item in layout.items():
            if isinstance(item, item_type):
                return item
        return None

    def reorder_layer_tree(self, group, wanted_order):
        if not wanted_order:
            return
        normalized = [str(item) for item in wanted_order]
        children = list(group.children())
        sortable = []
        leftovers = []
        for child in children:
            child_key = child.layerId() if hasattr(child, "layerId") else None
            child_name = child.name()
            if child_key in normalized:
                sortable.append((normalized.index(child_key), child))
            elif child_name in normalized:
                sortable.append((normalized.index(child_name), child))
            else:
                leftovers.append(child)

        ordered_children = [child for _, child in sorted(sortable, key=lambda item: item[0])] + leftovers
        for child in list(group.children()):
            group.removeChildNode(child)
        for child in ordered_children:
            group.addChildNode(child)

    def remove_hidden_layers(self, group, hidden_layers):
        if not hidden_layers:
            return
        hidden = {str(item) for item in hidden_layers}
        for child in list(group.children()):
            if hasattr(child, "layerId"):
                if child.layerId() in hidden or child.name() in hidden:
                    group.removeChildNode(child)
            elif hasattr(child, "children"):
                self.remove_hidden_layers(child, hidden_layers)
                if not child.children():
                    group.removeChildNode(child)

    def resolve_point(self, point, crs_authid):
        if isinstance(point, dict):
            x = point.get("x")
            y = point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
        else:
            raise ValueError("Point must be a dict or list")

        qgs_point = QgsPointXY(float(x), float(y))
        if crs_authid and crs_authid != "EPSG:4326":
            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                QgsCoordinateReferenceSystem(crs_authid),
                self.project,
            )
            qgs_point = transform.transform(qgs_point)
        return qgs_point

    def parse_layout_position(self, position):
        defaults = {"x": 205, "y": 25, "width": 85, "height": 55}
        if isinstance(position, dict):
            defaults.update({key: float(value) for key, value in position.items() if key in defaults})
        return defaults

    def resolve_chart_slot_position(self, session, chart_slot=None, base_position=None):
        slot_name = str(chart_slot or DEFAULT_CHART_SLOT)
        chart_slots = session.setdefault("chart_slots", {})
        if slot_name not in chart_slots:
            chart_slots[slot_name] = len(chart_slots)
        if base_position:
            return self.parse_layout_position(base_position)
        return chart_slot_position(chart_slots[slot_name], base_position=base_position)

    def normalize_vector(self, dx, dy):
        length = math.hypot(dx, dy)
        if length == 0:
            raise ValueError("Zero-length vector is not allowed")
        return dx / length, dy / length

    def rotate_vector(self, dx, dy, angle_radians):
        cos_value = math.cos(angle_radians)
        sin_value = math.sin(angle_radians)
        return (
            dx * cos_value - dy * sin_value,
            dx * sin_value + dy * cos_value,
        )

    def transform_point_xy(self, point, source_crs, target_crs):
        if source_crs == target_crs:
            return QgsPointXY(point)
        transform = QgsCoordinateTransform(source_crs, target_crs, self.project)
        return transform.transform(QgsPointXY(point))

    def classic_hu_points(self, target_crs):
        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        start = QgsPointXY(127.5, 50.25)
        end = QgsPointXY(98.5, 25.0)
        if target_crs != source_crs:
            transform = QgsCoordinateTransform(source_crs, target_crs, self.project)
            start = transform.transform(start)
            end = transform.transform(end)
        return start, end

    def line_side_value(self, point, anchor, direction):
        return (point.x() - anchor.x()) * direction[1] - (point.y() - anchor.y()) * direction[0]

    def feature_weighted_points(self, layer, weight_field, target_crs):
        self.require_field(layer, weight_field)
        weighted_points = []
        source_crs = layer.crs()
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue
            point = geometry.asPoint() if layer.geometryType() == QgsWkbTypes.PointGeometry else geometry.centroid().asPoint()
            point_xy = QgsPointXY(point)
            if source_crs != target_crs:
                transform = QgsCoordinateTransform(source_crs, target_crs, self.project)
                point_xy = transform.transform(point_xy)
            weight = float(feature[weight_field] or 0)
            if weight > 0:
                weighted_points.append((point_xy, weight))
        if not weighted_points:
            raise ValueError("No valid weighted points were found in the layer")
        return weighted_points

    def population_share_for_line(self, weighted_points, anchor, direction, reference_point):
        reference_side = self.line_side_value(reference_point, anchor, direction)
        if reference_side == 0:
            reference_side = 1.0
        total_weight = sum(weight for _, weight in weighted_points)
        side_weight = 0.0
        for point, weight in weighted_points:
            side_value = self.line_side_value(point, anchor, direction)
            if side_value == 0:
                side_weight += weight / 2.0
            elif side_value * reference_side > 0:
                side_weight += weight
        return side_weight / total_weight if total_weight else 0.0

    def segment_for_line(self, anchor, direction, weighted_points, scale_factor=3.0):
        xs = [point.x() for point, _ in weighted_points]
        ys = [point.y() for point, _ in weighted_points]
        diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        half_length = max(diagonal * scale_factor, 1.0)
        return (
            QgsPointXY(anchor.x() - direction[0] * half_length, anchor.y() - direction[1] * half_length),
            QgsPointXY(anchor.x() + direction[0] * half_length, anchor.y() + direction[1] * half_length),
        )

    def chart_summary(self, chart_type, data_points, image_path):
        return {
            "chart_type": chart_type,
            "point_count": len(data_points),
            "image_path": image_path,
            "points": data_points,
        }

    def serialize_python_value(self, value, depth=0):
        if depth > 3:
            return {"type": type(value).__name__, "repr": repr(value)}

        if value is None or isinstance(value, (bool, int, float, str)):
            return value

        if isinstance(value, dict):
            return {
                str(key): self.serialize_python_value(item, depth + 1)
                for key, item in list(value.items())[:50]
            }

        if isinstance(value, (list, tuple, set)):
            return [self.serialize_python_value(item, depth + 1) for item in list(value)[:50]]

        if isinstance(value, QgsPointXY):
            return {"type": "QgsPointXY", "x": value.x(), "y": value.y()}

        if isinstance(value, QgsGeometry):
            try:
                wkt = value.asWkt()
            except Exception:
                wkt = repr(value)
            if len(wkt) > 500:
                wkt = wkt[:500] + "...(truncated)"
            return {"type": "QgsGeometry", "wkt": wkt}

        if isinstance(value, QgsFeature):
            return {
                "type": "QgsFeature",
                "id": value.id(),
                "attributes": value.attributes(),
                "has_geometry": value.hasGeometry(),
            }

        if isinstance(value, (QgsVectorLayer, QgsRasterLayer)):
            return {
                "type": type(value).__name__,
                "id": value.id(),
                "name": value.name(),
                "source": value.source(),
                "crs": value.crs().authid() if value.crs().isValid() else None,
            }

        return {"type": type(value).__name__, "repr": repr(value)}

    def build_python_exec_context(self):
        context = {
            "__builtins__": builtins.__dict__,
            "iface": self.iface,
            "server": self.server,
            "project": self.project,
            "canvas": self.iface.mapCanvas() if self.iface else None,
            "processing": processing,
            "json": json,
            "math": math,
            "os": os,
            "tempfile": tempfile,
            "QgsProject": QgsProject,
            "QgisProject": QgsProject,
            "QgsFeature": QgsFeature,
            "QgsGeometry": QgsGeometry,
            "QgsPointXY": QgsPointXY,
            "QColor": QColor,
            "QFont": QFont,
        }

        for module in (qgis_core, qgis_gui):
            for name in dir(module):
                if name.startswith(("Qgs", "Qgis")) and name not in context:
                    context[name] = getattr(module, name)

        return context

    def execute_python_code(self, code, result_var="result"):
        if not code or not str(code).strip():
            return self.error("Python code is required")

        exec_globals = self.build_python_exec_context()
        exec_locals = {}
        stdout_buffer = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout_buffer):
                exec(code, exec_globals, exec_locals)
        except Exception as exc:
            return self.error(
                f"Python execution failed: {exc}",
                data={
                    "stdout": stdout_buffer.getvalue(),
                    "traceback": traceback.format_exc(),
                },
            )

        result = exec_locals.get(result_var, exec_globals.get(result_var))
        visible_locals = {
            key: self.serialize_python_value(value)
            for key, value in exec_locals.items()
            if not key.startswith("__")
        }

        return self.success(
            "Python code executed",
            data={
                "result_var": result_var,
                "result": self.serialize_python_value(result),
                "stdout": stdout_buffer.getvalue(),
                "locals": visible_locals,
            },
        )
