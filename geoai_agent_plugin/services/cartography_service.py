import os
import tempfile
from collections import OrderedDict

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFillSymbol,
    QgsField,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPrintLayout,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsStyle,
    QgsSymbol,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

from .base_service import BaseGeoAIService
from .service_utils import layout_frame_for_paper
from .session_utils import DEFAULT_CHART_SLOT, DEFAULT_LAYOUT_NAME


class CartographyService(BaseGeoAIService):
    def _resolve_label_placement(self, placement_name):
        qgis_label_placement = getattr(Qgis, "LabelPlacement", None)
        if qgis_label_placement and hasattr(qgis_label_placement, placement_name):
            return getattr(qgis_label_placement, placement_name)
        if hasattr(QgsPalLayerSettings, placement_name):
            return getattr(QgsPalLayerSettings, placement_name)
        raise AttributeError(f"Unsupported label placement: {placement_name}")

    def _apply_page_size(self, layout, paper_spec):
        if not hasattr(layout, "pageCollection"):
            return False

        collection = layout.pageCollection()
        page = None
        if hasattr(collection, "page"):
            page = collection.page(0)
        elif hasattr(collection, "pages"):
            pages = collection.pages()
            page = pages[0] if pages else None

        if page is None or not hasattr(page, "setPageSize"):
            return False

        page_size = QgsLayoutSize(paper_spec["width"], paper_spec["height"], QgsUnitTypes.LayoutMillimeters)
        try:
            page.setPageSize(page_size)
            return True
        except TypeError:
            pass
        except Exception:
            pass

        try:
            page.setPageSize(paper_spec["label"].split()[0])
            return True
        except Exception:
            return False

    def set_background_color(self, color="#ffffff"):
        if not self.iface:
            return self.error("QGIS interface is unavailable")
        self.iface.mapCanvas().setCanvasColor(QColor(color))
        self.iface.mapCanvas().refresh()
        return self.success("Canvas background updated", data={"color": color})

    def set_style(self, layer_id=None, layer_name=None, style_type="single", map_session=None, **properties):
        try:
            layer = self.require_layer(layer_id=layer_id, layer_name=layer_name)
            geom_type = layer.geometryType() if hasattr(layer, "geometryType") else None
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None

            if style_type != "single":
                return self.error("Complex thematic styling should use dedicated tools")

            style_dict = {key: str(value) for key, value in properties.items()}
            if geom_type == QgsWkbTypes.PointGeometry:
                symbol = QgsMarkerSymbol.createSimple(style_dict)
            elif geom_type == QgsWkbTypes.LineGeometry:
                symbol = QgsLineSymbol.createSimple(style_dict)
            elif geom_type == QgsWkbTypes.PolygonGeometry:
                symbol = QgsFillSymbol.createSimple(style_dict)
            else:
                return self.error("Unsupported geometry type for styling")

            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            self.refresh_layer(layer)
            if session:
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
            return self.success(
                "Single symbol style applied",
                artifacts=dict({"layer": self.artifact_for_layer(layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def auto_layout(
        self,
        title="GeoAI Output",
        paper_size="A4",
        layout_name=DEFAULT_LAYOUT_NAME,
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
                snapshot_visible_layers=not map_session,
            )
            actual_layout_name = session["layout_name"]
            frame = layout_frame_for_paper(paper_size)
            manager = self.project.layoutManager()
            existing = manager.layoutByName(actual_layout_name)
            if existing:
                manager.removeLayout(existing)

            layout = QgsPrintLayout(self.project)
            layout.initializeDefaults()
            self._apply_page_size(layout, frame["paper"])
            layout.setName(actual_layout_name)
            if hasattr(layout, "setCustomProperty"):
                layout.setCustomProperty("geoai/map_session", session["map_session"])
            manager.addLayout(layout)

            map_item = QgsLayoutItemMap(layout)
            if hasattr(map_item, "setId"):
                map_item.setId("geoai_map")
            layout.addLayoutItem(map_item)
            map_item.attemptMove(QgsLayoutPoint(frame["map"]["x"], frame["map"]["y"], QgsUnitTypes.LayoutMillimeters))
            map_item.attemptResize(QgsLayoutSize(frame["map"]["width"], frame["map"]["height"], QgsUnitTypes.LayoutMillimeters))
            self.apply_session_to_map_item(map_item, session)

            title_item = QgsLayoutItemLabel(layout)
            if hasattr(title_item, "setId"):
                title_item.setId("geoai_title")
            title_item.setText(title)
            title_item.setFont(QFont("Arial", 22))
            layout.addLayoutItem(title_item)
            title_item.attemptMove(QgsLayoutPoint(frame["title"]["x"], frame["title"]["y"], QgsUnitTypes.LayoutMillimeters))

            legend = QgsLayoutItemLegend(layout)
            if hasattr(legend, "setId"):
                legend.setId("geoai_legend")
            legend.setTitle("Legend")
            legend.setLinkedMap(map_item)
            legend.setAutoUpdateModel(False)
            try:
                legend.model().setRootGroup(self.clone_session_layer_tree(session))
            except Exception:
                pass
            layout.addLayoutItem(legend)
            legend.attemptMove(QgsLayoutPoint(frame["legend"]["x"], frame["legend"]["y"], QgsUnitTypes.LayoutMillimeters))
            legend.attemptResize(QgsLayoutSize(frame["legend"]["width"], frame["legend"]["height"], QgsUnitTypes.LayoutMillimeters))

            artifacts = self.session_artifacts(session)
            return self.success(
                "Layout created",
                data={
                    "paper_size": frame["paper"]["label"],
                    "page_width_mm": frame["paper"]["width"],
                    "page_height_mm": frame["paper"]["height"],
                    "extent_mode": session.get("extent_mode"),
                },
                artifacts=artifacts,
                layout_name=actual_layout_name,
                map_session=session["map_session"],
                layer_group=session.get("group_name"),
            )
        except Exception as exc:
            return self.error(str(exc))

    def export_map(self, file_path, layout_name=DEFAULT_LAYOUT_NAME, map_session=None):
        try:
            session = self.map_sessions.get(map_session) if map_session else self.find_session_by_layout_name(layout_name)
            actual_layout_name = session["layout_name"] if session else layout_name
            layout = self.get_layout(layout_name=actual_layout_name, map_session=map_session)
            if not layout:
                return self.error("Layout not found")

            exporter = QgsLayoutExporter(layout)
            if file_path.lower().endswith(".pdf"):
                result = exporter.exportToPdf(file_path, QgsLayoutExporter.PdfExportSettings())
            else:
                result = exporter.exportToImage(file_path, QgsLayoutExporter.ImageExportSettings())

            if result != QgsLayoutExporter.Success:
                return self.error("Layout export failed", data={"code": result})

            artifacts = {"layout": self.artifact_for_layout(actual_layout_name), "export_path": file_path}
            artifacts.update(self.session_artifacts(session))
            return self.success(
                "Layout exported",
                artifacts=artifacts,
                path=file_path,
                layout_name=actual_layout_name,
                map_session=session["map_session"] if session else None,
            )
        except Exception as exc:
            return self.error(str(exc))

    def apply_graduated_renderer(
        self,
        layer_id=None,
        layer_name=None,
        field=None,
        mode="jenks",
        classes=5,
        color_ramp="Viridis",
        precision=2,
        label_format="{lower} - {upper}",
        map_session=None,
    ):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            self.require_field(layer, field)
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None

            mode_name = str(mode).lower()
            mode_map = {
                "jenks": QgsGraduatedSymbolRenderer.Jenks,
                "quantile": QgsGraduatedSymbolRenderer.Quantile,
                "equalinterval": QgsGraduatedSymbolRenderer.EqualInterval,
                "pretty": QgsGraduatedSymbolRenderer.Pretty,
            }
            mode_value = mode_map.get(mode_name, QgsGraduatedSymbolRenderer.Jenks)

            base_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            style = QgsStyle.defaultStyle()
            ramp = style.colorRamp(color_ramp) if style else None
            if not ramp and style:
                ramp = style.colorRamp("Viridis")

            renderer = QgsGraduatedSymbolRenderer.createRenderer(
                layer,
                field,
                int(classes),
                mode_value,
                base_symbol,
                ramp,
            )

            ranges = []
            for index, range_item in enumerate(renderer.ranges()):
                lower = round(range_item.lowerValue(), int(precision))
                upper = round(range_item.upperValue(), int(precision))
                label = label_format.format(lower=lower, upper=upper, index=index + 1)
                renderer.updateRangeLabel(index, label)
                ranges.append({"lower": lower, "upper": upper, "label": label})

            layer.setRenderer(renderer)
            self.refresh_layer(layer)
            if session:
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
            return self.success(
                "Graduated renderer applied",
                data={"field": field, "mode": mode_name, "classes": len(ranges), "ranges": ranges},
                artifacts=dict({"layer": self.artifact_for_layer(layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def generate_hu_huanyong_line(
        self,
        line_name="Hu Huanyong Line",
        start_point=None,
        end_point=None,
        crs="EPSG:4326",
        add_label=True,
        map_session=None,
    ):
        try:
            session = self.ensure_map_session(map_session=map_session, title=line_name, create_new=not map_session) if map_session else None
            layer = QgsVectorLayer(f"LineString?crs={crs}", line_name, "memory")
            provider = layer.dataProvider()
            provider.addAttributes([QgsField("name", QVariant.String)])
            layer.updateFields()

            default_start = start_point or {"x": 127.5, "y": 50.25}
            default_end = end_point or {"x": 98.5, "y": 25.0}
            start = self.resolve_point(default_start, crs)
            end = self.resolve_point(default_end, crs)

            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPolylineXY([start, end]))
            feature["name"] = "胡焕庸线"
            provider.addFeature(feature)
            layer.updateExtents()

            symbol = QgsLineSymbol.createSimple({"color": "#2d3142", "width": "1.2", "line_style": "dash"})
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            self.add_map_layer(layer)
            self.refresh_layer(layer)
            if session:
                self.register_layer_with_session(session, layer, role="comparison_line", owned=True, include_in_layout=True, source_tag="hu_huanyong")

            if add_label:
                self.set_layer_labels(layer_id=layer.id(), field="name", color="#2d3142", size=11, map_session=map_session)

            return self.success(
                "Hu Huanyong line generated",
                artifacts=dict({"layer": self.artifact_for_layer(layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def customize_layout_legend(
        self,
        layout_name=DEFAULT_LAYOUT_NAME,
        title="Legend",
        layer_order=None,
        hidden_layers=None,
        patch_size=None,
        fonts=None,
        auto_update=False,
        map_session=None,
    ):
        try:
            session = self.map_sessions.get(map_session) if map_session else self.find_session_by_layout_name(layout_name)
            actual_layout_name = session["layout_name"] if session else layout_name
            layout = self.get_layout(layout_name=actual_layout_name, map_session=map_session)
            if not layout:
                return self.error("Layout not found")

            if isinstance(layer_order, str):
                layer_order = [layer_order]
            if isinstance(hidden_layers, str):
                hidden_layers = [hidden_layers]

            legend = self.find_layout_item(layout, QgsLayoutItemLegend)
            if not legend:
                legend = QgsLayoutItemLegend(layout)
                layout.addLayoutItem(legend)
                legend.attemptMove(QgsLayoutPoint(205, 20, QgsUnitTypes.LayoutMillimeters))

            map_item = self.find_layout_item(layout, QgsLayoutItemMap)
            if map_item:
                legend.setLinkedMap(map_item)
                if session:
                    self.apply_session_to_map_item(map_item, session)
            legend.setTitle(title)
            legend.setAutoUpdateModel(bool(auto_update))

            cloned_root = self.clone_session_layer_tree(session) if session else self.project.layerTreeRoot().clone()
            self.remove_hidden_layers(cloned_root, hidden_layers or [])
            self.reorder_layer_tree(cloned_root, layer_order or [])
            try:
                legend.model().setRootGroup(cloned_root)
            except Exception:
                pass

            if isinstance(patch_size, dict):
                if "width" in patch_size:
                    legend.setSymbolWidth(float(patch_size["width"]))
                if "height" in patch_size:
                    legend.setSymbolHeight(float(patch_size["height"]))

            if isinstance(fonts, dict):
                if "title" in fonts:
                    title_font = QFont(fonts["title"].get("family", "Arial"), int(fonts["title"].get("size", 12)))
                    legend.rstyle(QgsLegendStyle.Title).setFont(title_font)
                if "group" in fonts:
                    group_font = QFont(fonts["group"].get("family", "Arial"), int(fonts["group"].get("size", 10)))
                    legend.rstyle(QgsLegendStyle.Group).setFont(group_font)
                if "symbol" in fonts:
                    symbol_font = QFont(fonts["symbol"].get("family", "Arial"), int(fonts["symbol"].get("size", 9)))
                    legend.rstyle(QgsLegendStyle.SymbolLabel).setFont(symbol_font)

            legend.adjustBoxSize()
            return self.success(
                "Layout legend customized",
                data={"title": title},
                artifacts=dict({"layout": self.artifact_for_layout(actual_layout_name)}, **self.session_artifacts(session)),
                layout_name=actual_layout_name,
                map_session=session["map_session"] if session else None,
            )
        except Exception as exc:
            return self.error(str(exc))

    def set_layer_labels(
        self,
        layer_id=None,
        layer_name=None,
        field=None,
        expression=None,
        font="Arial",
        size=10,
        color="#1f2933",
        buffer_color="#ffffff",
        buffer_size=1.0,
        placement=None,
        scale_visibility=None,
        map_session=None,
    ):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            if not expression:
                self.require_field(layer, field)
            session = self.ensure_map_session(map_session=map_session, create_new=False) if map_session else None

            settings = QgsPalLayerSettings()
            settings.enabled = True
            settings.fieldName = expression or field
            settings.isExpression = bool(expression)

            text_format = QgsTextFormat()
            text_format.setFont(QFont(font, int(size)))
            text_format.setSize(float(size))
            text_format.setColor(QColor(color))

            buffer_settings = QgsTextBufferSettings()
            buffer_settings.setEnabled(True)
            buffer_settings.setColor(QColor(buffer_color))
            buffer_settings.setSize(float(buffer_size))
            text_format.setBuffer(buffer_settings)
            settings.setFormat(text_format)

            placement_key = (placement or "").lower()
            if layer.geometryType() == QgsWkbTypes.LineGeometry:
                settings.placement = self._resolve_label_placement("Curved")
            elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                settings.placement = self._resolve_label_placement("OverPoint")
            else:
                settings.placement = self._resolve_label_placement("OverPoint")

            if placement_key == "line":
                settings.placement = self._resolve_label_placement("Line")
            elif placement_key == "horizontal":
                settings.placement = self._resolve_label_placement("Horizontal")

            if isinstance(scale_visibility, (list, tuple)) and len(scale_visibility) == 2:
                settings.scaleVisibility = True
                settings.minimumScale = float(scale_visibility[0])
                settings.maximumScale = float(scale_visibility[1])

            layer.setLabelsEnabled(True)
            layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
            self.refresh_layer(layer)
            if session:
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
            return self.success(
                "Layer labels configured",
                artifacts=dict({"layer": self.artifact_for_layer(layer)}, **self.session_artifacts(session)),
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))

    def _build_chart_data(self, layer, chart_type, category_field, value_field, aggregation):
        if category_field:
            self.require_field(layer, category_field)
        if chart_type != "count" and value_field:
            self.require_field(layer, value_field)

        buckets = OrderedDict()
        for index, feature in enumerate(layer.getFeatures()):
            key = str(feature[category_field]) if category_field else str(index + 1)
            buckets.setdefault(key, [])
            if value_field:
                value = feature[value_field]
                if value not in (None, ""):
                    buckets[key].append(float(value))
            else:
                buckets[key].append(1.0)

        points = []
        aggregation_name = (aggregation or "sum").lower()
        for key, values in buckets.items():
            if aggregation_name == "count":
                agg_value = float(len(values))
            elif aggregation_name == "avg":
                agg_value = float(sum(values) / len(values)) if values else 0.0
            elif aggregation_name == "min":
                agg_value = float(min(values)) if values else 0.0
            elif aggregation_name == "max":
                agg_value = float(max(values)) if values else 0.0
            else:
                agg_value = float(sum(values))
            points.append({"label": key, "value": round(agg_value, 4)})
        return points

    def _render_chart(self, chart_type, title, data_points):
        try:
            import matplotlib

            matplotlib.use("Agg")
            from matplotlib import pyplot as plt
        except Exception as exc:
            raise RuntimeError(f"matplotlib is required for chart rendering: {exc}")

        labels = [item["label"] for item in data_points]
        values = [item["value"] for item in data_points]
        figure, axis = plt.subplots(figsize=(8, 5))
        axis.set_title(title)

        normalized_chart = (chart_type or "bar").lower()
        if normalized_chart == "pie":
            axis.pie(values, labels=labels, autopct="%1.1f%%")
        elif normalized_chart == "line":
            axis.plot(labels, values, marker="o", color="#2a9d8f")
            axis.set_ylabel("Value")
        else:
            axis.bar(labels, values, color="#457b9d")
            axis.set_ylabel("Value")
            axis.tick_params(axis="x", rotation=30)

        figure.tight_layout()
        fd, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        figure.savefig(image_path, dpi=150)
        plt.close(figure)
        return image_path

    def embed_chart(
        self,
        layer_id=None,
        layer_name=None,
        chart_type="bar",
        category_field=None,
        value_field=None,
        aggregation="sum",
        title="GeoAI Chart",
        dock_preview=True,
        layout_embed=True,
        layout_name=DEFAULT_LAYOUT_NAME,
        position=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
        chart_slot=None,
    ):
        try:
            layer = self.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
            session = None
            if map_session or layout_embed:
                session = self.ensure_map_session(
                    map_session=map_session,
                    title=title,
                    layout_name=layout_name,
                    reference_layers=reference_layers,
                    extent_mode=extent_mode,
                    create_new=not map_session,
                )
                self.register_layer_with_session(session, layer, owned=False, include_in_layout=True)
            data_points = self._build_chart_data(layer, chart_type, category_field, value_field, aggregation)
            if not data_points:
                return self.error("Chart data is empty")

            image_path = self._render_chart(chart_type, title, data_points)
            summary = self.chart_summary(chart_type, data_points, image_path)

            if dock_preview:
                self.emit_chart_preview(image_path, title, summary)

            artifacts = {
                "layer": self.artifact_for_layer(layer),
                "chart_image": image_path,
            }
            artifacts.update(self.session_artifacts(session))

            if layout_embed:
                actual_layout_name = session["layout_name"]
                slot_name = str(chart_slot or DEFAULT_CHART_SLOT)

                def _embed_chart():
                    layout = self.get_layout(
                        layout_name=actual_layout_name,
                        create_if_missing=True,
                        title=title,
                        map_session=session["map_session"],
                    )
                    picture_id = f"geoai_chart_{slot_name}"
                    picture = self.find_layout_item_by_id(layout, picture_id)
                    if picture is None:
                        picture = QgsLayoutItemPicture(layout)
                        if hasattr(picture, "setId"):
                            picture.setId(picture_id)
                        layout.addLayoutItem(picture)
                    picture.setPicturePath(image_path)
                    chart_position = self.resolve_chart_slot_position(session, chart_slot=slot_name, base_position=position)
                    picture.attemptMove(QgsLayoutPoint(chart_position["x"], chart_position["y"], QgsUnitTypes.LayoutMillimeters))
                    picture.attemptResize(QgsLayoutSize(chart_position["width"], chart_position["height"], QgsUnitTypes.LayoutMillimeters))

                self.call_in_main_thread(_embed_chart)
                artifacts["layout"] = self.artifact_for_layout(
                    actual_layout_name,
                    map_session=session["map_session"],
                    layer_group=session.get("group_name"),
                )

            return self.success(
                "Chart generated",
                data=summary,
                artifacts=artifacts,
                **self.artifact_for_layer(layer),
            )
        except Exception as exc:
            return self.error(str(exc))
