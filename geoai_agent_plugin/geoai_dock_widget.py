# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import pyqtSignal, QObject
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
)

from .geoai_socket_server import GeoaiSocketServer

class GeoaiDockWidget(QDockWidget):
    closed = pyqtSignal()

    def __init__(self, iface):
        super().__init__("GeoAI Agent 控制台")
        self.iface = iface
        self.server_thread = None
        self.setup_ui()

    def setup_ui(self):
        widget = QWidget()
        layout = QVBoxLayout()
        widget.setLayout(layout)

        layout.addWidget(QLabel("服务器将运行在固定端口上:"))
        self.port_label = QLabel("<b>5555</b>")
        layout.addWidget(self.port_label)

        self.start_button = QPushButton("启动服务器")
        self.start_button.clicked.connect(self.start_server)
        layout.addWidget(self.start_button)

        self.stop_button = QPushButton("停止服务器")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.status_label = QLabel("状态: 已停止")
        layout.addWidget(self.status_label)

        self.setWidget(widget)

    def start_server(self):
        port = 5555
        # 实例化服务器
        self.server_thread = GeoaiSocketServer(port=port, iface=self.iface)

        if self.server_thread.start():
            self.status_label.setText(f"状态: 运行中 (端口: {port})")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        else:
            self.status_label.setText("状态: 启动失败，请查看日志")
            self.server_thread = None

    def stop_server(self):
        if self.server_thread:
            self.server_thread.stop()
            self.server_thread = None

        self.status_label.setText("状态: 已停止")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        print("UI 面板被关闭，正在停止服务器...")
        self.stop_server()
        self.closed.emit()
        super().closeEvent(event)