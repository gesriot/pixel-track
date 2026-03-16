from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from pixel_track.model import Calibration, Point


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)
    scene_clicked = Signal(float, float)
    scene_hovered = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._placeholder_item: QGraphicsSimpleTextItem | None = None
        self._calibration: Calibration | None = None
        self._calibration_line_item: QGraphicsLineItem | None = None
        self._preview_line_item: QGraphicsLineItem | None = None
        self._endpoint_items: list[QGraphicsEllipseItem] = []
        self._calibration_label_item: QGraphicsSimpleTextItem | None = None
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self._center_scene_pos: QPointF | None = None
        self._click_press_pos: QPoint | None = None
        self._preview_start: Point | None = None
        self._preview_end: Point | None = None
        self._zoom_correction_generation = 0
        self._suspend_center_capture = False

        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.darkGray)
        self.show_placeholder(
            "Sprint 2\n\nOpen a folder with frames and use Calibrate mode to mark a known distance."
        )

    @property
    def zoom_factor(self) -> float:
        return self._user_zoom_factor

    def reset_view_state(self) -> None:
        self._invalidate_pending_zoom_corrections()
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self._center_scene_pos = None
        self._apply_view_state()

    def show_placeholder(self, text: str) -> None:
        self._invalidate_pending_zoom_corrections()
        self._reset_scene_item_refs()
        self._scene.clear()
        self._pixmap_item = None
        self._placeholder_item = self._scene.addSimpleText(text)
        self._placeholder_item.setBrush(Qt.white)
        self._placeholder_item.setPos(40, 40)
        self._scene.setSceneRect(0, 0, 1280, 720)
        self._calibration = None
        self._preview_start = None
        self._preview_end = None
        self.resetTransform()
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self._center_scene_pos = QPointF(640.0, 360.0)
        self.zoom_changed.emit(self._user_zoom_factor)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._invalidate_pending_zoom_corrections()
        had_pixmap = self._pixmap_item is not None
        previous_rect = self.sceneRect()

        if had_pixmap:
            self._capture_center_norm()

        self._suspend_center_capture = True
        try:
            if self._placeholder_item is not None and self._placeholder_item.scene() is self._scene:
                self._scene.removeItem(self._placeholder_item)
                self._placeholder_item = None

            if self._pixmap_item is None:
                self._pixmap_item = self._scene.addPixmap(pixmap)
            else:
                self._pixmap_item.setPixmap(pixmap)

            current_rect = self._pixmap_item.boundingRect()
            self._scene.setSceneRect(current_rect)
            self._redraw_overlay()
        finally:
            self._suspend_center_capture = False

        if not had_pixmap or previous_rect.size() != current_rect.size():
            self._apply_view_state()
        else:
            self._capture_center_norm()

    def set_calibration(self, calibration: Calibration | None) -> None:
        self._calibration = calibration
        self._redraw_overlay()

    def set_calibration_preview(self, start: Point | None, end: Point | None = None) -> None:
        self._preview_start = start
        self._preview_end = end
        self._redraw_preview_line()

    def clear_calibration_preview(self) -> None:
        self._preview_start = None
        self._preview_end = None
        self._redraw_preview_line()

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
        self._apply_zoom_at_viewport_pos(event.position(), next_zoom)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._click_press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pixmap_item is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(scene_pos):
                self.scene_hovered.emit(scene_pos.x(), scene_pos.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self._click_press_pos is not None
            and self._pixmap_item is not None
        ):
            delta = event.position().toPoint() - self._click_press_pos
            if delta.manhattanLength() <= 4:
                scene_pos = self.mapToScene(event.position().toPoint())
                if self.sceneRect().contains(scene_pos):
                    self.scene_clicked.emit(scene_pos.x(), scene_pos.y())
        self._click_press_pos = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        self._capture_center_norm()
        super().resizeEvent(event)
        self._apply_view_state()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if not self._suspend_center_capture:
            self._capture_center_norm()

    def _apply_view_state(self) -> None:
        rect = self.sceneRect()
        if rect.isEmpty():
            return

        desired_center_norm = self._center_norm
        desired_center_scene_pos = self._center_scene_pos
        self._suspend_center_capture = True
        try:
            self.resetTransform()
            fit_scale = self._fit_scale(rect)
            total_scale = fit_scale * self._user_zoom_factor
            self.scale(total_scale, total_scale)
            if desired_center_scene_pos is not None:
                self.centerOn(self._clamp_scene_point(rect, desired_center_scene_pos))
            else:
                self.centerOn(self._scene_point_from_norm(rect, desired_center_norm))
        finally:
            self._suspend_center_capture = False
        self._capture_center_norm()
        self.zoom_changed.emit(self._user_zoom_factor)

    def _capture_center_norm(self) -> None:
        rect = self.sceneRect()
        if rect.isEmpty():
            return

        viewport_center = self.viewport().rect().center()
        scene_center = self.mapToScene(viewport_center)
        self._center_scene_pos = scene_center
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

    def _scene_point_from_norm(
        self,
        rect: QRectF,
        center_norm: tuple[float, float] | None = None,
    ) -> QPointF:
        x_norm, y_norm = self._center_norm if center_norm is None else center_norm
        x = rect.left() + rect.width() * x_norm
        y = rect.top() + rect.height() * y_norm
        return QPointF(x, y)

    def _clamp_scene_point(self, rect: QRectF, point: QPointF) -> QPointF:
        x = min(rect.right(), max(rect.left(), point.x()))
        y = min(rect.bottom(), max(rect.top(), point.y()))
        return QPointF(x, y)

    def _reset_scene_item_refs(self) -> None:
        self._calibration_line_item = None
        self._preview_line_item = None
        self._endpoint_items = []
        self._calibration_label_item = None

    def _redraw_overlay(self) -> None:
        self._remove_calibration_items()
        self._remove_preview_item()
        if self._pixmap_item is None:
            return

        if self._calibration is not None:
            line_pen = QPen(QColor("#4cc9f0"), 2.0)
            line_pen.setCosmetic(True)
            self._calibration_line_item = self._scene.addLine(
                self._calibration.p1[0],
                self._calibration.p1[1],
                self._calibration.p2[0],
                self._calibration.p2[1],
                line_pen,
            )

            endpoint_pen = QPen(QColor("#0b7285"), 1.5)
            endpoint_pen.setCosmetic(True)
            for point in (self._calibration.p1, self._calibration.p2):
                item = self._scene.addEllipse(
                    -5,
                    -5,
                    10,
                    10,
                    endpoint_pen,
                    QBrush(QColor("#99e9f2")),
                )
                item.setPos(point[0], point[1])
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                self._endpoint_items.append(item)

            midpoint_x = (self._calibration.p1[0] + self._calibration.p2[0]) / 2
            midpoint_y = (self._calibration.p1[1] + self._calibration.p2[1]) / 2
            self._calibration_label_item = self._scene.addSimpleText(
                f"{self._calibration.length_m:.3f} m"
            )
            self._calibration_label_item.setBrush(QColor("white"))
            self._calibration_label_item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
            )
            self._calibration_label_item.setPos(midpoint_x + 8, midpoint_y + 8)

        self._redraw_preview_line()

    def _redraw_preview_line(self) -> None:
        self._remove_preview_item()
        if self._pixmap_item is None or self._preview_start is None or self._preview_end is None:
            return

        preview_pen = QPen(QColor("#ffd43b"), 2.0, Qt.PenStyle.DashLine)
        preview_pen.setCosmetic(True)
        self._preview_line_item = self._scene.addLine(
            self._preview_start[0],
            self._preview_start[1],
            self._preview_end[0],
            self._preview_end[1],
            preview_pen,
        )

    def _remove_calibration_items(self) -> None:
        for item in self._endpoint_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._endpoint_items = []

        if self._calibration_line_item is not None:
            if self._calibration_line_item.scene() is self._scene:
                self._scene.removeItem(self._calibration_line_item)
            self._calibration_line_item = None

        if self._calibration_label_item is not None:
            if self._calibration_label_item.scene() is self._scene:
                self._scene.removeItem(self._calibration_label_item)
            self._calibration_label_item = None

    def _remove_preview_item(self) -> None:
        if self._preview_line_item is not None:
            if self._preview_line_item.scene() is self._scene:
                self._scene.removeItem(self._preview_line_item)
            self._preview_line_item = None

    def _apply_zoom_at_viewport_pos(self, viewport_pos: QPointF, next_zoom: float) -> None:
        if self._pixmap_item is None:
            return

        anchor_scene_pos = self.mapToScene(viewport_pos.toPoint())
        factor = next_zoom / self._user_zoom_factor
        self._user_zoom_factor = next_zoom
        self._suspend_center_capture = True
        try:
            self.scale(factor, factor)
            moved_scene_pos = self.mapToScene(viewport_pos.toPoint())
            delta = moved_scene_pos - anchor_scene_pos
            current_center = self.mapToScene(self.viewport().rect().center())
            self.centerOn(current_center - delta)
        finally:
            self._suspend_center_capture = False
        self._capture_center_norm()
        self.zoom_changed.emit(self._user_zoom_factor)
        self._zoom_correction_generation += 1
        generation = self._zoom_correction_generation
        QTimer.singleShot(
            0,
            lambda: self._finalize_zoom_anchor(generation, anchor_scene_pos, QPointF(viewport_pos)),
        )

    def _finalize_zoom_anchor(
        self,
        generation: int,
        anchor_scene_pos: QPointF,
        viewport_pos: QPointF,
    ) -> None:
        if generation != self._zoom_correction_generation or self._pixmap_item is None:
            return

        moved_scene_pos = self.mapToScene(viewport_pos.toPoint())
        delta = moved_scene_pos - anchor_scene_pos
        self._suspend_center_capture = True
        try:
            current_center = self.mapToScene(self.viewport().rect().center())
            self.centerOn(current_center - delta)
        finally:
            self._suspend_center_capture = False
        self._capture_center_norm()

    def _invalidate_pending_zoom_corrections(self) -> None:
        self._zoom_correction_generation += 1
