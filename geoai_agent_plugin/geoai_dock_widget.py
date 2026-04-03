# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QListWidget,
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

        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout()
        preview_frame.setLayout(preview_layout)

        self.preview_title = QLabel("图表预览: 暂无")
        preview_layout.addWidget(self.preview_title)

        self.preview_image = QLabel("等待 embed_chart 调用")
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setMinimumHeight(180)
        self.preview_image.setWordWrap(True)
        preview_layout.addWidget(self.preview_image)

        self.preview_summary = QLabel("图表摘要将在这里显示")
        self.preview_summary.setWordWrap(True)
        preview_layout.addWidget(self.preview_summary)

        layout.addWidget(preview_frame)

        result_frame = QFrame()
        result_frame.setFrameShape(QFrame.StyledPanel)
        result_layout = QVBoxLayout()
        result_frame.setLayout(result_layout)

        self.execution_title = QLabel("模板执行: 暂无")
        result_layout.addWidget(self.execution_title)

        self.execution_summary = QLabel("最近一次模板执行摘要将在这里显示")
        self.execution_summary.setWordWrap(True)
        result_layout.addWidget(self.execution_summary)

        self.artifact_list = QListWidget()
        result_layout.addWidget(self.artifact_list)

        layout.addWidget(result_frame)

        self.setWidget(widget)

    def start_server(self):
        port = 5555
        # 实例化服务器
        self.server_thread = GeoaiSocketServer(
            port=port,
            iface=self.iface,
            chart_preview_callback=self.update_chart_preview,
            execution_summary_callback=self.update_execution_summary,
        )

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

        self.clear_chart_preview()
        self.clear_execution_summary()
        self.status_label.setText("状态: 已停止")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def update_chart_preview(self, image_path=None, title="", summary=None):
        self.preview_title.setText(f"图表预览: {title or '未命名图表'}")

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
            self.preview_image.setText("未提供图表图像")

        if isinstance(summary, dict):
            chart_type = summary.get("chart_type", "unknown")
            point_count = summary.get("point_count", 0)
            self.preview_summary.setText(f"类型: {chart_type} | 数据点: {point_count}")
        else:
            self.preview_summary.setText("图表摘要将在这里显示")

    def clear_chart_preview(self):
        self.preview_title.setText("图表预览: 暂无")
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("等待 embed_chart 调用")
        self.preview_summary.setText("图表摘要将在这里显示")

    def update_execution_summary(self, payload):
        title = payload.get("title", "未命名模板")
        summary_lines = payload.get("summary_lines", [])
        artifacts = payload.get("artifacts", {})

        self.execution_title.setText(f"模板执行: {title}")
        self.execution_summary.setText("\n".join(summary_lines) if summary_lines else "最近一次模板执行摘要将在这里显示")

        self.artifact_list.clear()
        for key, value in artifacts.items():
            self.artifact_list.addItem(f"{key}: {value}")

    def clear_execution_summary(self):
        self.execution_title.setText("模板执行: 暂无")
        self.execution_summary.setText("最近一次模板执行摘要将在这里显示")
        self.artifact_list.clear()

    def closeEvent(self, event):
        print("UI 面板被关闭，正在停止服务器...")
        self.stop_server()
        self.closed.emit()
        super().closeEvent(event)
