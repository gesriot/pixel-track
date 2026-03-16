from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsObject,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from pixel_track.model import Calibration, MeasurementStep, Point


class _OverlayHandleItem(QGraphicsObject):
    handle_moved = Signal(str, float, float)
    handle_released = Signal(str, float, float)

    def __init__(
        self,
        role: str,
        stroke_color: str,
        fill_color: str,
        radius: float = 6.0,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._radius = radius
        self._pen = QPen(QColor(stroke_color), 1.5)
        self._pen.setCosmetic(True)
        self._brush = QBrush(QColor(fill_color))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(10.0)
        self.set_interactive(False)

    def boundingRect(self) -> QRectF:
        diameter = self._radius * 2
        return QRectF(-self._radius, -self._radius, diameter, diameter)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        painter.setPen(self._pen)
        painter.setBrush(self._brush)
        painter.drawEllipse(self.boundingRect())

    def set_interactive(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enabled)
        self.setAcceptedMouseButtons(Qt.LeftButton if enabled else Qt.NoButton)
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.ArrowCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            next_pos = self.pos() if not isinstance(value, QPointF) else value
            self.handle_moved.emit(self._role, next_pos.x(), next_pos.y())
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
            self.setCursor(Qt.OpenHandCursor)
            current_pos = self.pos()
            self.handle_released.emit(self._role, current_pos.x(), current_pos.y())


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)
    scene_clicked = Signal(float, float)
    scene_hovered = Signal(float, float)
    overlay_handle_released = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._placeholder_item: QGraphicsSimpleTextItem | None = None
        self._calibration: Calibration | None = None
        self._calibration_line_item: QGraphicsLineItem | None = None
        self._preview_line_item: QGraphicsLineItem | None = None
        self._endpoint_items: dict[str, _OverlayHandleItem] = {}
        self._calibration_label_item: QGraphicsSimpleTextItem | None = None
        self._measurement: MeasurementStep | None = None
        self._measurement_line_item: QGraphicsLineItem | None = None
        self._measurement_endpoint_items: dict[str, _OverlayHandleItem] = {}
        self._measurement_label_items: dict[str, QGraphicsSimpleTextItem] = {}
        self._user_zoom_factor = 1.0
        self._center_norm = (0.5, 0.5)
        self._center_scene_pos: QPointF | None = None
        self._click_press_pos: QPoint | None = None
        self._preview_start: Point | None = None
        self._preview_end: Point | None = None
        self._zoom_correction_generation = 0
        self._suspend_center_capture = False
        self._edit_handles_enabled = False
        self._updating_handle_geometry = False

        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.darkGray)
        self.show_placeholder(
            "Sprint 6\n\nOpen frames, calibrate, then mark or drag points to measure motion."
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
        self._measurement = None
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
        if calibration is None:
            self._calibration = None
        else:
            self._calibration = Calibration(calibration.p1, calibration.p2, calibration.length_m)
        self._redraw_overlay()

    def set_measurement(self, measurement: MeasurementStep | None) -> None:
        if measurement is None:
            self._measurement = None
        else:
            self._measurement = MeasurementStep(
                frame_index=measurement.frame_index,
                current_point_px=measurement.current_point_px,
                previous_point_on_this_frame_px=measurement.previous_point_on_this_frame_px,
                previous_point_is_auto=measurement.previous_point_is_auto,
            )
        self._redraw_overlay()

    def set_edit_handles_enabled(self, enabled: bool) -> None:
        self._edit_handles_enabled = enabled
        self._update_handle_interactivity()

    def zoom_in(self) -> None:
        self._zoom_relative(1.15)

    def zoom_out(self) -> None:
        self._zoom_relative(1 / 1.15)

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
        self._endpoint_items = {}
        self._calibration_label_item = None
        self._measurement_line_item = None
        self._measurement_endpoint_items = {}
        self._measurement_label_items = {}

    def _redraw_overlay(self) -> None:
        self._remove_calibration_items()
        self._remove_preview_item()
        self._remove_measurement_items()
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
            self._endpoint_items["calibration_p1"] = self._create_handle_item(
                "calibration_p1",
                self._calibration.p1,
                "#0b7285",
                "#99e9f2",
            )
            self._endpoint_items["calibration_p2"] = self._create_handle_item(
                "calibration_p2",
                self._calibration.p2,
                "#0b7285",
                "#99e9f2",
            )

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

        self._redraw_measurement_items()
        self._redraw_preview_line()
        self._update_handle_interactivity()

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
        for item in self._endpoint_items.values():
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._endpoint_items = {}

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

    def _redraw_measurement_items(self) -> None:
        if self._pixmap_item is None or self._measurement is None:
            return

        previous_point = self._measurement.previous_point_on_this_frame_px
        current_point = self._measurement.current_point_px

        if previous_point is not None and current_point is not None:
            line_pen = QPen(QColor("#ffd43b"), 2.0)
            line_pen.setCosmetic(True)
            self._measurement_line_item = self._scene.addLine(
                previous_point[0],
                previous_point[1],
                current_point[0],
                current_point[1],
                line_pen,
            )

        if previous_point is not None:
            self._add_measurement_marker(
                "measurement_previous",
                previous_point,
                "#e8590c",
                "#ffd8a8",
                "P",
            )

        if current_point is not None:
            self._add_measurement_marker(
                "measurement_current",
                current_point,
                "#2b8a3e",
                "#b2f2bb",
                "C",
            )

    def _add_measurement_marker(
        self,
        role: str,
        point: Point,
        stroke_color: str,
        fill_color: str,
        label: str,
    ) -> None:
        marker = self._create_handle_item(role, point, stroke_color, fill_color)
        self._measurement_endpoint_items[role] = marker

        text = self._scene.addSimpleText(label)
        text.setBrush(QColor("white"))
        text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        text.setPos(point[0] + 10, point[1] - 10)
        self._measurement_label_items[role] = text

    def _remove_measurement_items(self) -> None:
        if self._measurement_line_item is not None:
            if self._measurement_line_item.scene() is self._scene:
                self._scene.removeItem(self._measurement_line_item)
            self._measurement_line_item = None

        for item in self._measurement_endpoint_items.values():
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._measurement_endpoint_items = {}

        for item in self._measurement_label_items.values():
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._measurement_label_items = {}

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

    def _zoom_relative(self, factor: float) -> None:
        if self._pixmap_item is None:
            return
        viewport_center = QPointF(self.viewport().rect().center())
        next_zoom = min(25.0, max(0.2, self._user_zoom_factor * factor))
        self._apply_zoom_at_viewport_pos(viewport_center, next_zoom)

    def _create_handle_item(
        self,
        role: str,
        point: Point,
        stroke_color: str,
        fill_color: str,
    ) -> _OverlayHandleItem:
        item = _OverlayHandleItem(role, stroke_color, fill_color)
        item.setPos(point[0], point[1])
        item.set_interactive(self._edit_handles_enabled)
        item.handle_moved.connect(self._on_overlay_handle_dragged)
        item.handle_released.connect(self._on_overlay_handle_released)
        self._scene.addItem(item)
        return item

    def _update_handle_interactivity(self) -> None:
        for item in list(self._endpoint_items.values()) + list(self._measurement_endpoint_items.values()):
            item.set_interactive(self._edit_handles_enabled)

    def _on_overlay_handle_dragged(self, role: str, x: float, y: float) -> None:
        if self._updating_handle_geometry:
            return

        point = (x, y)
        if role == "calibration_p1" and self._calibration is not None:
            self._calibration = Calibration(point, self._calibration.p2, self._calibration.length_m)
            self._refresh_calibration_geometry()
            return

        if role == "calibration_p2" and self._calibration is not None:
            self._calibration = Calibration(self._calibration.p1, point, self._calibration.length_m)
            self._refresh_calibration_geometry()
            return

        if self._measurement is None:
            return

        if role == "measurement_previous":
            self._measurement.previous_point_on_this_frame_px = point
            self._measurement.previous_point_is_auto = False
            self._refresh_measurement_geometry()
        elif role == "measurement_current":
            self._measurement.current_point_px = point
            self._refresh_measurement_geometry()

    def _on_overlay_handle_released(self, role: str, x: float, y: float) -> None:
        self.overlay_handle_released.emit(role, x, y)

    def _refresh_calibration_geometry(self) -> None:
        if self._calibration is None:
            return
        self._updating_handle_geometry = True
        try:
            if self._calibration_line_item is not None:
                self._calibration_line_item.setLine(
                    self._calibration.p1[0],
                    self._calibration.p1[1],
                    self._calibration.p2[0],
                    self._calibration.p2[1],
                )

            handle = self._endpoint_items.get("calibration_p1")
            if handle is not None:
                handle.setPos(self._calibration.p1[0], self._calibration.p1[1])
            handle = self._endpoint_items.get("calibration_p2")
            if handle is not None:
                handle.setPos(self._calibration.p2[0], self._calibration.p2[1])

            if self._calibration_label_item is not None:
                midpoint_x = (self._calibration.p1[0] + self._calibration.p2[0]) / 2
                midpoint_y = (self._calibration.p1[1] + self._calibration.p2[1]) / 2
                self._calibration_label_item.setText(f"{self._calibration.length_m:.3f} m")
                self._calibration_label_item.setPos(midpoint_x + 8, midpoint_y + 8)
        finally:
            self._updating_handle_geometry = False

    def _refresh_measurement_geometry(self) -> None:
        if self._measurement is None:
            return

        previous_point = self._measurement.previous_point_on_this_frame_px
        current_point = self._measurement.current_point_px
        self._updating_handle_geometry = True
        try:
            if previous_point is not None and current_point is not None:
                if self._measurement_line_item is None:
                    line_pen = QPen(QColor("#ffd43b"), 2.0)
                    line_pen.setCosmetic(True)
                    self._measurement_line_item = self._scene.addLine(
                        previous_point[0],
                        previous_point[1],
                        current_point[0],
                        current_point[1],
                        line_pen,
                    )
                else:
                    self._measurement_line_item.setLine(
                        previous_point[0],
                        previous_point[1],
                        current_point[0],
                        current_point[1],
                    )
            elif self._measurement_line_item is not None:
                if self._measurement_line_item.scene() is self._scene:
                    self._scene.removeItem(self._measurement_line_item)
                self._measurement_line_item = None

            previous_handle = self._measurement_endpoint_items.get("measurement_previous")
            if previous_point is not None and previous_handle is not None:
                previous_handle.setPos(previous_point[0], previous_point[1])
            previous_label = self._measurement_label_items.get("measurement_previous")
            if previous_point is not None and previous_label is not None:
                previous_label.setPos(previous_point[0] + 10, previous_point[1] - 10)

            current_handle = self._measurement_endpoint_items.get("measurement_current")
            if current_point is not None and current_handle is not None:
                current_handle.setPos(current_point[0], current_point[1])
            current_label = self._measurement_label_items.get("measurement_current")
            if current_point is not None and current_label is not None:
                current_label.setPos(current_point[0] + 10, current_point[1] - 10)
        finally:
            self._updating_handle_geometry = False
