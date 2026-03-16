from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._placeholder_item: QGraphicsSimpleTextItem | None = None
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)

        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.darkGray)
        self.show_placeholder(
            "Sprint 1\n\nOpen a folder with frames to start browsing the sequence."
        )

    @property
    def zoom_factor(self) -> float:
        return self._user_zoom_factor

    def reset_view_state(self) -> None:
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self._apply_view_state()

    def show_placeholder(self, text: str) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._placeholder_item = self._scene.addSimpleText(text)
        self._placeholder_item.setBrush(Qt.white)
        self._placeholder_item.setPos(40, 40)
        self._scene.setSceneRect(0, 0, 1280, 720)
        self.resetTransform()
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self.zoom_changed.emit(self._user_zoom_factor)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._capture_center_norm()
        self._scene.clear()
        self._placeholder_item = None
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._apply_view_state()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap_item is None:
            super().wheelEvent(event)
            return

        zoom_step = 1.15
        if event.angleDelta().y() == 0:
            event.accept()
            return

        factor = zoom_step if event.angleDelta().y() > 0 else 1 / zoom_step
        next_zoom = min(25.0, max(0.2, self._user_zoom_factor * factor))
        factor = next_zoom / self._user_zoom_factor
        self._user_zoom_factor = next_zoom

        self.scale(factor, factor)
        self._capture_center_norm()
        self.zoom_changed.emit(self._user_zoom_factor)
        event.accept()

    def resizeEvent(self, event) -> None:
        self._capture_center_norm()
        super().resizeEvent(event)
        self._apply_view_state()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._capture_center_norm()

    def _apply_view_state(self) -> None:
        rect = self.sceneRect()
        if rect.isEmpty():
            return

        self.resetTransform()
        fit_scale = self._fit_scale(rect)
        total_scale = fit_scale * self._user_zoom_factor
        self.scale(total_scale, total_scale)
        self.centerOn(self._scene_point_from_norm(rect))
        self.zoom_changed.emit(self._user_zoom_factor)

    def _capture_center_norm(self) -> None:
        rect = self.sceneRect()
        if rect.isEmpty():
            return

        viewport_center = self.viewport().rect().center()
        scene_center = self.mapToScene(viewport_center)
        width = rect.width() or 1.0
        height = rect.height() or 1.0
        x = (scene_center.x() - rect.left()) / width
        y = (scene_center.y() - rect.top()) / height
        self._center_norm = (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    def _fit_scale(self, rect: QRectF) -> float:
        viewport = self.viewport().rect()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0
        return min(viewport.width() / rect.width(), viewport.height() / rect.height())

    def _scene_point_from_norm(self, rect: QRectF) -> QPointF:
        x_norm, y_norm = self._center_norm
        x = rect.left() + rect.width() * x_norm
        y = rect.top() + rect.height() * y_norm
        return QPointF(x, y)
