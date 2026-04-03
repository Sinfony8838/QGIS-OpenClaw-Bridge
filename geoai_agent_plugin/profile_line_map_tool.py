# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand


class ProfileLineMapTool(QgsMapTool):
    line_finished = pyqtSignal(list)
    status_message = pyqtSignal(str)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.points = []
        self.committed_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.preview_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)

        self.committed_band.setColor(QColor("#d1495b"))
        self.committed_band.setWidth(2)
        self.preview_band.setColor(QColor("#457b9d"))
        self.preview_band.setWidth(2)

    def activate(self):
        super().activate()
        self.reset()
        self.status_message.emit("Click to draw a profile line. Double click or right click to finish.")

    def deactivate(self):
        self.clear_bands()
        super().deactivate()

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._append_point(self.toMapCoordinates(event.pos()))
            self._sync_preview()
        elif event.button() == Qt.RightButton:
            self._finish_drawing()

    def canvasMoveEvent(self, event):
        if not self.points:
            return
        point = self.toMapCoordinates(event.pos())
        self._sync_preview(point)

    def canvasDoubleClickEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        if not self.points or not self._same_point(self.points[-1], point):
            self._append_point(point)
        self._finish_drawing()

    def reset(self):
        self.points = []
        self.clear_bands()

    def clear_bands(self):
        self.committed_band.reset(QgsWkbTypes.LineGeometry)
        self.preview_band.reset(QgsWkbTypes.LineGeometry)

    def _append_point(self, point):
        point_xy = QgsPointXY(point)
        self.points.append(point_xy)
        if len(self.points) == 1:
            self.committed_band.addPoint(point_xy, False)
        self.committed_band.addPoint(point_xy, True)

    def _sync_preview(self, trailing_point=None):
        self.preview_band.reset(QgsWkbTypes.LineGeometry)
        if not self.points:
            return

        all_points = list(self.points)
        if trailing_point is not None:
            all_points.append(QgsPointXY(trailing_point))
        self.preview_band.setToGeometry(QgsGeometry.fromPolylineXY(all_points), None)

    def _finish_drawing(self):
        if len(self.points) < 2:
            self.status_message.emit("At least two points are required to create a profile line.")
            self.reset()
            return

        finished_points = list(self.points)
        self.reset()
        self.line_finished.emit(finished_points)

    def _same_point(self, first, second, tolerance=1e-9):
        return abs(first.x() - second.x()) <= tolerance and abs(first.y() - second.y()) <= tolerance
