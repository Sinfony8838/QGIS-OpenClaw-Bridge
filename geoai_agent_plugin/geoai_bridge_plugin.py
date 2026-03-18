# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt
from .geoai_dock_widget import GeoaiDockWidget

class GeoaiBridgePlugin:
    """
    QGIS 插件主类。
    """

    def __init__(self, iface):
        self.iface = iface
        self.dock_widget = None
        self.action = None

    def initGui(self):
        # 创建菜单和工具栏按钮
        self.action = QAction("GeoAI Agent 控制台", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dock)

        self.iface.addPluginToMenu("&GeoAI Agent", self.action)
        self.iface.addToolBarIcon(self.action)
      

    def unload(self):
        if self.dock_widget:
            self.dock_widget.stop_server()
            self.iface.removeDockWidget(self.dock_widget)

        self.iface.removePluginMenu("&GeoAI Agent", self.action)
        self.iface.removeToolBarIcon(self.action)

    def toggle_dock(self, checked):
        if checked:
            if not self.dock_widget:
                self.dock_widget = GeoaiDockWidget(self.iface)
                self.dock_widget.closed.connect(self.dock_closed)

            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            self.dock_widget.show()
        else:
            if self.dock_widget:
                self.dock_widget.hide()

    def dock_closed(self):
        if self.action:
            self.action.setChecked(False)