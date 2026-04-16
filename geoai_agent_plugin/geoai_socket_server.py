import json
import socket
import threading

from qgis.PyQt.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot

from .services import AnalysisService, CartographyService, ExperimentalService, LayerService, TeachingService, TerrainService
from .services.response_utils import error_response, success_response


class MainThreadExecutor(QObject):
    invocation_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.invocation_requested.connect(self._invoke, Qt.QueuedConnection)

    def call(self, func, *args, **kwargs):
        if QThread.currentThread() == self.thread():
            return func(*args, **kwargs)

        state = {
            "func": func,
            "args": args,
            "kwargs": kwargs,
            "event": threading.Event(),
            "result": None,
            "error": None,
        }
        self.invocation_requested.emit(state)
        state["event"].wait()
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    @pyqtSlot(object)
    def _invoke(self, state):
        try:
            state["result"] = state["func"](*state["args"], **state["kwargs"])
        except Exception as exc:
            state["error"] = exc
        finally:
            state["event"].set()


class GeoaiSocketServer(QObject):
    BACKGROUND_TOOLS = {
        "run_algorithm",
        "create_heatmap",
        "prepare_layer",
        "filter_layer",
        "join_attributes",
        "create_centroids",
        "create_connection_lines",
        "query_attributes",
        "embed_chart",
        "run_population_attraction_model",
        "generate_dynamic_hu_huanyong_line",
        "create_population_distribution_map",
        "create_population_density_map",
        "create_population_migration_map",
        "create_hu_line_comparison_map",
        "create_terrain_profile",
        "create_terrain_model",
    }

    def __init__(self, port=5555, iface=None, chart_preview_callback=None, execution_summary_callback=None):
        super().__init__()
        self.port = port
        self.iface = iface
        self.chart_preview_callback = chart_preview_callback
        self.execution_summary_callback = execution_summary_callback
        self.running = False
        self.socket = None
        self.server_thread = None
        self.map_sessions = {}
        self.map_session_counter = 0
        self.main_thread_executor = MainThreadExecutor(self)

        self.layer_service = LayerService(self)
        self.cartography_service = CartographyService(self)
        self.analysis_service = AnalysisService(self)
        self.teaching_service = TeachingService(self)
        self.experimental_service = ExperimentalService(self)
        self.terrain_service = TerrainService(self)

        self.handlers = {
            "ping": self._ping,
            "get_layers": self.layer_service.get_layers,
            "run_python_code": self.experimental_service.run_python_code,
            "set_style": self.cartography_service.set_style,
            "set_layer_style": self.cartography_service.set_style,
            "get_layer_style": self.cartography_service.get_layer_style,
            "set_background_color": self.cartography_service.set_background_color,
            "run_algorithm": self.analysis_service.run_algorithm,
            "fly_to": self.layer_service.fly_to,
            "zoom_to_layer": self.layer_service.zoom_to_layer,
            "set_layer_visibility": self.layer_service.set_layer_visibility,
            "set_active_layer": self.layer_service.set_active_layer,
            "update_banner": self._update_banner,
            "auto_layout": self.cartography_service.auto_layout,
            "export_map": self.cartography_service.export_map,
            "add_layer_from_path": self.layer_service.add_layer_from_path,
            "set_layer_z_order": self.layer_service.set_layer_z_order,
            "move_layer": self.layer_service.set_layer_z_order,
            "get_algorithm_help": self.analysis_service.get_algorithm_help,
            "apply_graduated_renderer": self.cartography_service.apply_graduated_renderer,
            "create_heatmap": self.analysis_service.create_heatmap,
            "create_flow_arrows": self.analysis_service.create_flow_arrows,
            "generate_hu_huanyong_line": self.cartography_service.generate_hu_huanyong_line,
            "generate_dynamic_hu_huanyong_line": self.teaching_service.generate_dynamic_hu_huanyong_line,
            "customize_layout_legend": self.cartography_service.customize_layout_legend,
            "set_layer_labels": self.cartography_service.set_layer_labels,
            "query_attributes": self._query_attributes,
            "embed_chart": self.cartography_service.embed_chart,
            "run_population_attraction_model": self.analysis_service.run_population_attraction_model,
            "style_population_attraction_result": self.analysis_service.style_population_attraction_result,
            "prepare_layer": self.layer_service.prepare_layer,
            "calculate_field": self.layer_service.calculate_field,
            "filter_layer": self.layer_service.filter_layer,
            "join_attributes": self.layer_service.join_attributes,
            "create_centroids": self.layer_service.create_centroids,
            "create_connection_lines": self.layer_service.create_connection_lines,
            "create_population_distribution_map": self.teaching_service.create_population_distribution_map,
            "create_population_density_map": self.teaching_service.create_population_density_map,
            "create_population_migration_map": self.teaching_service.create_population_migration_map,
            "create_hu_line_comparison_map": self.teaching_service.create_hu_line_comparison_map,
            "create_terrain_profile": self.terrain_service.create_terrain_profile,
            "create_terrain_model": self.terrain_service.create_terrain_model,
        }

    def start(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("127.0.0.1", self.port))
            self.socket.listen(5)
            self.socket.settimeout(1.0)
            self.running = True
            self.server_thread = threading.Thread(target=self._serve_loop, name="GeoAISocketServer", daemon=True)
            self.server_thread.start()
            self.layer_service.log("transport", f"Socket server started on 127.0.0.1:{self.port}")
            return True
        except Exception as exc:
            self.layer_service.push_banner(f"Socket server failed: {exc}")
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            self.running = False
            return False

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        self.server_thread = None
        self.layer_service.log("transport", "Socket server stopped")

    def call_in_main_thread(self, func, *args, **kwargs):
        return self.main_thread_executor.call(func, *args, **kwargs)

    def _serve_loop(self):
        while self.running:
            try:
                client_socket, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if self.running and not self._is_expected_disconnect(exc):
                    self.layer_service.log("transport", f"Socket accept failed: {exc}")
                break

            with client_socket:
                try:
                    client_socket.settimeout(10.0)
                    payload = self._read_message(client_socket)
                    response = self._dispatch_payload(payload)
                except Exception as exc:
                    if not self._is_expected_disconnect(exc):
                        self.layer_service.log("transport", f"Client request failed: {exc}")
                    response = error_response(str(exc))
                self._write_message(client_socket, response)

    def _recv_exact(self, client, size):
        buffer = b""
        while len(buffer) < size:
            try:
                chunk = client.recv(size - len(buffer))
            except socket.timeout:
                raise TimeoutError("Timed out while waiting for socket payload")
            if not chunk:
                raise ConnectionError("Socket closed before full request was received")
            buffer += chunk
        return buffer

    def _read_message(self, client):
        message_length = int.from_bytes(self._recv_exact(client, 4), "big")
        return json.loads(self._recv_exact(client, message_length).decode("utf-8"))

    def _dispatch_payload(self, payload):
        tool_name = payload.get("tool_name")
        tool_params = payload.get("tool_params", {})
        handler = self.handlers.get(tool_name)
        if not handler:
            return error_response(f"Unknown tool: {tool_name}")

        self.layer_service.log("transport", f"Executing tool: {tool_name}")
        try:
            if tool_name in self.BACKGROUND_TOOLS:
                result = handler(**tool_params)
            else:
                result = self.call_in_main_thread(handler, **tool_params)
            return result if isinstance(result, dict) else success_response(data=result)
        except Exception as exc:
            self.layer_service.log("transport", f"Unhandled tool error: {exc}")
            return error_response(str(exc))

    def _write_message(self, client, message_dict):
        try:
            payload = json.dumps(message_dict).encode("utf-8")
            client.sendall(len(payload).to_bytes(4, "big") + payload)
        except Exception as exc:
            if not self._is_expected_disconnect(exc):
                self.layer_service.log("transport", f"Client write failed: {exc}")

    def _is_expected_disconnect(self, exc):
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
            return True
        return isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10038, 10054)

    def _update_banner(self, text):
        self.layer_service.push_banner(text)
        return success_response("Banner updated", data={"text": text})

    def _ping(self):
        return success_response(
            "pong",
            data={
                "server": "GeoBot QGIS Plugin",
                "port": self.port,
            },
        )

    def _query_attributes(self, **kwargs):
        from .services.query_service import query_attributes

        return query_attributes(self.layer_service, **kwargs)
