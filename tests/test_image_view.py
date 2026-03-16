import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from math import isclose

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from pixel_track.model import Calibration
from pixel_track.model import MeasurementStep
from pixel_track.ui.image_view import ImageView


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_set_pixmap_twice_keeps_calibration_overlay_alive() -> None:
    app = _app()
    view = ImageView()
    view.resize(800, 600)
    view.show()
    app.processEvents()

    pixmap = QPixmap(320, 240)
    pixmap.fill(QColor("black"))

    view.set_calibration(Calibration((10.0, 10.0), (110.0, 10.0), 10.0))
    view.set_pixmap(pixmap)
    first_line = view._calibration_line_item

    view.set_pixmap(pixmap)
    app.processEvents()

    assert first_line is not view._calibration_line_item
    assert view._calibration_line_item is not None
    assert view._calibration_line_item.scene() is view.scene()


def test_zoom_keeps_scene_point_under_cursor_stable() -> None:
    app = _app()
    view = ImageView()
    view.resize(800, 600)
    view.show()
    app.processEvents()

    pixmap = QPixmap(1200, 800)
    pixmap.fill(QColor("darkGray"))
    view.set_pixmap(pixmap)
    app.processEvents()

    viewport_pos = QPointF(350.0, 250.0)
    before = view.mapToScene(viewport_pos.toPoint())

    view._apply_zoom_at_viewport_pos(viewport_pos, 2.0)
    app.processEvents()

    after = view.mapToScene(viewport_pos.toPoint())
    assert isclose(before.x(), after.x(), abs_tol=1.0)
    assert isclose(before.y(), after.y(), abs_tol=1.0)


def test_set_pixmap_preserves_center_at_high_zoom() -> None:
    app = _app()
    view = ImageView()
    view.resize(1200, 800)
    view.show()
    app.processEvents()

    first = QPixmap(3000, 2000)
    first.fill(QColor("black"))
    second = QPixmap(3000, 2000)
    second.fill(QColor("darkBlue"))

    view.set_pixmap(first)
    app.processEvents()
    view._apply_zoom_at_viewport_pos(QPointF(500.0, 300.0), 10.0)
    app.processEvents()

    before = view.mapToScene(view.viewport().rect().center())
    view.set_pixmap(second)
    app.processEvents()
    after = view.mapToScene(view.viewport().rect().center())

    assert isclose(before.x(), after.x(), abs_tol=1.0)
    assert isclose(before.y(), after.y(), abs_tol=1.0)


def test_repeated_set_pixmap_does_not_accumulate_drift() -> None:
    app = _app()
    view = ImageView()
    view.resize(1200, 800)
    view.show()
    app.processEvents()

    first = QPixmap(3000, 2000)
    first.fill(QColor("black"))
    second = QPixmap(3000, 2000)
    second.fill(QColor("darkBlue"))

    view.set_pixmap(first)
    app.processEvents()
    view._apply_zoom_at_viewport_pos(QPointF(500.0, 300.0), 10.0)
    app.processEvents()

    initial = view.mapToScene(view.viewport().rect().center())

    for pixmap in [second, first, second, first]:
        view.set_pixmap(pixmap)
        app.processEvents()

    final = view.mapToScene(view.viewport().rect().center())
    assert isclose(initial.x(), final.x(), abs_tol=1.0)
    assert isclose(initial.y(), final.y(), abs_tol=1.0)


def test_edit_mode_makes_overlay_handles_movable() -> None:
    app = _app()
    view = ImageView()
    view.resize(800, 600)
    view.show()
    app.processEvents()

    pixmap = QPixmap(320, 240)
    pixmap.fill(QColor("black"))

    view.set_pixmap(pixmap)
    view.set_calibration(Calibration((10.0, 10.0), (110.0, 10.0), 10.0))
    view.set_measurement(
        MeasurementStep(
            frame_index=0,
            previous_point_on_this_frame_px=(30.0, 40.0),
            current_point_px=(90.0, 40.0),
        )
    )
    view.set_edit_handles_enabled(True)

    calibration_handle = view._endpoint_items["calibration_p1"]
    measurement_handle = view._measurement_endpoint_items["measurement_current"]

    assert calibration_handle.flags() & calibration_handle.GraphicsItemFlag.ItemIsMovable
    assert measurement_handle.flags() & measurement_handle.GraphicsItemFlag.ItemIsMovable


def test_dragging_measurement_handle_updates_overlay_geometry() -> None:
    app = _app()
    view = ImageView()
    view.resize(800, 600)
    view.show()
    app.processEvents()

    pixmap = QPixmap(320, 240)
    pixmap.fill(QColor("black"))

    view.set_pixmap(pixmap)
    view.set_measurement(
        MeasurementStep(
            frame_index=0,
            previous_point_on_this_frame_px=(30.0, 40.0),
            current_point_px=(90.0, 40.0),
        )
    )
    view.set_edit_handles_enabled(True)
    current_handle = view._measurement_endpoint_items["measurement_current"]

    current_handle.setPos(120.0, 60.0)
    app.processEvents()

    assert view._measurement is not None
    assert view._measurement.current_point_px == (120.0, 60.0)
    assert view._measurement_line_item is not None
    line = view._measurement_line_item.line()
    assert isclose(line.x2(), 120.0, abs_tol=0.01)
    assert isclose(line.y2(), 60.0, abs_tol=0.01)
