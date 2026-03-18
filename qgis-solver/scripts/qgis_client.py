import json
import socket
import traceback
from qgis.PyQt.QtCore import QObject, QTimer
from qgis.PyQt.QtGui import QFont
from qgis.core import (
    QgsProject, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsWkbTypes, QgsSingleSymbolRenderer, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsApplication, QgsPrintLayout, QgsLayoutItemMap, 
    QgsLayoutItemLabel, QgsLayoutExporter,
    QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes,
    QgsVectorLayer, QgsRasterLayer
)

try:
    import processing
except ImportError:
    processing = None

class GeoaiSocketServer(QObject):
    def __init__(self, port=5555, iface=None):
        super().__init__()
        self.port, self.iface = port, iface
        self.running = False
        self.socket, self.timer = None, None
        self.clients, self.buffers = [], {}
        
        # 注册映射关系
        self.handlers = {
            "get_layers": self.get_layers,
            "set_style": self.set_style,
            "set_background_color": self.set_background_color,  
            "run_algorithm": self.run_algorithm,     
            "fly_to": self.fly_to,
            "zoom_to_layer": self.zoom_to_layer,
            "update_banner": self.update_banner,                    
            "auto_layout": self.auto_layout,         
            "export_map": self.export_map,           
            "get_algorithm_help": self.get_algorithm_help,
            "add_layer_from_path": self.add_layer_from_path
        }

    def start(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setblocking(False)
            self.socket.bind(('127.0.0.1', self.port))
            self.socket.listen(5)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.process_connections)
            self.timer.start(100)
            self.running = True
            return True
        except: return False

    def run_algorithm(self, algorithm_id, params, load_result=True):
        """执行算法并即时渲染内存结果"""
        if not processing: return {"status": "error", "message": "Processing模块未加载"}
        try:
            # 1. 自动转换：图层名转对象
            fixed_params = {}
            for k, v in params.items():
                if isinstance(v, str):
                    layers = QgsProject.instance().mapLayersByName(v)
                    fixed_params[k] = layers[0] if layers else v
                else:
                    fixed_params[k] = v

            # 2. 强制内存输出：如果不指定路径，则直接蹦出内存图层
            if "OUTPUT" not in fixed_params:
                fixed_params["OUTPUT"] = "memory:"

            result = processing.run(algorithm_id, fixed_params)

            # 3. 自动加载到地图
            if load_result and 'OUTPUT' in result:
                out = result['OUTPUT']
                # 如果是路径字符串则创建图层，如果是对象直接使用
                new_layer = out if not isinstance(out, str) else QgsVectorLayer(out, f"Result_{algorithm_id.split(':')[-1]}", "ogr")
                
                if new_layer and new_layer.isValid():
                    QgsProject.instance().addMapLayer(new_layer)
                    return {"status": "success", "layer_id": new_layer.id(), "message": "分析完成，结果已展示"}
            
            return {"status": "success", "result": "执行成功（未加载结果）"}
        except Exception as e:
            return {"status": "error", "message": f"算法报错: {str(e)}"}

    def add_layer_from_path(self, file_path, layer_name="新图层"):
        """手动加载本地文件到项目"""
        if file_path.lower().endswith(('.shp', '.geojson', '.gpkg', '.kml')):
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
        else:
            layer = QgsRasterLayer(file_path, layer_name)

        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {"status": "success", "layer_id": layer.id()}
        return {"status": "error", "message": "无效的文件路径或格式"}

    def zoom_to_layer(self, layer_id=None, layer_name=None):
        """精准缩放：含 CRS 转换与 10% 留白"""
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if not layer and layer_name:
            layers = QgsProject.instance().mapLayersByName(layer_name)
            layer = layers[0] if layers else None
        
        if not layer: return {"status": "error", "message": "图层未找到"}

        canvas = self.iface.mapCanvas()
        extent = layer.extent()
        layer_crs = layer.crs()
        canvas_crs = canvas.mapSettings().destinationCrs()

        # 处理坐标转换
        if layer_crs != canvas_crs:
            transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)

        if not extent.isEmpty():
            extent.scale(1.1)
            canvas.setExtent(extent) # 修正为 setExtent
            canvas.refresh()
            return {"status": "success"}
        return {"status": "error", "message": "图层范围无效"}

    # --- 以下为通用基础逻辑，已整合修正 ---
 
    def set_background_color(self, color="#ffffff"):
        return self.send_command("set_background_color", {"color": color})

    def set_style(self, layer_id=None, layer_name=None, style_type='single', **properties):
            """
            全能型样式设置函数：支持单符号 (single) 与 分类 (categorized) 渲染。
            支持点、线、面图层自动识别，并提供默认符号兜底。
            """
            from qgis.core import (
                QgsCategorizedSymbolRenderer, QgsRendererCategory, 
                QgsSymbol, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol
            )

            # 1. 获取目标图层
            layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
            if not layer and layer_name:
                layers = QgsProject.instance().mapLayersByName(layer_name)
                layer = layers[0] if layers else None
            
            if not layer: 
                return {"status": "error", "message": f"未找到图层: {layer_id or layer_name}"}

            geom_type = layer.geometryType()

            # --- 情况 A: 分类渲染 (Categorized) ---
            if style_type == 'categorized':
                column = properties.get('column', 'color')  # 分类依据字段，默认尝试 'color'
                mapping = properties.get('categories', {})  # 格式: {"属性值": "颜色十六进制"}
                
                categories = []
                for value, color_hex in mapping.items():
                    # 根据几何类型创建基础符号
                    if geom_type == QgsWkbTypes.PointGeometry:
                        symbol = QgsMarkerSymbol.createSimple({'color': color_hex, 'size': '4', 'outline_style': 'no'})
                    elif geom_type == QgsWkbTypes.LineGeometry:
                        symbol = QgsLineSymbol.createSimple({'color': color_hex, 'width': '1'})
                    else:
                        symbol = QgsFillSymbol.createSimple({'color': color_hex, 'outline_color': 'white'})
                    
                    # 创建分类条目
                    category = QgsRendererCategory(str(value), symbol, str(value))
                    categories.append(category)

                # 创建渲染器并设置默认符号（防止未定义属性的要素消失）
                renderer = QgsCategorizedSymbolRenderer(column, categories)
                
                # 创建一个通用的灰色默认符号
                if geom_type == QgsWkbTypes.PointGeometry:
                    default_s = QgsMarkerSymbol.createSimple({'color': '#cccccc', 'size': '2'})
                elif geom_type == QgsWkbTypes.LineGeometry:
                    default_s = QgsLineSymbol.createSimple({'color': '#cccccc', 'width': '0.5'})
                else:
                    default_s = QgsFillSymbol.createSimple({'color': '#cccccc'})
                
                renderer.setSourceSymbol(default_s)
                layer.setRenderer(renderer)

            # --- 情况 B: 单符号渲染 (Single) ---
            else:
                # 将传入的所有属性转为字符串供 Qgs 使用
                style_params = {k: str(v) for k, v in properties.items()}
                
                if geom_type == QgsWkbTypes.PointGeometry:
                    symbol = QgsMarkerSymbol.createSimple(style_params)
                elif geom_type == QgsWkbTypes.LineGeometry:
                    symbol = QgsLineSymbol.createSimple(style_params)
                else:
                    symbol = QgsFillSymbol.createSimple(style_params)
                
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))

            # 4. 刷新画布与图层面板
            layer.triggerRepaint()
            if self.iface:
                self.iface.layerTreeView().refreshLayerSymbology(layer.id())
                self.iface.mapCanvas().refresh()
                
            return {"status": "success", "mode": style_type, "layer": layer.name()}
    
    def set_layer_z_order(self, layer_id=None, layer_name=None, position="top"):
        """
        调整图层顺序
        position 可选值: "top", "bottom"
        """
        return self.send_command("set_layer_z_order", {
            "layer_id": layer_id,
            "layer_name": layer_name,
            "position": position
        })
    
    def process_connections(self):
        if not self.running: return
        try:
            client_socket, _ = self.socket.accept()
            client_socket.setblocking(False)
            self.clients.append(client_socket)
            self.buffers[client_socket] = b''
        except BlockingIOError: pass
        for client in list(self.clients):
            try:
                data = client.recv(4096)
                if data:
                    self.buffers[client] += data
                    self._process_buffer(client)
                else: self._disconnect_client(client)
            except: continue

    def _process_buffer(self, client):
        while True:
            buffer = self.buffers.get(client)
            if not buffer or len(buffer) < 4: break
            msg_len = int.from_bytes(buffer[:4], 'big')
            if len(buffer) < 4 + msg_len: break
            message_bytes = buffer[4:4 + msg_len]
            self.buffers[client] = buffer[4 + msg_len:]
            try:
                command_data = json.loads(message_bytes.decode('utf-8'))
                handler = self.handlers.get(command_data.get('tool_name'))
                if handler:
                    res = handler(**command_data.get('tool_params', {}))
                    response = res if isinstance(res, dict) else {"status": "success", "data": res}
                else: response = {"status": "error", "message": "未定义工具"}
            except Exception as e:
                response = {"status": "error", "message": str(e)}
            self._write_message(client, response)

    def _write_message(self, client, message_dict):
        try:
            b = json.dumps(message_dict).encode('utf-8')
            client.sendall(len(b).to_bytes(4, 'big') + b)
        except: self._disconnect_client(client)

    def auto_layout(self, title="GeoAI 生成地图", paper_size="A4"):
        project = QgsProject.instance()
        manager = project.layoutManager()
        layout_name = "GeoAI_Output"
        if manager.layoutByName(layout_name):
            manager.removeLayout(manager.layoutByName(layout_name))
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(layout_name)
        manager.addLayout(layout)
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(20, 20, 20, 20)
        layout.addLayoutItem(map_item)
        map_item.attemptMove(QgsLayoutPoint(5, 20, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(280, 170, QgsUnitTypes.LayoutMillimeters))
        map_item.zoomToExtent(self.iface.mapCanvas().extent())
        title_item = QgsLayoutItemLabel(layout)
        title_item.setText(title)
        title_item.setFont(QFont("Arial", 28))
        layout.addLayoutItem(title_item)
        title_item.attemptMove(QgsLayoutPoint(5, 5, QgsUnitTypes.LayoutMillimeters))
        return {"status": "success"}

    def export_map(self, file_path):
        layout = QgsProject.instance().layoutManager().layoutByName("GeoAI_Output")
        if not layout: return {"status": "error", "message": "无布局"}
        exporter = QgsLayoutExporter(layout)
        if file_path.lower().endswith(".pdf"):
            res = exporter.exportToPdf(file_path, QgsLayoutExporter.PdfExportSettings())
        else:
            res = exporter.exportToImage(file_path, QgsLayoutExporter.ImageExportSettings())
        return {"status": "success"} if res == QgsLayoutExporter.Success else {"status": "error"}

    def get_algorithm_help(self, algorithm_id):
        try:
            alg = QgsApplication.processingRegistry().algorithmById(algorithm_id)
            if not alg: return {"status": "not_found"}
            params = {p.name(): p.description() for p in alg.parameterDefinitions()}
            return {"status": "success", "params": params}
        except: return {"status": "error"}

    def _disconnect_client(self, client):
        if client in self.clients: self.clients.remove(client)
        if client in self.buffers: del self.buffers[client]
        client.close()

    def get_layers(self):
        return [{"name": l.name(), "id": l.id()} for l in QgsProject.instance().mapLayers().values()]

    def update_banner(self, text):
        self.iface.messageBar().pushMessage("GeoAI", text, duration=5)
        return {"status": "ok"}

    def fly_to(self, lat, lon, scale):
        canvas = self.iface.mapCanvas()
        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dest_crs = canvas.mapSettings().destinationCrs()
        point = QgsPointXY(float(lon), float(lat))
        if src_crs != dest_crs:
            transform = QgsCoordinateTransform(src_crs, dest_crs, QgsProject.instance())
            point = transform.transform(point)
        canvas.setCenter(point)
        canvas.zoomScale(float(scale))
        canvas.refresh()
        return {"status": "ok"}

    def stop(self):
        self.running = False
        if self.timer: self.timer.stop()
        if self.socket: self.socket.close()