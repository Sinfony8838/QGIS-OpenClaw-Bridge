import math
import os
import tempfile

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRectangle,
    QgsSingleBandPseudoColorRenderer,
    QgsStyle,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    from qgis.analysis import QgsGridFileWriter, QgsInterpolator, QgsTinInterpolator
except ImportError:
    QgsGridFileWriter = None
    QgsInterpolator = None
    QgsTinInterpolator = None

try:
    import processing
except ImportError:
    processing = None

from .base_service import BaseGeoAIService
from .service_utils import (
    default_grid_spacing,
    default_profile_sample_distance,
    infer_terrain_source_kind,
    summarize_profile_samples,
)


DEFAULT_PROFILE_LINE_LAYER_NAME = "GeoAI_Profile_Line"
DEFAULT_PROFILE_SAMPLE_LAYER_NAME = "GeoAI_Profile_Samples"
PREFERRED_ELEVATION_FIELDS = (
    "elevation",
    "elev",
    "height",
    "z",
    "altitude",
    "alt",
    "dem",
)


class TerrainService(BaseGeoAIService):
    def create_terrain_profile(
        self,
        terrain_layer_id=None,
        terrain_layer_name=None,
        terrain_type="auto",
        elevation_field=None,
        profile_layer_id=None,
        profile_layer_name=None,
        profile_points=None,
        sample_distance=None,
        title="Terrain Profile",
        map_session=None,
    ):
        try:
            session = self.ensure_map_session(map_session=map_session, title=title, create_new=False) if map_session else None
            terrain_context = self._resolve_terrain_surface(
                terrain_layer_id=terrain_layer_id,
                terrain_layer_name=terrain_layer_name,
                terrain_type=terrain_type,
                elevation_field=elevation_field,
                title=title,
                map_session=map_session,
                include_in_layout=False,
                register_source=True,
            )

            profile_context = self._resolve_profile_line(
                profile_layer_id=profile_layer_id,
                profile_layer_name=profile_layer_name,
                profile_points=profile_points,
                map_session=map_session,
            )
            surface_layer = terrain_context["surface_layer"]
            sampling_geometry = self._geometry_in_layer_crs(
                profile_context["geometry"],
                profile_context["crs"],
                surface_layer.crs(),
            )

            total_length = sampling_geometry.length()
            step = float(sample_distance) if sample_distance else default_profile_sample_distance(total_length)
            if step <= 0:
                raise ValueError("sample_distance must be positive")

            sample_rows = self._sample_profile_geometry(surface_layer, sampling_geometry, step)
            stats = summarize_profile_samples(sample_rows)
            sample_points_layer = self._create_profile_sample_layer(
                sample_rows,
                surface_layer.crs(),
                output_name=DEFAULT_PROFILE_SAMPLE_LAYER_NAME,
                map_session=map_session,
            )
            image_path = self._render_profile_chart(title, sample_rows)

            preview_summary = {
                "chart_type": "terrain_profile",
                "point_count": stats["point_count"],
                "min_elevation": round(stats["min_elevation"], 4),
                "max_elevation": round(stats["max_elevation"], 4),
                "relief": round(stats["relief"], 4),
                "detail_lines": [
                    f"Samples: {stats['point_count']}",
                    f"Distance: {round(stats['total_distance'], 4)}",
                    f"Elevation: {round(stats['min_elevation'], 4)} - {round(stats['max_elevation'], 4)}",
                ],
            }
            self.emit_chart_preview(image_path, title, preview_summary)

            summary_lines = [
                f"Terrain source: {terrain_context['surface_layer'].name()}",
                f"Profile line: {profile_context['layer'].name()}",
                f"Samples: {stats['point_count']}",
                f"Total distance: {round(stats['total_distance'], 4)}",
                f"Elevation range: {round(stats['min_elevation'], 4)} - {round(stats['max_elevation'], 4)}",
            ]

            artifacts = {
                "chart_image": image_path,
                "profile_line_layer": self.artifact_for_layer(profile_context["layer"]),
                "sample_points_layer": self.artifact_for_layer(sample_points_layer),
                "surface_layer": self.artifact_for_layer(surface_layer),
            }
            if terrain_context.get("dem_layer") and terrain_context["dem_layer"].id() != surface_layer.id():
                artifacts["dem_layer"] = self.artifact_for_layer(terrain_context["dem_layer"])
            artifacts.update(self.session_artifacts(session))
            self.emit_execution_summary(title=title, summary_lines=summary_lines, artifacts=artifacts)

            data = {
                "terrain_type": terrain_context["terrain_mode"],
                "sample_distance": float(step),
                "points": sample_rows,
            }
            data.update(stats)
            if terrain_context.get("elevation_field"):
                data["elevation_field"] = terrain_context["elevation_field"]

            warnings = list(terrain_context.get("warnings", [])) + list(profile_context.get("warnings", []))
            return self.success("Terrain profile created", data=data, warnings=warnings, artifacts=artifacts)
        except Exception as exc:
            return self.error(str(exc))

    def create_terrain_model(
        self,
        terrain_layer_id=None,
        terrain_layer_name=None,
        terrain_type="auto",
        elevation_field=None,
        grid_spacing=None,
        vertical_exaggeration=1.5,
        create_hillshade=True,
        color_ramp="Terrain",
        title="Simplified Terrain Model",
        map_session=None,
    ):
        try:
            session = self.ensure_map_session(map_session=map_session, title=title, create_new=False) if map_session else None
            terrain_context = self._resolve_terrain_surface(
                terrain_layer_id=terrain_layer_id,
                terrain_layer_name=terrain_layer_name,
                terrain_type=terrain_type,
                elevation_field=elevation_field,
                title=title,
                map_session=map_session,
                include_in_layout=True,
                register_source=True,
                grid_spacing=grid_spacing,
            )
            surface_layer = terrain_context["surface_layer"]
            self._apply_terrain_color_ramp(surface_layer, color_ramp=color_ramp)

            hillshade_layer = None
            warnings = list(terrain_context.get("warnings", []))
            if create_hillshade:
                if not processing:
                    warnings.append("hillshade_skipped_processing_unavailable")
                else:
                    hillshade_layer = self._create_hillshade_layer(
                        surface_layer=surface_layer,
                        vertical_exaggeration=vertical_exaggeration,
                        map_session=map_session,
                    )

            artifacts = {
                "surface_layer": self.artifact_for_layer(surface_layer),
            }
            if terrain_context.get("dem_layer") and terrain_context["dem_layer"].id() != surface_layer.id():
                artifacts["dem_layer"] = self.artifact_for_layer(terrain_context["dem_layer"])
            if hillshade_layer:
                artifacts["hillshade_layer"] = self.artifact_for_layer(hillshade_layer)
            artifacts.update(self.session_artifacts(session))

            detail_lines = [
                f"Surface layer: {surface_layer.name()}",
                f"Terrain mode: {terrain_context['terrain_mode']}",
                f"Vertical exaggeration: {float(vertical_exaggeration)}",
            ]
            if hillshade_layer:
                detail_lines.append(f"Hillshade layer: {hillshade_layer.name()}")
            self.emit_chart_preview(
                None,
                title,
                {
                    "chart_type": "terrain_model",
                    "point_count": 0,
                    "detail_lines": detail_lines,
                },
            )
            self.emit_execution_summary(title=title, summary_lines=detail_lines, artifacts=artifacts)

            data = {
                "terrain_type": terrain_context["terrain_mode"],
                "surface_layer_name": surface_layer.name(),
                "used_interpolation": terrain_context["terrain_mode"] == "contours",
                "vertical_exaggeration": float(vertical_exaggeration),
                "color_ramp": color_ramp,
                "hillshade_enabled": bool(hillshade_layer),
            }
            if terrain_context.get("elevation_field"):
                data["elevation_field"] = terrain_context["elevation_field"]

            return self.success("Simplified terrain model created", data=data, warnings=warnings, artifacts=artifacts)
        except Exception as exc:
            return self.error(str(exc))

    def upsert_profile_line_layer(self, profile_points, layer_name=DEFAULT_PROFILE_LINE_LAYER_NAME, crs_authid=None, map_session=None):
        points = self._coerce_profile_points(profile_points)
        if len(points) < 2:
            raise ValueError("At least two profile points are required")

        target_crs = self._fallback_crs(crs_authid)
        existing_layer = self.resolve_layer(layer_name=layer_name)
        if existing_layer:
            self.call_in_main_thread(self.project.removeMapLayer, existing_layer.id())

        layer = QgsVectorLayer(f"LineString?crs={target_crs.authid()}", layer_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField("name", QVariant.String)])
        layer.updateFields()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(points))
        feature["name"] = layer_name
        provider.addFeature(feature)
        layer.updateExtents()
        self.add_map_layer(layer)

        if map_session:
            session = self.ensure_map_session(map_session=map_session, create_new=False)
            self.register_layer_with_session(
                session,
                layer,
                role="overlay_line",
                owned=True,
                include_in_layout=False,
                source_tag="terrain_profile_line",
            )
        return layer

    def clear_profile_line_layer(self, layer_name=DEFAULT_PROFILE_LINE_LAYER_NAME):
        layer = self.resolve_layer(layer_name=layer_name)
        if not layer:
            return False
        self.call_in_main_thread(self.project.removeMapLayer, layer.id())
        return True

    def detect_elevation_field(self, layer):
        candidates = []
        for field in layer.fields():
            if not self._is_numeric_field(field):
                continue
            candidates.append(field.name())
            lowered = field.name().strip().lower()
            if any(lowered == token or token in lowered for token in PREFERRED_ELEVATION_FIELDS):
                return field.name()
        return candidates[0] if candidates else None

    def _resolve_terrain_surface(
        self,
        terrain_layer_id=None,
        terrain_layer_name=None,
        terrain_type="auto",
        elevation_field=None,
        title="Terrain Output",
        map_session=None,
        include_in_layout=True,
        register_source=True,
        grid_spacing=None,
    ):
        layer = self.require_layer(layer_id=terrain_layer_id, layer_name=terrain_layer_name)
        layer_kind = self._terrain_layer_kind(layer)
        terrain_mode = infer_terrain_source_kind(terrain_type, layer_kind)
        warnings = []
        source_layer = layer
        dem_layer = layer if isinstance(layer, QgsRasterLayer) else None

        session = self.ensure_map_session(map_session=map_session, title=title, create_new=False) if map_session else None
        if session and register_source:
            self.register_layer_with_session(session, source_layer, owned=False, include_in_layout=include_in_layout)

        resolved_field = None
        if terrain_mode == "contours":
            contour_layer = self.require_vector_layer(layer_id=terrain_layer_id, layer_name=terrain_layer_name)
            resolved_field = elevation_field or self.detect_elevation_field(contour_layer)
            if not resolved_field:
                raise ValueError("Contour terrain input requires elevation_field or a detectable numeric elevation field")
            if not elevation_field:
                warnings.append(f"auto_detected_elevation_field:{resolved_field}")

            dem_layer = self._interpolate_contours_to_dem(
                contour_layer=contour_layer,
                elevation_field=resolved_field,
                grid_spacing=grid_spacing,
                output_name=f"{contour_layer.name()}_dem",
                map_session=map_session,
                include_in_layout=include_in_layout,
            )
            surface_layer = dem_layer
        else:
            if not isinstance(layer, QgsRasterLayer):
                raise ValueError("DEM terrain input must be a raster layer")
            surface_layer = layer

        return {
            "surface_layer": surface_layer,
            "source_layer": source_layer,
            "dem_layer": dem_layer,
            "terrain_mode": terrain_mode,
            "warnings": warnings,
            "elevation_field": resolved_field,
        }

    def _resolve_profile_line(self, profile_layer_id=None, profile_layer_name=None, profile_points=None, map_session=None):
        warnings = []
        if profile_points:
            layer = self.upsert_profile_line_layer(profile_points, map_session=map_session)
            geometry = self._first_line_geometry(layer)
            return {
                "layer": layer,
                "geometry": geometry,
                "crs": layer.crs(),
                "warnings": warnings,
            }

        layer = self.require_vector_layer(layer_id=profile_layer_id, layer_name=profile_layer_name or DEFAULT_PROFILE_LINE_LAYER_NAME)
        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            raise ValueError("Profile layer must be a line layer")
        geometry = self._first_line_geometry(layer)
        if sum(1 for _ in layer.getFeatures()) > 1:
            warnings.append("multiple_profile_features_detected:first_feature_used")
        return {
            "layer": layer,
            "geometry": geometry,
            "crs": layer.crs(),
            "warnings": warnings,
        }

    def _first_line_geometry(self, layer):
        for feature in layer.getFeatures():
            geometry = feature.geometry()
            if geometry and not geometry.isEmpty():
                return geometry
        raise ValueError("Profile layer does not contain a usable line geometry")

    def _coerce_profile_points(self, profile_points):
        points = []
        for item in profile_points or []:
            if hasattr(item, "x") and hasattr(item, "y") and callable(item.x) and callable(item.y):
                x = item.x()
                y = item.y()
            elif isinstance(item, dict):
                x = item.get("x")
                y = item.get("y")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                x, y = item[0], item[1]
            else:
                raise ValueError("Each profile point must be a dict with x/y or a two-item list")
            points.append(QgsPointXY(float(x), float(y)))
        return points

    def _fallback_crs(self, crs_authid=None):
        if crs_authid:
            crs = QgsCoordinateReferenceSystem(crs_authid)
            if crs.isValid():
                return crs
        if self.project.crs().isValid():
            return self.project.crs()
        return QgsCoordinateReferenceSystem("EPSG:4326")

    def _terrain_layer_kind(self, layer):
        if isinstance(layer, QgsRasterLayer):
            return "raster"
        if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.LineGeometry:
            return "line"
        raise ValueError("Terrain layer must be a raster DEM or a line contour layer")

    def _is_numeric_field(self, field):
        if hasattr(field, "isNumeric") and callable(field.isNumeric):
            try:
                return bool(field.isNumeric())
            except Exception:
                pass
        return field.type() in (
            QVariant.Int,
            QVariant.UInt,
            QVariant.LongLong,
            QVariant.ULongLong,
            QVariant.Double,
        )

    def _geometry_in_layer_crs(self, geometry, source_crs, target_crs):
        if not source_crs.isValid() or not target_crs.isValid() or source_crs == target_crs:
            return QgsGeometry(geometry)

        transformed = QgsGeometry(geometry)
        transform = QgsCoordinateTransform(source_crs, target_crs, self.project)
        transformed.transform(transform)
        return transformed

    def _sample_profile_geometry(self, raster_layer, geometry, sample_distance):
        total_length = geometry.length()
        if total_length <= 0:
            raise ValueError("Profile line length must be positive")

        sample_distances = []
        distance = 0.0
        while distance < total_length:
            sample_distances.append(distance)
            distance += float(sample_distance)
        if not sample_distances or sample_distances[-1] != total_length:
            sample_distances.append(total_length)

        rows = []
        provider = raster_layer.dataProvider()
        for distance_along in sample_distances:
            point_geometry = geometry.interpolate(distance_along)
            point = point_geometry.asPoint()
            sampled = provider.sample(QgsPointXY(point), 1)
            if isinstance(sampled, tuple):
                elevation, ok = sampled[0], bool(sampled[1])
            else:
                elevation = sampled
                ok = elevation is not None
            if not ok or elevation is None or (isinstance(elevation, float) and math.isnan(elevation)):
                continue
            rows.append(
                {
                    "distance": round(float(distance_along), 4),
                    "elevation": round(float(elevation), 4),
                    "x": round(point.x(), 6),
                    "y": round(point.y(), 6),
                }
            )

        if len(rows) < 2:
            raise ValueError("Unable to sample enough valid elevation points from the terrain layer")
        return rows

    def _create_profile_sample_layer(self, sample_rows, crs, output_name, map_session=None):
        existing_layer = self.resolve_layer(layer_name=output_name)
        if existing_layer:
            self.call_in_main_thread(self.project.removeMapLayer, existing_layer.id())

        layer = QgsVectorLayer(f"Point?crs={crs.authid()}", output_name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("distance", QVariant.Double),
                QgsField("elev", QVariant.Double),
            ]
        )
        layer.updateFields()

        features = []
        for row in sample_rows:
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(row["x"]), float(row["y"]))))
            feature["distance"] = float(row["distance"])
            feature["elev"] = float(row["elevation"])
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        self.add_map_layer(layer)

        if map_session:
            session = self.ensure_map_session(map_session=map_session, create_new=False)
            self.register_layer_with_session(
                session,
                layer,
                role="point",
                owned=True,
                include_in_layout=False,
                source_tag="terrain_profile_samples",
            )
        return layer

    def _render_profile_chart(self, title, sample_rows):
        try:
            import matplotlib

            matplotlib.use("Agg")
            from matplotlib import pyplot as plt
        except Exception as exc:
            raise RuntimeError(f"matplotlib is required for profile rendering: {exc}")

        distances = [row["distance"] for row in sample_rows]
        elevations = [row["elevation"] for row in sample_rows]
        baseline = min(elevations)

        figure, axis = plt.subplots(figsize=(8, 5))
        axis.plot(distances, elevations, color="#1d6fa5", linewidth=2.2)
        axis.fill_between(distances, elevations, baseline, color="#94c7df", alpha=0.38)
        axis.set_title(title)
        axis.set_xlabel("Distance")
        axis.set_ylabel("Elevation")
        axis.grid(True, alpha=0.22)
        figure.tight_layout()

        fd, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        figure.savefig(image_path, dpi=150)
        plt.close(figure)
        return image_path

    def _interpolate_contours_to_dem(
        self,
        contour_layer,
        elevation_field,
        grid_spacing=None,
        output_name="Contour_DEM",
        map_session=None,
        include_in_layout=True,
    ):
        if contour_layer.geometryType() != QgsWkbTypes.LineGeometry:
            raise ValueError("Contour input must be a line layer")
        if QgsInterpolator is None or QgsTinInterpolator is None or QgsGridFileWriter is None:
            raise RuntimeError("QGIS interpolation classes are unavailable in this environment")

        point_layer = self._contour_vertices_to_points(contour_layer, elevation_field)
        extent = QgsRectangle(contour_layer.extent())
        if extent.isEmpty():
            raise ValueError("Contour layer extent is empty")
        extent.scale(1.02)
        cell_size = float(grid_spacing) if grid_spacing else default_grid_spacing(extent.width(), extent.height())

        output_path = self.coerce_output_target("file", default_suffix=".tif")
        self._write_interpolated_raster(point_layer, elevation_field, extent, cell_size, output_path)
        return self.load_result_layer(
            output_path,
            output_name,
            map_session=map_session,
            role="raster",
            owned=True,
            include_in_layout=include_in_layout,
            source_tag="terrain_dem",
        )

    def _contour_vertices_to_points(self, contour_layer, elevation_field):
        target_crs = contour_layer.crs() if contour_layer.crs().isValid() else self._fallback_crs()
        point_layer = QgsVectorLayer(f"Point?crs={target_crs.authid()}", f"{contour_layer.name()}_vertices", "memory")
        provider = point_layer.dataProvider()
        provider.addAttributes([QgsField(elevation_field, QVariant.Double)])
        point_layer.updateFields()

        features = []
        for source_feature in contour_layer.getFeatures():
            raw_value = source_feature[elevation_field]
            if raw_value in (None, ""):
                continue

            geometry = source_feature.geometry()
            if not geometry or geometry.isEmpty():
                continue

            elevation = float(raw_value)
            for vertex in geometry.vertices():
                point_feature = QgsFeature(point_layer.fields())
                point_feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(vertex)))
                point_feature[elevation_field] = elevation
                features.append(point_feature)

        if not features:
            raise ValueError("Contour layer did not produce any valid interpolation vertices")

        provider.addFeatures(features)
        point_layer.updateExtents()
        return point_layer

    def _write_interpolated_raster(self, point_layer, elevation_field, extent, cell_size, output_path):
        layer_data = QgsInterpolator.LayerData()
        source_points = getattr(QgsInterpolator, "SourcePoints", 0)

        if hasattr(layer_data, "source"):
            layer_data.source = point_layer
        if hasattr(layer_data, "vectorLayer"):
            layer_data.vectorLayer = point_layer
        if hasattr(layer_data, "interpolationAttribute"):
            layer_data.interpolationAttribute = point_layer.fields().indexFromName(elevation_field)
        if hasattr(layer_data, "attributeIndex"):
            layer_data.attributeIndex = point_layer.fields().indexFromName(elevation_field)
        if hasattr(layer_data, "sourceType"):
            layer_data.sourceType = source_points
        if hasattr(layer_data, "mInputType"):
            layer_data.mInputType = source_points
        if hasattr(layer_data, "zCoordInterpolation"):
            layer_data.zCoordInterpolation = False
        if hasattr(layer_data, "useZValue"):
            layer_data.useZValue = False

        try:
            interpolator = QgsTinInterpolator([layer_data], getattr(QgsTinInterpolator, "Linear", 0))
        except TypeError:
            interpolator = QgsTinInterpolator([layer_data])

        columns = max(int(math.ceil(extent.width() / float(cell_size))), 1)
        rows = max(int(math.ceil(extent.height() / float(cell_size))), 1)

        writer = None
        for args in (
            (interpolator, output_path, extent, columns, rows),
            (interpolator, output_path, extent, columns, rows, float(cell_size), float(cell_size)),
        ):
            try:
                writer = QgsGridFileWriter(*args)
                break
            except TypeError:
                continue
        if writer is None:
            raise RuntimeError("Failed to initialize grid writer for contour interpolation")

        result = writer.writeFile()
        if isinstance(result, tuple):
            result = result[0]
        if result not in (None, 0):
            raise RuntimeError(f"Contour interpolation failed with code {result}")

    def _create_hillshade_layer(self, surface_layer, vertical_exaggeration, map_session=None):
        algorithm_id = self.find_processing_algorithm(
            [
                "native:hillshade",
                "gdal:hillshade",
                "hillshade",
            ]
        )
        if not algorithm_id:
            raise RuntimeError("Hillshade algorithm is unavailable in this QGIS environment")

        params = {
            "INPUT": surface_layer,
            "BAND": 1,
            "Z_FACTOR": float(vertical_exaggeration),
            "SCALE": 1.0,
            "AZIMUTH": 315.0,
            "V_ANGLE": 45.0,
            "ALTITUDE": 45.0,
            "COMPUTE_EDGES": True,
            "OUTPUT": self.coerce_output_target("file", default_suffix=".tif"),
        }
        result = self.run_processing_with_supported_params(algorithm_id, params)
        hillshade_layer = None
        for value in result.values():
            hillshade_layer = self.load_result_layer(
                value,
                f"{surface_layer.name()}_hillshade",
                map_session=map_session,
                role="surface",
                owned=True,
                include_in_layout=True,
                source_tag="hillshade",
            )
            if hillshade_layer:
                break

        if not hillshade_layer:
            raise RuntimeError("Hillshade output could not be loaded")

        self._set_layer_opacity(hillshade_layer, 0.38)
        return hillshade_layer

    def _apply_terrain_color_ramp(self, raster_layer, color_ramp="Terrain"):
        provider = raster_layer.dataProvider()
        try:
            stats = provider.bandStatistics(1, QgsRasterBandStats.All)
        except TypeError:
            stats = provider.bandStatistics(1)
        min_value = float(getattr(stats, "minimumValue", 0.0))
        max_value = float(getattr(stats, "maximumValue", 0.0))
        if max_value <= min_value:
            return

        style = QgsStyle.defaultStyle()
        ramp = style.colorRamp(color_ramp) if style else None
        if not ramp and style:
            ramp = style.colorRamp("Terrain") or style.colorRamp("Spectral")
        if not ramp:
            return

        items = [
            QgsColorRampShader.ColorRampItem(min_value, ramp.color1(), f"{min_value:.2f}"),
        ]
        if hasattr(ramp, "stops"):
            for stop in ramp.stops() or []:
                value = min_value + (max_value - min_value) * float(stop.offset)
                items.append(QgsColorRampShader.ColorRampItem(value, stop.color, f"{value:.2f}"))
        items.append(QgsColorRampShader.ColorRampItem(max_value, ramp.color2(), f"{max_value:.2f}"))

        color_shader = QgsColorRampShader()
        color_shader.setColorRampType(QgsColorRampShader.Interpolated)
        color_shader.setColorRampItemList(items)

        shader = QgsRasterShader()
        shader.setRasterShaderFunction(color_shader)
        renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
        raster_layer.setRenderer(renderer)
        self.refresh_layer(raster_layer)

    def _set_layer_opacity(self, layer, opacity):
        renderer = getattr(layer, "renderer", lambda: None)()
        if renderer and hasattr(renderer, "setOpacity"):
            renderer.setOpacity(float(opacity))
            self.refresh_layer(layer)
            return
        if hasattr(layer, "setOpacity"):
            layer.setOpacity(float(opacity))
            self.refresh_layer(layer)
