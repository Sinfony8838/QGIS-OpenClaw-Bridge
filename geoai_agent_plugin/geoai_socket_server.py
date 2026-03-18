import json
import socket
import traceback
from qgis.PyQt.QtCore import QObject, QTimer, QTimeLine
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsProject, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsWkbTypes, QgsSingleSymbolRenderer, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsApplication,
    QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutItemScaleBar, QgsLayoutItemLegend, 
    QgsLayoutExporter,
    QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes
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
            "set_layer_style": self.set_style,
            "set_background_color": self.set_background_color, # 指向类中定义的正确方法
            "run_algorithm": self.run_algorithm,     
            "fly_to": self.fly_to,
            "zoom_to_layer": self.zoom_to_layer,
            "update_banner": self.update_banner,                    
            "auto_layout": self.auto_layout,         
            "export_map": self.export_map,  
            "add_layer_from_path": self.add_layer_from_path,
            "set_layer_z_order": self.set_layer_z_order,
            "move_layer": self.set_layer_z_order, # 增加别名方便 AI 调用         
            "get_algorithm_help": self.get_algorithm_help
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

    def set_background_color(self, color="#ffffff"):
        """
        正式的服务端背景设置逻辑：直接操作 QGIS 画布
        """
        try:
            from qgis.PyQt.QtGui import QColor
            canvas = self.iface.mapCanvas()
            # 核心操作：将颜色字符串转为 QColor 并应用
            canvas.setCanvasColor(QColor(color))
            canvas.refresh()
            return {"status": "success", "message": f"背景已更改为 {color}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}    

    def set_style(self, layer_id=None, layer_name=None, **properties):
        """核心修复：通用属性映射"""
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if not layer and layer_name:
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if layers: layer = layers[0]
        if not layer: return {"status": "error", "message": "图层未找到"}

        # 将所有属性转为字符串供Qgs使用
        style_dict = {k: str(v) for k, v in properties.items()}
        geom_type = layer.geometryType()

        if geom_type == QgsWkbTypes.PointGeometry:
            symbol = QgsMarkerSymbol.createSimple(style_dict)
        elif geom_type == QgsWkbTypes.LineGeometry:
            symbol = QgsLineSymbol.createSimple(style_dict)
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            symbol = QgsFillSymbol.createSimple(style_dict)
        
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()
        return {"status": "success"}

    def run_algorithm(self, algorithm_id, params, load_result=True):
            """执行算法并自动处理结果加载"""
            import processing
            from qgis.core import QgsVectorLayer, QgsRasterLayer
            
            # 1. 参数预处理：将图层名字符串转为实际图层对象
            fixed_params = {}
            for k, v in params.items():
                if isinstance(v, str):
                    layers = QgsProject.instance().mapLayersByName(v)
                    fixed_params[k] = layers[0] if layers else v
                else:
                    fixed_params[k] = v

            if "OUTPUT" not in fixed_params:
                fixed_params["OUTPUT"] = "memory:"

            # 2. 运行算法
            result = processing.run(algorithm_id, fixed_params)

            # 3. 自动加载结果到图层面板
            if load_result and 'OUTPUT' in result:
                out = result['OUTPUT']
                # 如果是内存图层对象直接添加，如果是路径字符串则先创建图层
                new_layer = out if not isinstance(out, str) else QgsVectorLayer(out, f"Result_{algorithm_id.split(':')[-1]}", "ogr")
                
                if new_layer and new_layer.isValid():
                    QgsProject.instance().addMapLayer(new_layer)
                    return {"status": "success", "layer_id": new_layer.id(), "message": "算法成功并已加载图层"}
            
            return {"status": "success", "result": "执行成功"}
    
    def add_layer_from_path(self, file_path, layer_name="New Layer"):
        """万能加载器：支持矢量和栅格"""
        from qgis.core import QgsVectorLayer, QgsRasterLayer
        if file_path.lower().endswith(('.shp', '.geojson', '.gpkg', '.kml', '.tab')):
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
        else:
            layer = QgsRasterLayer(file_path, layer_name)

        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {"status": "success", "layer_id": layer.id()}
        return {"status": "error", "message": "无法加载该文件，请检查路径或格式"}

    # --- 基础通讯逻辑 (已缩减，保持功能一致) ---
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
                        # 修正点：确保 res 为空时不会报错，并封装统一结构
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




    # --- 新增的生产工具函数 ---

    def auto_layout(self, title="GeoAI 生成地图", paper_size="A4"):
        """一键创建标准的地图布局"""
        project = QgsProject.instance()
        manager = project.layoutManager()
        
        # 移除同名布局防止冲突
        layout_name = "GeoAI_Output"
        if manager.layoutByName(layout_name):
            manager.removeLayout(manager.layoutByName(layout_name))
        
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(layout_name)
        manager.addLayout(layout)
        
        # 1. 添加地图项
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(20, 20, 20, 20) # 占位
        layout.addLayoutItem(map_item)
        map_item.attemptMove(QgsLayoutPoint(5, 20, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(280, 170, QgsUnitTypes.LayoutMillimeters))
        map_item.zoomToExtent(self.iface.mapCanvas().extent())
        
        # 2. 添加标题
        title_item = QgsLayoutItemLabel(layout)
        title_item.setText(title)
        title_item.setFont(QFont("Arial", 28))
        layout.addLayoutItem(title_item)
        title_item.attemptMove(QgsLayoutPoint(5, 5, QgsUnitTypes.LayoutMillimeters))
        
        return {"status": "success", "message": "布局已生成，请检查 QGIS 布局窗口"}

    def export_map(self, file_path):
            """一键导出地图文件 - 修复了类名拼写错误"""
            layout = QgsProject.instance().layoutManager().layoutByName("GeoAI_Output")
            if not layout: 
                return {"status": "error", "message": "请先调用 auto_layout"}
            
            # 修正类名：QgsLayoutExporter
            exporter = QgsLayoutExporter(layout)
            if file_path.lower().endswith(".pdf"):
                settings = QgsLayoutExporter.PdfExportSettings()
                res = exporter.exportToPdf(file_path, settings)
            else:
                settings = QgsLayoutExporter.ImageExportSettings()
                res = exporter.exportToImage(file_path, settings)    
        # 修正常量引用
            return {"status": "success", "path": file_path} if res == QgsLayoutExporter.Success else {"status": "error", "code": res}
    def get_algorithm_help(self, algorithm_id):
        """让 AI 查询算法参数说明"""
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
    
    def set_layer_z_order(self, layer_id=None, layer_name=None, position="top"):
        """
        调整图层层序
        :param position: "top" (最顶), "bottom" (最底)
        """
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        
        # 查找目标图层节点
        layer = project.mapLayer(layer_id) if layer_id else None
        if not layer and layer_name:
            layers = project.mapLayersByName(layer_name)
            layer = layers[0] if layers else None
        
        if not layer:
            return {"status": "error", "message": "图层未找到"}
            
        layer_node = root.findLayer(layer.id())
        if not layer_node:
            return {"status": "error", "message": "图层不在节点树中"}

        # 克隆节点并移动
        parent = layer_node.parent()
        clone = layer_node.clone()
        
        if position == "top":
            parent.insertChildNode(0, clone)
        elif position == "bottom":
            parent.insertChildNode(-1, clone)
            
        parent.removeChildNode(layer_node)
        return {"status": "success", "message": f"图层 {layer.name()} 已移至 {position}"}

    def fly_to(self, lat, lon, scale):
            """飞行逻辑：增加了 CRS 转换，确保经纬度跳转准确"""
            canvas = self.iface.mapCanvas()
            # 创建 WGS84 到当前画布坐标系的转换
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

    def zoom_to_layer(self, layer_id=None, layer_name=None):
            """
            精准缩放到指定图层：自动处理坐标转换 (CRS) 并增加 10% 视觉留白
            """
            # 1. 查找图层：优先 ID，次选名称
            layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
            if not layer and layer_name:
                layers = QgsProject.instance().mapLayersByName(layer_name)
                layer = layers[0] if layers else None
            
            if not layer:
                return {"status": "error", "message": "图层未找到"}

            # 2. 获取初始范围与坐标系
            canvas = self.iface.mapCanvas()
            extent = layer.extent()
            layer_crs = layer.crs()
            canvas_crs = canvas.mapSettings().destinationCrs()

            # 3. 核心修正：如果坐标系不一致，执行动态转换
            if layer_crs != canvas_crs:
                transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)

            # 4. 视觉优化：将缩放范围扩大 10%，避免图层紧贴边缘
            if not extent.isEmpty():
                extent.scale(1.1)
                canvas.setExtent(extent) # 使用正确的 setExtent 方法
                canvas.refresh()
                return {"status": "success", "message": f"已精准缩放至: {layer.name()}"}
            
            return {"status": "error", "message": "图层范围为空"}
    
    def stop(self):
        self.running = False
        if self.timer: self.timer.stop()
        if self.socket: self.socket.close()