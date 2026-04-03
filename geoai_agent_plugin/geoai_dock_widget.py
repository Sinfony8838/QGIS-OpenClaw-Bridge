# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsVectorLayer, QgsWkbTypes

from .geoai_socket_server import GeoaiSocketServer
from .profile_line_map_tool import ProfileLineMapTool
from .services.terrain_service import DEFAULT_PROFILE_LINE_LAYER_NAME


class GeoaiDockWidget(QDockWidget):
    closed = pyqtSignal()

    def __init__(self, iface):
        super().__init__("GeoAI Agent Console")
        self.iface = iface
        self.server_thread = None
        self.profile_map_tool = None
        self.previous_map_tool = None
        self.setup_ui()

    def setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        service_frame = QFrame()
        service_frame.setFrameShape(QFrame.StyledPanel)
        service_layout = QVBoxLayout()
        service_frame.setLayout(service_layout)

        service_layout.addWidget(QLabel("Socket bridge port:"))
        self.port_label = QLabel("<b>5555</b>")
        service_layout.addWidget(self.port_label)

        service_buttons = QHBoxLayout()
        self.start_button = QPushButton("Start Server")
        self.start_button.clicked.connect(self.start_server)
        service_buttons.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Server")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        service_buttons.addWidget(self.stop_button)
        service_layout.addLayout(service_buttons)

        self.status_label = QLabel("Status: stopped")
        service_layout.addWidget(self.status_label)
        layout.addWidget(service_frame)

        terrain_frame = QFrame()
        terrain_frame.setFrameShape(QFrame.StyledPanel)
        terrain_layout = QVBoxLayout()
        terrain_frame.setLayout(terrain_layout)

        terrain_layout.addWidget(QLabel("Terrain / 3D tools use the current active layer as terrain input."))
        self.terrain_hint = QLabel("Active terrain layer: none | Profile line: missing")
        self.terrain_hint.setWordWrap(True)
        terrain_layout.addWidget(self.terrain_hint)

        line_buttons = QHBoxLayout()
        self.draw_profile_button = QPushButton("Draw Profile Line")
        self.draw_profile_button.clicked.connect(self.begin_profile_line_drawing)
        line_buttons.addWidget(self.draw_profile_button)

        self.clear_profile_button = QPushButton("Clear Profile Line")
        self.clear_profile_button.clicked.connect(self.clear_profile_line)
        line_buttons.addWidget(self.clear_profile_button)
        terrain_layout.addLayout(line_buttons)

        action_buttons = QHBoxLayout()
        self.generate_profile_button = QPushButton("Generate Profile")
        self.generate_profile_button.clicked.connect(self.generate_profile_from_active_layer)
        action_buttons.addWidget(self.generate_profile_button)

        self.generate_terrain_button = QPushButton("Generate 3D Terrain")
        self.generate_terrain_button.clicked.connect(self.generate_terrain_model_from_active_layer)
        action_buttons.addWidget(self.generate_terrain_button)
        terrain_layout.addLayout(action_buttons)
        layout.addWidget(terrain_frame)

        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout()
        preview_frame.setLayout(preview_layout)

        self.preview_title = QLabel("Preview: none")
        preview_layout.addWidget(self.preview_title)

        self.preview_image = QLabel("Waiting for chart or terrain output")
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setMinimumHeight(180)
        self.preview_image.setWordWrap(True)
        preview_layout.addWidget(self.preview_image)

        self.preview_summary = QLabel("Preview summary will appear here")
        self.preview_summary.setWordWrap(True)
        preview_layout.addWidget(self.preview_summary)
        layout.addWidget(preview_frame)

        result_frame = QFrame()
        result_frame.setFrameShape(QFrame.StyledPanel)
        result_layout = QVBoxLayout()
        result_frame.setLayout(result_layout)

        self.execution_title = QLabel("Execution: none")
        result_layout.addWidget(self.execution_title)

        self.execution_summary = QLabel("Latest execution summary will appear here")
        self.execution_summary.setWordWrap(True)
        result_layout.addWidget(self.execution_summary)

        self.artifact_list = QListWidget()
        result_layout.addWidget(self.artifact_list)
        layout.addWidget(result_frame)

        self.setWidget(widget)
        self.refresh_terrain_hint()

    def start_server(self):
        if self.server_thread:
            return True

        port = 5555
        self.server_thread = GeoaiSocketServer(
            port=port,
            iface=self.iface,
            chart_preview_callback=self.update_chart_preview,
            execution_summary_callback=self.update_execution_summary,
        )

        if self.server_thread.start():
            self.status_label.setText(f"Status: running (port: {port})")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.show_message("GeoAI socket server started.")
            self.refresh_terrain_hint()
            return True

        self.status_label.setText("Status: failed to start")
        self.server_thread = None
        self.show_message("GeoAI socket server failed to start.", level=Qgis.Warning)
        return False

    def stop_server(self):
        self.restore_previous_map_tool()
        if self.server_thread:
            self.server_thread.stop()
            self.server_thread = None

        self.clear_chart_preview()
        self.clear_execution_summary()
        self.status_label.setText("Status: stopped")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.refresh_terrain_hint()

    def update_chart_preview(self, image_path=None, title="", summary=None):
        self.preview_title.setText(f"Preview: {title or 'untitled'}")

        if image_path:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self.preview_image.setPixmap(
                    pixmap.scaled(
                        320,
                        180,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                self.preview_image.setText("")
            else:
                self.preview_image.setPixmap(QPixmap())
                self.preview_image.setText(image_path)
        else:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("No preview image available for this output")

        if isinstance(summary, dict):
            detail_lines = summary.get("detail_lines", [])
            if detail_lines:
                self.preview_summary.setText("\n".join(str(item) for item in detail_lines))
            else:
                chart_type = summary.get("chart_type", "unknown")
                point_count = summary.get("point_count", 0)
                self.preview_summary.setText(f"Type: {chart_type} | Points: {point_count}")
        else:
            self.preview_summary.setText("Preview summary will appear here")

    def clear_chart_preview(self):
        self.preview_title.setText("Preview: none")
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("Waiting for chart or terrain output")
        self.preview_summary.setText("Preview summary will appear here")

    def update_execution_summary(self, payload):
        title = payload.get("title", "Untitled")
        summary_lines = payload.get("summary_lines", [])
        artifacts = payload.get("artifacts", {})

        self.execution_title.setText(f"Execution: {title}")
        self.execution_summary.setText("\n".join(summary_lines) if summary_lines else "Latest execution summary will appear here")

        self.artifact_list.clear()
        for key, value in artifacts.items():
            self.artifact_list.addItem(f"{key}: {value}")

    def clear_execution_summary(self):
        self.execution_title.setText("Execution: none")
        self.execution_summary.setText("Latest execution summary will appear here")
        self.artifact_list.clear()

    def begin_profile_line_drawing(self):
        if not self.start_server():
            return

        if self.profile_map_tool is None:
            self.profile_map_tool = ProfileLineMapTool(self.iface.mapCanvas())
            self.profile_map_tool.line_finished.connect(self.handle_profile_line_finished)
            self.profile_map_tool.status_message.connect(self.handle_profile_tool_message)

        self.previous_map_tool = self.iface.mapCanvas().mapTool()
        self.iface.mapCanvas().setMapTool(self.profile_map_tool)
        self.handle_profile_tool_message("Profile line drawing enabled.")

    def handle_profile_line_finished(self, points):
        try:
            if not self.server_thread:
                raise RuntimeError("Terrain tools are unavailable because the socket server is not running")

            layer = self.server_thread.terrain_service.upsert_profile_line_layer(points)
            self.update_execution_summary(
                {
                    "title": "Profile Line Saved",
                    "summary_lines": [
                        f"Layer: {layer.name()}",
                        f"Vertices: {len(points)}",
                        "Use the current active terrain layer and click Generate Profile.",
                    ],
                    "artifacts": {
                        "profile_line_layer": self.server_thread.terrain_service.artifact_for_layer(layer),
                    },
                }
            )
            self.show_message(f"Saved profile line to layer '{layer.name()}'.")
        except Exception as exc:
            self.show_message(str(exc), level=Qgis.Warning)
            self.update_execution_summary(
                {
                    "title": "Profile Line Error",
                    "summary_lines": [str(exc)],
                    "artifacts": {},
                }
            )
        finally:
            self.restore_previous_map_tool()
            self.refresh_terrain_hint()

    def handle_profile_tool_message(self, message):
        self.show_message(message)
        self.refresh_terrain_hint(extra_message=message)

    def clear_profile_line(self):
        if not self.start_server():
            return

        removed = self.server_thread.terrain_service.clear_profile_line_layer()
        if self.profile_map_tool:
            self.profile_map_tool.reset()
        self.restore_previous_map_tool()

        message = "Profile line layer cleared." if removed else "No profile line layer was found."
        self.show_message(message)
        self.update_execution_summary(
            {
                "title": "Profile Line",
                "summary_lines": [message],
                "artifacts": {},
            }
        )
        self.refresh_terrain_hint()

    def generate_profile_from_active_layer(self):
        if not self.start_server():
            return

        try:
            layer, params = self.active_terrain_params()
            response = self.server_thread.terrain_service.create_terrain_profile(
                profile_layer_name=DEFAULT_PROFILE_LINE_LAYER_NAME,
                title=f"{layer.name()} Terrain Profile",
                **params,
            )
            self.handle_service_response(response, "Terrain Profile")
        except Exception as exc:
            self.handle_service_response({"status": "error", "message": str(exc)}, "Terrain Profile")

    def generate_terrain_model_from_active_layer(self):
        if not self.start_server():
            return

        try:
            layer, params = self.active_terrain_params()
            response = self.server_thread.terrain_service.create_terrain_model(
                title=f"{layer.name()} Simplified Terrain Model",
                **params,
            )
            self.handle_service_response(response, "Terrain Model")
        except Exception as exc:
            self.handle_service_response({"status": "error", "message": str(exc)}, "Terrain Model")

    def active_terrain_params(self):
        layer = self.iface.activeLayer()
        if not layer:
            raise ValueError("Select a terrain layer in QGIS before running Terrain / 3D tools.")
        if layer.name() == DEFAULT_PROFILE_LINE_LAYER_NAME:
            raise ValueError("The active layer is the profile line. Select a raster DEM or contour layer instead.")

        params = {
            "terrain_layer_id": layer.id(),
            "terrain_type": "auto",
        }
        if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.LineGeometry:
            elevation_field = self.server_thread.terrain_service.detect_elevation_field(layer)
            if elevation_field:
                params["elevation_field"] = elevation_field
        return layer, params

    def handle_service_response(self, response, title):
        if response.get("status") == "success":
            self.refresh_terrain_hint()
            return

        message = response.get("message", f"{title} failed")
        warnings = response.get("warnings", [])
        summary_lines = [message]
        if warnings:
            summary_lines.extend(str(item) for item in warnings)
        self.update_execution_summary(
            {
                "title": f"{title} Error",
                "summary_lines": summary_lines,
                "artifacts": response.get("artifacts", {}),
            }
        )
        self.show_message(message, level=Qgis.Warning)
        self.refresh_terrain_hint()

    def restore_previous_map_tool(self):
        canvas = self.iface.mapCanvas()
        if self.profile_map_tool and canvas.mapTool() == self.profile_map_tool:
            try:
                canvas.unsetMapTool(self.profile_map_tool)
            except Exception:
                pass
        if self.previous_map_tool and self.previous_map_tool != self.profile_map_tool:
            try:
                canvas.setMapTool(self.previous_map_tool)
            except Exception:
                pass
        self.previous_map_tool = None

    def refresh_terrain_hint(self, extra_message=None):
        active_layer = self.iface.activeLayer()
        active_text = active_layer.name() if active_layer else "none"
        profile_layer = self.server_thread.terrain_service.resolve_layer(layer_name=DEFAULT_PROFILE_LINE_LAYER_NAME) if self.server_thread else None
        profile_text = profile_layer.name() if profile_layer else "missing"
        message = f"Active terrain layer: {active_text} | Profile line: {profile_text}"
        if extra_message:
            message = f"{message}\n{extra_message}"
        self.terrain_hint.setText(message)

    def show_message(self, text, level=Qgis.Info):
        if not self.iface:
            return
        self.iface.messageBar().pushMessage("GeoAI", str(text), level=level, duration=4)

    def closeEvent(self, event):
        self.restore_previous_map_tool()
        self.stop_server()
        self.closed.emit()
        super().closeEvent(event)
